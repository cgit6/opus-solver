"""CDELS 2 Workspace 版的 Numba 熱路徑實作。

這個模組以 :mod:`CDELS_2` 為行為基準，不修改原檔。目前已將完整
reevaluation、two-swap、reinsertion、strong-drop、transfer、不可行修復、
完整 local search、mutation、crossover、SA 與 selection 純值決策搬入 Numba。
Python 只保留 Workspace Individual 及 population 引用搬移，以及溫度／停止控制。
每完成一個模組後，
必須通過狀態、RNG、Workspace identity 與逐代 digest 比對才能繼續。
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import ClassVar

import numpy as np
from numba import njit

from ..problem.scvrp import (
    LEGACY_INFEASIBILITY_PENALTY,
    SCVRPEvaluation,
    SCVRPProblem,
)
from .CDELS_2 import (
    CDELS2,
    CDELS_CR,
    CDELS_F,
    CDELSGeneration,
    CDELSIndividual,
    CDELS2Solver,
)


@njit(cache=True)
def _reevaluate_workspace_numba(
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    transfer_mask: np.ndarray,
    demands: np.ndarray,
    distances: np.ndarray,
    fixed_route_for_customer: np.ndarray,
    fixed_route_capacities: np.ndarray,
    capacity: int,
    transfer_cost_once: int,
    route_capacities_free: np.ndarray,
    transfer_capacities_free: np.ndarray,
) -> tuple[int, int, int, int, bool, bool]:
    """以預配置的扁平 route buffer 完整重建 legacy 狀態。"""
    route_count = route_offsets.shape[0] - 1
    for route_index in range(route_count):
        route_capacities_free[route_index] = capacity
    for fixed_index in range(fixed_route_capacities.shape[0]):
        transfer_capacities_free[fixed_index] = fixed_route_capacities[
            fixed_index
        ]

    route_cost = 0
    for route_index in range(route_count):
        customer_before = 0
        start = int(route_offsets[route_index])
        end = int(route_offsets[route_index + 1])
        for flat_index in range(start, end):
            customer = int(route_customers[flat_index])
            if transfer_mask[customer] != 0:
                continue
            route_capacities_free[route_index] -= demands[customer]
            route_cost += distances[customer_before, customer]
            customer_before = customer
        route_cost += distances[customer_before, 0]

    transferred_demand = 0
    for customer in range(1, transfer_mask.shape[0]):
        if transfer_mask[customer] == 0:
            continue
        demand = int(demands[customer])
        transferred_demand += demand
        fixed_index = int(fixed_route_for_customer[customer])
        transfer_capacities_free[fixed_index] -= demand

    transfer_vehicle_count = 0
    if transferred_demand != 0:
        transfer_vehicle_count = (
            transferred_demand + capacity - 1
        ) // capacity
    objective = route_cost + transfer_vehicle_count * transfer_cost_once

    legacy_feasible = True
    for route_index in range(route_count):
        if route_capacities_free[route_index] < 0:
            legacy_feasible = False
            break
    fixed_routes_feasible = True
    for fixed_index in range(transfer_capacities_free.shape[0]):
        if transfer_capacities_free[fixed_index] < 0:
            fixed_routes_feasible = False
            break

    legacy_search_score = objective
    if not legacy_feasible:
        legacy_search_score += LEGACY_INFEASIBILITY_PENALTY
    return (
        int(route_cost),
        int(transferred_demand),
        int(transfer_vehicle_count),
        int(legacy_search_score),
        legacy_feasible,
        legacy_feasible and fixed_routes_feasible,
    )


@njit(cache=True)
def _nearest_nontransfer_neighbors_numba(
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    customer_preceding: int,
    customer_successor: int,
) -> tuple[int, int]:
    """跳過 transfer customer；邏輯順序與基準版完全相同。"""
    if transfer_mask[customer_successor] != 0:
        route_index = int(positions[0, customer_successor])
        position = int(positions[1, customer_successor])
        route_end = int(route_offsets[route_index + 1] - route_offsets[route_index])
        while transfer_mask[customer_successor] != 0 and customer_successor != 0:
            position += 1
            if position < route_end:
                customer_successor = int(
                    route_customers[int(route_offsets[route_index]) + position]
                )
            else:
                customer_successor = 0

    if transfer_mask[customer_preceding] != 0:
        route_index = int(positions[0, customer_preceding])
        position = int(positions[1, customer_preceding])
        while transfer_mask[customer_preceding] != 0 and customer_preceding != 0:
            position -= 1
            if position >= 0:
                customer_preceding = int(
                    route_customers[int(route_offsets[route_index]) + position]
                )
            else:
                customer_preceding = 0

    return customer_preceding, customer_successor


@njit(cache=True)
def _swap_cost_exclusive_numba(
    distances: np.ndarray,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    customer_preceding: int,
    customer_successor: int,
    customer_old: int,
    customer_new: int,
    cost: int,
) -> int:
    """Numba 版跨 route 交換成本，包含舊 C++ 的 mixed-transfer typo。"""
    customer_preceding, customer_successor = _nearest_nontransfer_neighbors_numba(
        route_customers,
        route_offsets,
        positions,
        transfer_mask,
        customer_preceding,
        customer_successor,
    )
    old_transfer = int(transfer_mask[customer_old])
    new_transfer = int(transfer_mask[customer_new])

    if old_transfer == 0 and new_transfer == 0:
        result = int(
            cost
            - distances[customer_preceding, customer_old]
            - distances[customer_old, customer_successor]
        )

        if not (
            transfer_mask[customer_successor] == 0
            and customer_successor != customer_new
        ):
            if (
                transfer_mask[customer_successor] == 0
                and customer_successor == customer_new
            ):
                customer_successor = customer_old
            else:
                route_index = int(positions[0, customer_successor])
                position = int(positions[1, customer_successor])
                route_end = int(
                    route_offsets[route_index + 1] - route_offsets[route_index]
                )
                while (
                    transfer_mask[customer_successor] != 0
                    and customer_successor != 0
                ) or customer_successor == customer_new:
                    position += 1
                    if position >= route_end:
                        customer_successor = 0
                        break
                    customer_successor = int(
                        route_customers[int(route_offsets[route_index]) + position]
                    )

        if not (
            transfer_mask[customer_preceding] == 0
            and customer_preceding != customer_new
        ):
            if (
                transfer_mask[customer_preceding] == 0
                and customer_preceding == customer_new
            ):
                customer_preceding = customer_old
            else:
                route_index = int(positions[0, customer_preceding])
                position = int(positions[1, customer_preceding])
                while (
                    transfer_mask[customer_preceding] != 0
                    and customer_preceding != 0
                ) or customer_preceding == customer_new:
                    position -= 1
                    if position < 0:
                        customer_preceding = 0
                        break
                    customer_preceding = int(
                        route_customers[int(route_offsets[route_index]) + position]
                    )

        return int(
            result
            + distances[customer_preceding, customer_new]
            + distances[customer_new, customer_successor]
        )

    if old_transfer == 1 and new_transfer == 0:
        return int(
            cost
            + distances[customer_preceding, customer_new]
            + distances[customer_new, customer_successor]
        )
    return int(cost)


@njit(cache=True)
def _swap_cost_inclusive_numba(
    distances: np.ndarray,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    i: int,
    j: int,
    customeri: int,
    icustomer_preceding: int,
    icustomer_successor: int,
    customerj: int,
    jcustomer_preceding: int,
    jcustomer_successor: int,
    cost: int,
) -> int:
    if i == j - 1:
        if transfer_mask[customeri] != 0 or transfer_mask[customerj] != 0:
            return int(cost)
        icustomer_preceding, jcustomer_successor = (
            _nearest_nontransfer_neighbors_numba(
                route_customers,
                route_offsets,
                positions,
                transfer_mask,
                icustomer_preceding,
                jcustomer_successor,
            )
        )
        return int(
            cost
            - distances[icustomer_preceding, customeri]
            - distances[customerj, jcustomer_successor]
            + distances[customerj, icustomer_preceding]
            + distances[customeri, jcustomer_successor]
        )

    return int(
        cost
        + _swap_cost_exclusive_numba(
            distances,
            route_customers,
            route_offsets,
            positions,
            transfer_mask,
            icustomer_preceding,
            icustomer_successor,
            customeri,
            customerj,
            0,
        )
        + _swap_cost_exclusive_numba(
            distances,
            route_customers,
            route_offsets,
            positions,
            transfer_mask,
            jcustomer_preceding,
            jcustomer_successor,
            customerj,
            customeri,
            0,
        )
    )


@njit(cache=True)
def _swap_customers_numba(
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    route_capacities_free: np.ndarray,
    customer1: int,
    load1: int,
    customer2: int,
    load2: int,
) -> None:
    route1 = int(positions[0, customer1])
    position1 = int(positions[1, customer1])
    route2 = int(positions[0, customer2])
    position2 = int(positions[1, customer2])
    effective_load1 = 0 if transfer_mask[customer1] == 1 else int(load1)
    effective_load2 = 0 if transfer_mask[customer2] == 1 else int(load2)

    flat1 = int(route_offsets[route1]) + position1
    flat2 = int(route_offsets[route2]) + position2
    route_customers[flat2] = customer1
    route_customers[flat1] = customer2
    positions[0, customer2] = route1
    positions[1, customer2] = position1
    route_capacities_free[route1] += effective_load1 - effective_load2
    positions[0, customer1] = route2
    positions[1, customer1] = position2
    route_capacities_free[route2] += effective_load2 - effective_load1


@njit(cache=True)
def _two_swap_numba(
    distances: np.ndarray,
    demands: np.ndarray,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    route_capacities_free: np.ndarray,
    original_cost: int,
    feasible: bool,
) -> tuple[int, bool]:
    """Numba nopython two-swap；掃描與 first-improvement 重啟順序不可調整。"""
    vehicle_count = route_offsets.shape[0] - 1
    for routei in range(vehicle_count):
        route_start_i = int(route_offsets[routei])
        route_endi = int(route_offsets[routei + 1] - route_start_i)
        for i in range(route_endi):
            while True:
                customeri = int(route_customers[route_start_i + i])
                customeri_transferred = int(transfer_mask[customeri])
                load = int(demands[customeri]) if customeri_transferred == 0 else 0
                i_pre = 0 if i == 0 else int(route_customers[route_start_i + i - 1])
                i_next = (
                    0
                    if i == route_endi - 1
                    else int(route_customers[route_start_i + i + 1])
                )
                improved = False

                for routej in range(routei, vehicle_count):
                    route_start_j = int(route_offsets[routej])
                    route_endj = int(route_offsets[routej + 1] - route_start_j)
                    j_start = i + 1 if routei == routej else 0
                    for j in range(j_start, route_endj):
                        customerj = int(route_customers[route_start_j + j])
                        # 保留 legacy typo：loadj 依 customer-i 的 transfer flag。
                        loadj = (
                            int(demands[customerj])
                            if customeri_transferred == 0
                            else 0
                        )

                        if routei != routej:
                            if (
                                route_capacities_free[routei] + load < loadj
                                or route_capacities_free[routej] + loadj < load
                            ):
                                continue
                            j_pre = (
                                0
                                if j == 0
                                else int(route_customers[route_start_j + j - 1])
                            )
                            j_next = (
                                0
                                if j == route_endj - 1
                                else int(route_customers[route_start_j + j + 1])
                            )
                            cost_new = int(
                                original_cost
                                + _swap_cost_exclusive_numba(
                                    distances,
                                    route_customers,
                                    route_offsets,
                                    positions,
                                    transfer_mask,
                                    i_pre,
                                    i_next,
                                    customeri,
                                    customerj,
                                    0,
                                )
                                + _swap_cost_exclusive_numba(
                                    distances,
                                    route_customers,
                                    route_offsets,
                                    positions,
                                    transfer_mask,
                                    j_pre,
                                    j_next,
                                    customerj,
                                    customeri,
                                    0,
                                )
                            )
                        else:
                            j_pre = int(route_customers[route_start_j + j - 1])
                            j_next = (
                                0
                                if j == route_endj - 1
                                else int(route_customers[route_start_j + j + 1])
                            )
                            cost_new = _swap_cost_inclusive_numba(
                                distances,
                                route_customers,
                                route_offsets,
                                positions,
                                transfer_mask,
                                i,
                                j,
                                customeri,
                                i_pre,
                                i_next,
                                customerj,
                                j_pre,
                                j_next,
                                original_cost,
                            )

                        if cost_new < original_cost:
                            original_cost = cost_new
                            if routei == routej:
                                _swap_customers_numba(
                                    route_customers,
                                    route_offsets,
                                    positions,
                                    transfer_mask,
                                    route_capacities_free,
                                    customeri,
                                    0,
                                    customerj,
                                    0,
                                )
                            else:
                                _swap_customers_numba(
                                    route_customers,
                                    route_offsets,
                                    positions,
                                    transfer_mask,
                                    route_capacities_free,
                                    customeri,
                                    load,
                                    customerj,
                                    loadj,
                                )
                            improved = True
                            break
                    if improved:
                        break
                if not improved:
                    break

    if not feasible:
        all_routes_feasible = True
        for route_index in range(vehicle_count):
            if route_capacities_free[route_index] < 0:
                all_routes_feasible = False
                break
        if all_routes_feasible:
            return (
                int(original_cost - LEGACY_INFEASIBILITY_PENALTY),
                True,
            )
    return int(original_cost), feasible


@njit(cache=True)
def _rebuild_positions_numba(
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
) -> None:
    """依 packed routes 重建 customer -> (route, local position)。"""
    route_count = route_offsets.shape[0] - 1
    for route_index in range(route_count):
        start = int(route_offsets[route_index])
        end = int(route_offsets[route_index + 1])
        for flat_index in range(start, end):
            customer = int(route_customers[flat_index])
            positions[0, customer] = route_index
            positions[1, customer] = flat_index - start


@njit(cache=True)
def _remove_customer_numba(
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    route_capacities_free: np.ndarray,
    customer: int,
    load: int,
) -> None:
    """從 packed route 移除 customer；尾端空格留作下一次 insert 使用。"""
    route_index = int(positions[0, customer])
    position = int(positions[1, customer])
    flat_index = int(route_offsets[route_index]) + position
    active_count = int(route_offsets[-1])
    if transfer_mask[customer] == 0:
        route_capacities_free[route_index] += int(load)
    for index in range(flat_index, active_count - 1):
        route_customers[index] = route_customers[index + 1]
    for index in range(route_index + 1, route_offsets.shape[0]):
        route_offsets[index] -= 1
    _rebuild_positions_numba(route_customers, route_offsets, positions)


@njit(cache=True)
def _insert_customer_numba(
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    route_capacities_free: np.ndarray,
    customer: int,
    load: int,
    new_index: int,
    new_route: int,
) -> None:
    """把 customer 插入 packed route；只能接在一次 remove 後於內部使用。

    remove 會在固定長度 buffer 尾端空出一格，本函式使用該空格完成右移；它
    不是可對完整 packed individual 單獨呼叫的公開操作。
    """
    active_count = int(route_offsets[-1])
    flat_index = int(route_offsets[new_route]) + int(new_index)
    for index in range(active_count, flat_index, -1):
        route_customers[index] = route_customers[index - 1]
    route_customers[flat_index] = customer
    for index in range(new_route + 1, route_offsets.shape[0]):
        route_offsets[index] += 1
    _rebuild_positions_numba(route_customers, route_offsets, positions)
    if transfer_mask[customer] == 0:
        route_capacities_free[new_route] -= int(load)


@njit(cache=True)
def _chosen_customer_neighbors_numba(
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    customer: int,
) -> tuple[int, int]:
    route_index = int(positions[0, customer])
    position = int(positions[1, customer])
    start = int(route_offsets[route_index])
    route_end = int(route_offsets[route_index + 1] - start)
    preceding = 0 if position == 0 else int(route_customers[start + position - 1])
    successor = (
        0
        if position == route_end - 1
        else int(route_customers[start + position + 1])
    )
    return preceding, successor


@njit(cache=True)
def _customer_removal_cost_numba(
    distances: np.ndarray,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    customer_preceding: int,
    customer_successor: int,
    customer: int,
    cost: int,
) -> int:
    if transfer_mask[customer] != 0:
        return int(cost)
    customer_preceding, customer_successor = _nearest_nontransfer_neighbors_numba(
        route_customers,
        route_offsets,
        positions,
        transfer_mask,
        customer_preceding,
        customer_successor,
    )
    return int(
        cost
        - distances[customer_preceding, customer]
        - distances[customer, customer_successor]
        + distances[customer_preceding, customer_successor]
    )


@njit(cache=True)
def _customer_insertion_cost_numba(
    distances: np.ndarray,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    customer_preceding: int,
    customer_successor: int,
    customer: int,
    cost: int,
) -> int:
    if transfer_mask[customer] != 0:
        return int(cost)
    customer_preceding, customer_successor = _nearest_nontransfer_neighbors_numba(
        route_customers,
        route_offsets,
        positions,
        transfer_mask,
        customer_preceding,
        customer_successor,
    )
    return int(
        cost
        + distances[customer_preceding, customer]
        + distances[customer, customer_successor]
        - distances[customer_preceding, customer_successor]
    )


@njit(cache=True)
def _best_insertion_in_route_numba(
    distances: np.ndarray,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    customer: int,
    route_index: int,
    base_cost: int,
) -> tuple[int, int]:
    start = int(route_offsets[route_index])
    route_end = int(route_offsets[route_index + 1] - start)
    best_cost = 0
    best_position = 0
    has_best = False
    customer_preceding = 0
    for position in range(route_end + 1):
        customer_successor = (
            int(route_customers[start + position])
            if position < route_end
            else 0
        )
        candidate_cost = _customer_insertion_cost_numba(
            distances,
            route_customers,
            route_offsets,
            positions,
            transfer_mask,
            customer_preceding,
            customer_successor,
            customer,
            base_cost,
        )
        if not has_best or candidate_cost < best_cost:
            best_cost = candidate_cost
            best_position = position
            has_best = True
        customer_preceding = customer_successor
    return int(best_cost), best_position


@njit(cache=True)
def _reinsert_customer_best_position_if_improves_numba(
    distances: np.ndarray,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    route_capacities_free: np.ndarray,
    customer: int,
    load: int,
    new_route_idx: int,
    current_cost: int,
) -> tuple[int, bool]:
    preceding, successor = _chosen_customer_neighbors_numba(
        route_customers,
        route_offsets,
        positions,
        customer,
    )
    base_cost = _customer_removal_cost_numba(
        distances,
        route_customers,
        route_offsets,
        positions,
        transfer_mask,
        preceding,
        successor,
        customer,
        current_cost,
    )
    destination_length = int(
        route_offsets[new_route_idx + 1] - route_offsets[new_route_idx]
    )

    if destination_length == 0:
        # 保留 legacy 行為：transfer customer 放入空 route 仍加 depot roundtrip。
        new_cost = int(
            base_cost + distances[0, customer] + distances[customer, 0]
        )
        if new_cost < current_cost:
            _remove_customer_numba(
                route_customers,
                route_offsets,
                positions,
                transfer_mask,
                route_capacities_free,
                customer,
                load,
            )
            _insert_customer_numba(
                route_customers,
                route_offsets,
                positions,
                transfer_mask,
                route_capacities_free,
                customer,
                load,
                0,
                new_route_idx,
            )
            return new_cost, True
        return current_cost, False

    new_cost, new_position = _best_insertion_in_route_numba(
        distances,
        route_customers,
        route_offsets,
        positions,
        transfer_mask,
        customer,
        new_route_idx,
        base_cost,
    )
    if new_cost < current_cost:
        _remove_customer_numba(
            route_customers,
            route_offsets,
            positions,
            transfer_mask,
            route_capacities_free,
            customer,
            load,
        )
        _insert_customer_numba(
            route_customers,
            route_offsets,
            positions,
            transfer_mask,
            route_capacities_free,
            customer,
            load,
            new_position,
            new_route_idx,
        )
        return new_cost, True
    return current_cost, False


@njit(cache=True)
def _strong_drop_numba(
    distances: np.ndarray,
    demands: np.ndarray,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    route_capacities_free: np.ndarray,
    possible_routes: np.ndarray,
    cost: int,
    feasible: bool,
) -> tuple[int, bool]:
    """Numba nopython strong-drop，保留搬移後跳過補位 customer 的行為。"""
    vehicle_count = route_offsets.shape[0] - 1
    possible_count = 0
    got_improvement = False

    for source_route_idx in range(vehicle_count):
        route_end = int(
            route_offsets[source_route_idx + 1]
            - route_offsets[source_route_idx]
        )
        load_old = -1
        if route_end > 0:
            component = 0
            while component < route_end:
                source_start = int(route_offsets[source_route_idx])
                customer = int(route_customers[source_start + component])
                load = (
                    int(demands[customer])
                    if transfer_mask[customer] == 0
                    else 0
                )

                if load > load_old or got_improvement:
                    possible_count = 0
                    for route_index in range(vehicle_count):
                        if (
                            route_index != source_route_idx
                            and load <= route_capacities_free[route_index]
                        ):
                            possible_routes[possible_count] = route_index
                            possible_count += 1

                got_improvement = False
                for possible_index in range(possible_count):
                    destination_route_idx = int(possible_routes[possible_index])
                    cost, improved = (
                        _reinsert_customer_best_position_if_improves_numba(
                            distances,
                            route_customers,
                            route_offsets,
                            positions,
                            transfer_mask,
                            route_capacities_free,
                            customer,
                            load,
                            destination_route_idx,
                            cost,
                        )
                    )
                    if not got_improvement:
                        got_improvement = improved

                if got_improvement:
                    route_end = int(
                        route_offsets[source_route_idx + 1]
                        - route_offsets[source_route_idx]
                    )
                load_old = load
                component += 1

    if not feasible:
        all_routes_feasible = True
        for route_index in range(vehicle_count):
            if route_capacities_free[route_index] < 0:
                all_routes_feasible = False
                break
        if all_routes_feasible:
            return (
                int(cost - LEGACY_INFEASIBILITY_PENALTY),
                True,
            )
    return int(cost), feasible


@njit(cache=True)
def _msvc_rand_numba(state: int, draw_count: int) -> tuple[int, int, int]:
    """抽出一個 MSVC ``rand()``；state/draw count 必須由呼叫端保存。"""
    state = (state * 214_013 + 2_531_011) & 0xFFFF_FFFF
    draw_count += 1
    return state, draw_count, (state >> 16) & 0x7FFF


@njit(cache=True)
def _msvc_rand_mod_numba(
    state: int,
    draw_count: int,
    modulus: int,
) -> tuple[int, int, int]:
    if modulus <= 0:
        raise ValueError("modulus must be > 0")
    state, draw_count, value = _msvc_rand_numba(state, draw_count)
    return state, draw_count, value % modulus


@njit(cache=True)
def _try_turn_customer_to_transfer_numba(
    distances: np.ndarray,
    demands: np.ndarray,
    fixed_route_for_customer: np.ndarray,
    transfer_cost_once: int,
    capacity: int,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    transfer_capacities_free: np.ndarray,
    customer: int,
    cost: int,
    transfer_vehicle_count: int,
    transfer_total_capacity_free: int,
) -> tuple[int, int, int, bool]:
    if transfer_mask[customer] == 1:
        return cost, transfer_vehicle_count, transfer_total_capacity_free, False

    fixed_route = int(fixed_route_for_customer[customer])
    demand = int(demands[customer])
    if demand > transfer_capacities_free[fixed_route]:
        return cost, transfer_vehicle_count, transfer_total_capacity_free, False

    preceding, successor = _chosen_customer_neighbors_numba(
        route_customers,
        route_offsets,
        positions,
        customer,
    )
    change_cost = _customer_removal_cost_numba(
        distances,
        route_customers,
        route_offsets,
        positions,
        transfer_mask,
        preceding,
        successor,
        customer,
        cost,
    )
    # 保留 legacy typo：拿 change_cost 而不是 demand 比總剩餘容量。
    has_legacy_capacity = transfer_total_capacity_free >= change_cost
    if change_cost >= cost:
        return cost, transfer_vehicle_count, transfer_total_capacity_free, False

    transfer_mask[customer] = 1
    cost = change_cost
    if not has_legacy_capacity:
        cost += transfer_cost_once
        transfer_vehicle_count += 1
    transfer_total_capacity_free -= demand
    if not has_legacy_capacity:
        transfer_total_capacity_free += capacity
    transfer_capacities_free[fixed_route] -= demand
    return cost, transfer_vehicle_count, transfer_total_capacity_free, True


@njit(cache=True)
def _turn_transfer_customer_to_nontransfer_numba(
    distances: np.ndarray,
    demands: np.ndarray,
    transfer_cost_once: int,
    capacity: int,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    customer: int,
    cost: int,
    transfer_vehicle_count: int,
    transfer_total_capacity_free: int,
) -> tuple[int, int, int, bool]:
    if transfer_mask[customer] != 1:
        return cost, transfer_vehicle_count, transfer_total_capacity_free, False

    transfer_mask[customer] = 0
    preceding, successor = _chosen_customer_neighbors_numba(
        route_customers,
        route_offsets,
        positions,
        customer,
    )
    change_cost = _customer_insertion_cost_numba(
        distances,
        route_customers,
        route_offsets,
        positions,
        transfer_mask,
        preceding,
        successor,
        customer,
        cost,
    )
    # 固定路線剩餘容量刻意不恢復，總容量也保留舊版 stale 行為。
    transfer_total_capacity_free += int(demands[customer])
    if transfer_total_capacity_free >= capacity:
        transfer_vehicle_count -= 1
        change_cost -= transfer_cost_once
    return (
        int(change_cost),
        transfer_vehicle_count,
        transfer_total_capacity_free,
        True,
    )


@njit(cache=True)
def _turn_random_customer_to_transfer_numba(
    distances: np.ndarray,
    demands: np.ndarray,
    fixed_route_for_customer: np.ndarray,
    transfer_cost_once: int,
    capacity: int,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    transfer_capacities_free: np.ndarray,
    cost: int,
    transfer_vehicle_count: int,
    transfer_total_capacity_free: int,
    state: int,
    draw_count: int,
) -> tuple[int, int, int, int, int, bool]:
    state, draw_count, selected = _msvc_rand_mod_numba(
        state,
        draw_count,
        transfer_mask.shape[0] - 1,
    )
    customer = selected + 1
    cost, transfer_vehicle_count, transfer_total_capacity_free, changed = (
        _try_turn_customer_to_transfer_numba(
            distances,
            demands,
            fixed_route_for_customer,
            transfer_cost_once,
            capacity,
            route_customers,
            route_offsets,
            positions,
            transfer_mask,
            transfer_capacities_free,
            customer,
            cost,
            transfer_vehicle_count,
            transfer_total_capacity_free,
        )
    )
    return (
        cost,
        transfer_vehicle_count,
        transfer_total_capacity_free,
        state,
        draw_count,
        changed,
    )


@njit(cache=True)
def _turn_random_transfer_to_nontransfer_numba(
    distances: np.ndarray,
    demands: np.ndarray,
    transfer_cost_once: int,
    capacity: int,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    transfer_customers: np.ndarray,
    cost: int,
    transfer_vehicle_count: int,
    transfer_total_capacity_free: int,
    state: int,
    draw_count: int,
) -> tuple[int, int, int, int, int, bool]:
    transfer_count = 0
    for customer in range(1, transfer_mask.shape[0]):
        if transfer_mask[customer] == 1:
            transfer_customers[transfer_count] = customer
            transfer_count += 1
    if transfer_count == 0:
        return (
            cost,
            transfer_vehicle_count,
            transfer_total_capacity_free,
            state,
            draw_count,
            False,
        )
    state, draw_count, selected = _msvc_rand_mod_numba(
        state,
        draw_count,
        transfer_count,
    )
    customer = int(transfer_customers[selected])
    cost, transfer_vehicle_count, transfer_total_capacity_free, changed = (
        _turn_transfer_customer_to_nontransfer_numba(
            distances,
            demands,
            transfer_cost_once,
            capacity,
            route_customers,
            route_offsets,
            positions,
            transfer_mask,
            customer,
            cost,
            transfer_vehicle_count,
            transfer_total_capacity_free,
        )
    )
    return (
        cost,
        transfer_vehicle_count,
        transfer_total_capacity_free,
        state,
        draw_count,
        changed,
    )


@njit(cache=True)
def _reinsert_customer_best_position_numba(
    distances: np.ndarray,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    route_capacities_free: np.ndarray,
    customer: int,
    load: int,
    new_route_idx: int,
    current_cost: int,
) -> int:
    """強制 reinsertion；不可行修復不要求成本改善。"""
    preceding, successor = _chosen_customer_neighbors_numba(
        route_customers,
        route_offsets,
        positions,
        customer,
    )
    base_cost = _customer_removal_cost_numba(
        distances,
        route_customers,
        route_offsets,
        positions,
        transfer_mask,
        preceding,
        successor,
        customer,
        current_cost,
    )
    _remove_customer_numba(
        route_customers,
        route_offsets,
        positions,
        transfer_mask,
        route_capacities_free,
        customer,
        load,
    )
    destination_length = int(
        route_offsets[new_route_idx + 1] - route_offsets[new_route_idx]
    )
    if destination_length == 0:
        _insert_customer_numba(
            route_customers,
            route_offsets,
            positions,
            transfer_mask,
            route_capacities_free,
            customer,
            load,
            0,
            new_route_idx,
        )
        return int(
            base_cost + distances[0, customer] + distances[customer, 0]
        )

    new_cost, new_position = _best_insertion_in_route_numba(
        distances,
        route_customers,
        route_offsets,
        positions,
        transfer_mask,
        customer,
        new_route_idx,
        base_cost,
    )
    _insert_customer_numba(
        route_customers,
        route_offsets,
        positions,
        transfer_mask,
        route_capacities_free,
        customer,
        load,
        new_position,
        new_route_idx,
    )
    return int(new_cost)


@njit(cache=True)
def _drop_one_point_infeasible_numba(
    distances: np.ndarray,
    demands: np.ndarray,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    route_capacities_free: np.ndarray,
    cost: int,
    state: int,
    draw_count: int,
) -> tuple[int, bool, int, int, int]:
    """Numba 版隨機不可行修復；最後一欄是舊函式回傳值。"""
    vehicle_count = route_offsets.shape[0] - 1
    route_highest_load = 0
    highest_free_capacity = 0
    for route_idx in range(vehicle_count):
        if route_capacities_free[route_idx] > highest_free_capacity:
            highest_free_capacity = int(route_capacities_free[route_idx])
            route_highest_load = route_idx

    infeasible = True
    while infeasible:
        while True:
            state, draw_count, route_invalid = _msvc_rand_mod_numba(
                state,
                draw_count,
                vehicle_count,
            )
            if route_capacities_free[route_invalid] < 0:
                break

        route_start = int(route_offsets[route_invalid])
        route_end = int(route_offsets[route_invalid + 1] - route_start)
        retry_count = 0
        retry_max = route_end + route_end // 2
        while True:
            if retry_count == retry_max:
                return cost, False, state, draw_count, -1
            state, draw_count, customer_position = _msvc_rand_mod_numba(
                state,
                draw_count,
                route_end,
            )
            customer = int(route_customers[route_start + customer_position])
            load = (
                int(demands[customer])
                if transfer_mask[customer] == 0
                else 0
            )
            retry_count += 1
            if highest_free_capacity >= load:
                break

        while True:
            state, draw_count, route_chosen = _msvc_rand_mod_numba(
                state,
                draw_count,
                vehicle_count,
            )
            if route_capacities_free[route_chosen] >= load:
                break

        cost = _reinsert_customer_best_position_numba(
            distances,
            route_customers,
            route_offsets,
            positions,
            transfer_mask,
            route_capacities_free,
            customer,
            load,
            route_chosen,
            cost,
        )

        if route_chosen == route_highest_load:
            highest_free_capacity -= load
            for route_idx in range(vehicle_count):
                if highest_free_capacity < route_capacities_free[route_idx]:
                    highest_free_capacity = int(route_capacities_free[route_idx])
                    route_highest_load = route_idx

        if route_capacities_free[route_invalid] >= 0:
            infeasible = False
            for route_idx in range(vehicle_count):
                if route_capacities_free[route_idx] < 0:
                    infeasible = True
                    break

    cost -= LEGACY_INFEASIBILITY_PENALTY
    return int(cost), True, state, draw_count, int(cost)


@njit(cache=True)
def _local_search_numba(
    distances: np.ndarray,
    demands: np.ndarray,
    fixed_route_for_customer: np.ndarray,
    fixed_route_capacities: np.ndarray,
    capacity: int,
    transfer_cost_once: int,
    route_customers: np.ndarray,
    route_offsets: np.ndarray,
    positions: np.ndarray,
    transfer_mask: np.ndarray,
    route_capacities_free: np.ndarray,
    transfer_capacities_free: np.ndarray,
    possible_routes: np.ndarray,
    transfer_customers: np.ndarray,
    cost: int,
    feasible: bool,
    transfer_vehicle_count: int,
    transfer_total_capacity_free: int,
    state: int,
    draw_count: int,
) -> tuple[int, bool, int, int, int, int]:
    """完整 local search；SA 不在本 kernel 中。"""
    no_improvement_count = 0
    original_cost = int(cost)

    while True:
        (
            cost,
            transfer_vehicle_count,
            transfer_total_capacity_free,
            state,
            draw_count,
            _,
        ) = _turn_random_customer_to_transfer_numba(
            distances,
            demands,
            fixed_route_for_customer,
            transfer_cost_once,
            capacity,
            route_customers,
            route_offsets,
            positions,
            transfer_mask,
            transfer_capacities_free,
            cost,
            transfer_vehicle_count,
            transfer_total_capacity_free,
            state,
            draw_count,
        )
        cost, feasible = _two_swap_numba(
            distances,
            demands,
            route_customers,
            route_offsets,
            positions,
            transfer_mask,
            route_capacities_free,
            cost,
            feasible,
        )

        if original_cost > cost:
            original_cost = int(cost)
            no_improvement_count = 0
        else:
            no_improvement_count += 1
        if no_improvement_count > 1:
            break

        cost, feasible = _strong_drop_numba(
            distances,
            demands,
            route_customers,
            route_offsets,
            positions,
            transfer_mask,
            route_capacities_free,
            possible_routes,
            cost,
            feasible,
        )
        if original_cost > cost:
            original_cost = int(cost)
            no_improvement_count = 0
        else:
            no_improvement_count += 1

        if not feasible:
            cost, feasible, state, draw_count, _ = (
                _drop_one_point_infeasible_numba(
                    distances,
                    demands,
                    route_customers,
                    route_offsets,
                    positions,
                    transfer_mask,
                    route_capacities_free,
                    cost,
                    state,
                    draw_count,
                )
            )
            if feasible:
                no_improvement_count = 0
            else:
                (
                    cost,
                    transfer_vehicle_count,
                    transfer_total_capacity_free,
                    state,
                    draw_count,
                    _,
                ) = _turn_random_transfer_to_nontransfer_numba(
                    distances,
                    demands,
                    transfer_cost_once,
                    capacity,
                    route_customers,
                    route_offsets,
                    positions,
                    transfer_mask,
                    transfer_customers,
                    cost,
                    transfer_vehicle_count,
                    transfer_total_capacity_free,
                    state,
                    draw_count,
                )

                (
                    _,
                    transferred_demand,
                    transfer_vehicle_count,
                    cost,
                    feasible,
                    _,
                ) = _reevaluate_workspace_numba(
                    route_customers,
                    route_offsets,
                    transfer_mask,
                    demands,
                    distances,
                    fixed_route_for_customer,
                    fixed_route_capacities,
                    capacity,
                    transfer_cost_once,
                    route_capacities_free,
                    transfer_capacities_free,
                )
                transfer_total_capacity_free = (
                    transfer_vehicle_count * capacity - transferred_demand
                )

        if no_improvement_count >= 2:
            break

    return (
        int(cost),
        feasible,
        int(transfer_vehicle_count),
        int(transfer_total_capacity_free),
        state,
        draw_count,
    )


@njit(cache=True)
def _select_mutation_indices_numba(
    population_size: int,
    target_index: int,
    state: int,
    draw_count: int,
) -> tuple[int, int, int, int, int]:
    """完全保留 r1/r2/r3 的初抽與逐一重抽順序。"""
    state, draw_count, r1 = _msvc_rand_mod_numba(
        state,
        draw_count,
        population_size,
    )
    state, draw_count, r2 = _msvc_rand_mod_numba(
        state,
        draw_count,
        population_size,
    )
    state, draw_count, r3 = _msvc_rand_mod_numba(
        state,
        draw_count,
        population_size,
    )
    while r2 == target_index:
        state, draw_count, r2 = _msvc_rand_mod_numba(
            state,
            draw_count,
            population_size,
        )
    while r3 == target_index or r3 == r2:
        state, draw_count, r3 = _msvc_rand_mod_numba(
            state,
            draw_count,
            population_size,
        )
    while r1 == target_index or r1 == r2 or r1 == r3:
        state, draw_count, r1 = _msvc_rand_mod_numba(
            state,
            draw_count,
            population_size,
        )
    return r1, r2, r3, state, draw_count


@njit(cache=True)
def _generate_new_mutant_numba(
    x1_route_customers: np.ndarray,
    x1_route_offsets: np.ndarray,
    x1_positions: np.ndarray,
    x1_transfer_mask: np.ndarray,
    x3_positions: np.ndarray,
    mutant_route_customers: np.ndarray,
    mutant_route_offsets: np.ndarray,
    mutant_positions: np.ndarray,
    mutant_route_capacities: np.ndarray,
    customers_possible: np.ndarray,
    perturbed_components_max: int,
    state: int,
    draw_count: int,
) -> tuple[int, int]:
    """建立 rand/1 mutant；x2 在 legacy 流程中抽出但完全不使用。"""
    for index in range(x1_route_customers.shape[0]):
        mutant_route_customers[index] = x1_route_customers[index]
    for index in range(x1_route_offsets.shape[0]):
        mutant_route_offsets[index] = x1_route_offsets[index]
    for axis in range(2):
        for customer in range(x1_positions.shape[1]):
            mutant_positions[axis, customer] = x1_positions[axis, customer]
    for customer in range(customers_possible.shape[0]):
        customers_possible[customer] = customer

    customers_possible_num = customers_possible.shape[0] - 1
    perturbed_components = 0
    while True:
        state, draw_count, selected = _msvc_rand_mod_numba(
            state,
            draw_count,
            customers_possible_num,
        )
        random_index = selected + 1
        customer_chosen = int(customers_possible[random_index])
        mutant_route = int(x3_positions[0, customer_chosen])
        mutant_position = int(x3_positions[1, customer_chosen])
        mutant_route_length = int(
            mutant_route_offsets[mutant_route + 1]
            - mutant_route_offsets[mutant_route]
        )

        if mutant_route_length < mutant_position + 1:
            _remove_customer_numba(
                mutant_route_customers,
                mutant_route_offsets,
                mutant_positions,
                x1_transfer_mask,
                mutant_route_capacities,
                customer_chosen,
                0,
            )
            new_index = int(
                mutant_route_offsets[mutant_route + 1]
                - mutant_route_offsets[mutant_route]
            )
            _insert_customer_numba(
                mutant_route_customers,
                mutant_route_offsets,
                mutant_positions,
                x1_transfer_mask,
                mutant_route_capacities,
                customer_chosen,
                0,
                new_index,
                mutant_route,
            )
        else:
            customer_target = int(
                mutant_route_customers[
                    int(mutant_route_offsets[mutant_route]) + mutant_position
                ]
            )
            _swap_customers_numba(
                mutant_route_customers,
                mutant_route_offsets,
                mutant_positions,
                x1_transfer_mask,
                mutant_route_capacities,
                customer_chosen,
                0,
                customer_target,
                0,
            )

        # 保留 legacy off-by-one：最後一格不往前搬。
        while random_index < customers_possible_num - 1:
            customers_possible[random_index] = customers_possible[random_index + 1]
            random_index += 1
        customers_possible_num -= 1
        perturbed_components += 1
        if perturbed_components >= perturbed_components_max:
            break
    return state, draw_count


@njit(cache=True)
def _apply_crossover_component_numba(
    trial_route_customers: np.ndarray,
    trial_route_offsets: np.ndarray,
    trial_positions: np.ndarray,
    transfer_mask: np.ndarray,
    trial_route_capacities: np.ndarray,
    customer_chosen: int,
    route_index: int,
    component_index: int,
    customers_closed: np.ndarray,
) -> None:
    route_length = int(
        trial_route_offsets[route_index + 1]
        - trial_route_offsets[route_index]
    )
    if component_index >= route_length:
        _remove_customer_numba(
            trial_route_customers,
            trial_route_offsets,
            trial_positions,
            transfer_mask,
            trial_route_capacities,
            customer_chosen,
            0,
        )
        new_index = int(
            trial_route_offsets[route_index + 1]
            - trial_route_offsets[route_index]
        )
        _insert_customer_numba(
            trial_route_customers,
            trial_route_offsets,
            trial_positions,
            transfer_mask,
            trial_route_capacities,
            customer_chosen,
            0,
            new_index,
            route_index,
        )
        customers_closed[customer_chosen] = 1
        return

    customer_target = int(
        trial_route_customers[
            int(trial_route_offsets[route_index]) + component_index
        ]
    )
    if customer_chosen == customer_target:
        customers_closed[customer_chosen] = 1
        return
    _swap_customers_numba(
        trial_route_customers,
        trial_route_offsets,
        trial_positions,
        transfer_mask,
        trial_route_capacities,
        customer_chosen,
        0,
        customer_target,
        0,
    )
    customers_closed[customer_chosen] = 1
    customers_closed[customer_target] = 1


@njit(cache=True)
def _crossover_numba(
    target_route_customers: np.ndarray,
    target_route_offsets: np.ndarray,
    target_positions: np.ndarray,
    target_transfer_mask: np.ndarray,
    mutant_route_customers: np.ndarray,
    mutant_route_offsets: np.ndarray,
    trial_route_customers: np.ndarray,
    trial_route_offsets: np.ndarray,
    trial_positions: np.ndarray,
    trial_route_capacities: np.ndarray,
    customers_closed: np.ndarray,
    crossover_rate: float,
    state: int,
    draw_count: int,
) -> tuple[int, int]:
    """Numba 版 exponential crossover，包含強制第一個 component。"""
    for index in range(target_route_customers.shape[0]):
        trial_route_customers[index] = target_route_customers[index]
    for index in range(target_route_offsets.shape[0]):
        trial_route_offsets[index] = target_route_offsets[index]
    for axis in range(2):
        for customer in range(target_positions.shape[1]):
            trial_positions[axis, customer] = target_positions[axis, customer]
            if axis == 0:
                customers_closed[customer] = 0
    customers_closed[0] = 1

    vehicle_count = mutant_route_offsets.shape[0] - 1
    state, draw_count, route_index = _msvc_rand_mod_numba(
        state,
        draw_count,
        vehicle_count,
    )
    while (
        mutant_route_offsets[route_index + 1]
        - mutant_route_offsets[route_index]
        == 0
    ):
        route_index = route_index + 1 if route_index < vehicle_count - 1 else 0
    mutant_route_length = int(
        mutant_route_offsets[route_index + 1]
        - mutant_route_offsets[route_index]
    )
    state, draw_count, component_index = _msvc_rand_mod_numba(
        state,
        draw_count,
        mutant_route_length,
    )
    customer_chosen = int(
        mutant_route_customers[
            int(mutant_route_offsets[route_index]) + component_index
        ]
    )
    _apply_crossover_component_numba(
        trial_route_customers,
        trial_route_offsets,
        trial_positions,
        target_transfer_mask,
        trial_route_capacities,
        customer_chosen,
        route_index,
        component_index,
        customers_closed,
    )

    for current_route in range(vehicle_count):
        start = int(mutant_route_offsets[current_route])
        end = int(mutant_route_offsets[current_route + 1])
        for flat_index in range(start, end):
            current_component = flat_index - start
            customer_chosen = int(mutant_route_customers[flat_index])
            state, draw_count, raw_random = _msvc_rand_numba(
                state,
                draw_count,
            )
            random_value = raw_random / 32767.0
            if random_value <= crossover_rate:
                if customers_closed[customer_chosen] == 0:
                    _apply_crossover_component_numba(
                        trial_route_customers,
                        trial_route_offsets,
                        trial_positions,
                        target_transfer_mask,
                        trial_route_capacities,
                        customer_chosen,
                        current_route,
                        current_component,
                        customers_closed,
                    )
            else:
                return state, draw_count
    return state, draw_count


@njit(cache=True)
def _accept_trial_by_sa_numba(
    target_cost: int,
    trial_cost: int,
    temperature: float,
    state: int,
    draw_count: int,
) -> tuple[bool, int, int, float]:
    """重現 legacy SA：固定先抽 RNG，並保留第一次未使用的 exp。"""
    state, draw_count, raw_random = _msvc_rand_numba(state, draw_count)
    random_value = raw_random / 32767.0
    numerator = target_cost - trial_cost
    if temperature == 0.0:
        if numerator > 0:
            exponent = math.inf
        elif numerator < 0:
            exponent = -math.inf
        else:
            exponent = math.nan
    else:
        exponent = numerator / temperature
    unused_delta_exp = math.exp(exponent)
    accepted = trial_cost < target_cost
    if not accepted:
        accepted = math.exp(exponent) > random_value
    return accepted, state, draw_count, unused_delta_exp


@njit(cache=True)
def _select_workspace_trial_by_sa_numba(
    target_cost: int,
    target_feasible: bool,
    target_is_best: bool,
    trial_cost: int,
    trial_feasible: bool,
    best_cost: int,
    temperature: float,
    state: int,
    draw_count: int,
) -> tuple[int, int, int, int, int, float]:
    """回傳 selection 與 elite 動作，不接觸 Python Individual。

    selection: 0 保留 target、1 採用 trial。
    best_action: 0 不變、1 best 指向 trial、2 複製舊 target 到 elite buffer。
    """
    accepted, state, draw_count, unused_delta_exp = (
        _accept_trial_by_sa_numba(
            target_cost,
            trial_cost,
            temperature,
            state,
            draw_count,
        )
    )
    if accepted:
        if trial_feasible:
            best_action = 0
            if trial_cost < best_cost:
                best_action = 1
            elif target_is_best:
                best_action = 2
            return 1, best_action, 1, state, draw_count, unused_delta_exp
        if target_is_best:
            return 0, 0, 1, state, draw_count, unused_delta_exp
        return 1, 0, 0, state, draw_count, unused_delta_exp
    return (
        0,
        0,
        1 if target_feasible else 0,
        state,
        draw_count,
        unused_delta_exp,
    )


class CDELS2Numba(CDELS2):
    """保留 CDELS 2 Workspace contract 的逐步 Numba 版。"""

    def __init__(self, problem: SCVRPProblem, *, seed: int) -> None:
        super().__init__(problem, seed=seed)
        max_int64 = int(np.iinfo(np.int64).max)
        maximum_distance = max(
            int(value) for value in problem.distance_matrix.flat
        )
        total_demand = sum(int(value) for value in problem.demands)
        maximum_route_cost = maximum_distance * (
            problem.n_customers - 1 + problem.vehicle_count
        )
        maximum_transfer_vehicles = (
            (total_demand + problem.capacity - 1) // problem.capacity
            if total_demand
            else 0
        )
        maximum_search_score = (
            maximum_route_cost
            + maximum_transfer_vehicles * problem.transfer_cost_once
            + LEGACY_INFEASIBILITY_PENALTY
        )
        if (
            problem.capacity > max_int64
            or total_demand > max_int64
            or maximum_search_score > max_int64
        ):
            raise ValueError("CDELS2Numba problem arithmetic exceeds int64")

        # 下列 buffer 只在建立 solver 時配置一次。route 長度可以改變，
        # 但每個合法解永遠剛好含有 n-1 個非 depot customer。
        self._numba_route_customers = np.empty(
            problem.n_customers - 1,
            dtype=np.int64,
        )
        self._numba_route_offsets = np.empty(
            problem.vehicle_count + 1,
            dtype=np.int64,
        )
        self._numba_route_capacities = np.empty(
            problem.vehicle_count,
            dtype=np.int64,
        )
        self._numba_transfer_capacities = np.empty(
            len(problem.fixed_routes),
            dtype=np.int64,
        )
        self._numba_possible_routes = np.empty(
            problem.vehicle_count,
            dtype=np.int64,
        )
        self._numba_transfer_customers = np.empty(
            problem.n_customers,
            dtype=np.int64,
        )
        self._numba_source1_customers = np.empty(
            problem.n_customers - 1, dtype=np.int64
        )
        self._numba_source1_offsets = np.empty(
            problem.vehicle_count + 1, dtype=np.int64
        )
        self._numba_source3_customers = np.empty(
            problem.n_customers - 1, dtype=np.int64
        )
        self._numba_source3_offsets = np.empty(
            problem.vehicle_count + 1, dtype=np.int64
        )
        self._numba_mutation_customers = np.empty(
            problem.n_customers, dtype=np.int64
        )
        # 直接把既有 bytearray 暴露成 NumPy view；沒有第三份 closed buffer。
        self._numba_crossover_closed = np.frombuffer(
            self.workspace.crossover_closed,
            dtype=np.uint8,
        )

    def _pack_routes_for_numba(self, individual: CDELSIndividual) -> None:
        """將 nested routes 覆寫到固定 scratch，不建立新 NumPy array。"""
        self._pack_routes_into_numba_buffers(
            individual,
            self._numba_route_customers,
            self._numba_route_offsets,
        )

    def _pack_routes_into_numba_buffers(
        self,
        individual: CDELSIndividual,
        route_customers: np.ndarray,
        route_offsets: np.ndarray,
    ) -> None:
        """把一個來源解寫入指定的預配置 packed buffer。"""
        if len(individual.routes) != self.problem.vehicle_count:
            raise ValueError("CDELS 2 individual route count changed")
        cursor = 0
        route_offsets[0] = 0
        for route_index, route in enumerate(individual.routes):
            for customer in route:
                if cursor >= route_customers.shape[0]:
                    raise ValueError(
                        "CDELS 2 individual contains too many customers"
                    )
                route_customers[cursor] = int(customer)
                cursor += 1
            route_offsets[route_index + 1] = cursor
        if cursor != self.problem.n_customers - 1:
            raise ValueError(
                "CDELS 2 individual does not contain every customer"
            )

    def _unpack_routes_from_numba(
        self,
        individual: CDELSIndividual,
    ) -> None:
        """原地覆寫每條 route list，保留 Workspace 容器 identity。"""
        for route_index, route in enumerate(individual.routes):
            start = int(self._numba_route_offsets[route_index])
            end = int(self._numba_route_offsets[route_index + 1])
            route[:] = [
                int(value)
                for value in self._numba_route_customers[start:end]
            ]

    def _mutation(
        self,
        generation: CDELSGeneration,
        target_index: int,
    ) -> CDELSIndividual:
        """抽取來源索引後，直接覆寫固定的 Workspace mutant。"""
        r1, r2, r3, state, draws = _select_mutation_indices_numba(
            len(generation.individuals),
            int(target_index),
            int(self.rng.state),
            int(self.rng.draw_count),
        )
        self.rng._state = int(state)
        self.rng._draw_count = int(draws)
        return self._generate_new_mutant(
            generation.individuals[r1],
            generation.individuals[r2],
            generation.individuals[r3],
        )

    def _generate_new_mutant(
        self,
        x1: CDELSIndividual,
        x2: CDELSIndividual,
        x3: CDELSIndividual,
    ) -> CDELSIndividual:
        del x2
        mutant = self._copy_individual_into(self.workspace.mutant, x1)
        self._pack_routes_into_numba_buffers(
            x1, self._numba_source1_customers, self._numba_source1_offsets
        )
        self._pack_routes_into_numba_buffers(
            x3, self._numba_source3_customers, self._numba_source3_offsets
        )
        for index, value in enumerate(x1.route_capacities_free):
            self._numba_route_capacities[index] = int(value)
        state, draws = _generate_new_mutant_numba(
            self._numba_source1_customers,
            self._numba_source1_offsets,
            x1.positions,
            x1.transfer_mask,
            x3.positions,
            self._numba_route_customers,
            self._numba_route_offsets,
            mutant.positions,
            self._numba_route_capacities,
            self._numba_mutation_customers,
            int((self.problem.n_customers / 2.0) * CDELS_F),
            int(self.rng.state),
            int(self.rng.draw_count),
        )
        self._unpack_routes_from_numba(mutant)
        mutant.route_capacities_free[:] = (
            int(value) for value in self._numba_route_capacities
        )
        self.rng._state = int(state)
        self.rng._draw_count = int(draws)
        return mutant

    def _crossover(
        self,
        target: CDELSIndividual,
        mutant: CDELSIndividual,
        *,
        destination: CDELSIndividual | None = None,
    ) -> CDELSIndividual:
        trial = (
            self._make_hard_clone(target)
            if destination is None
            else self._copy_individual_into(destination, target)
        )
        self._pack_routes_into_numba_buffers(
            target, self._numba_source1_customers, self._numba_source1_offsets
        )
        self._pack_routes_into_numba_buffers(
            mutant, self._numba_source3_customers, self._numba_source3_offsets
        )
        for index, value in enumerate(target.route_capacities_free):
            self._numba_route_capacities[index] = int(value)
        state, draws = _crossover_numba(
            self._numba_source1_customers,
            self._numba_source1_offsets,
            target.positions,
            target.transfer_mask,
            self._numba_source3_customers,
            self._numba_source3_offsets,
            self._numba_route_customers,
            self._numba_route_offsets,
            trial.positions,
            self._numba_route_capacities,
            self._numba_crossover_closed,
            float(CDELS_CR),
            int(self.rng.state),
            int(self.rng.draw_count),
        )
        self._unpack_routes_from_numba(trial)
        trial.route_capacities_free[:] = (
            int(value) for value in self._numba_route_capacities
        )
        self.rng._state = int(state)
        self.rng._draw_count = int(draws)
        return trial

    def _accept_trial_by_sa(
        self,
        target_cost: int,
        trial_cost: int,
        temperature: float,
    ) -> bool:
        accepted, state, draws, _unused = _accept_trial_by_sa_numba(
            int(target_cost),
            int(trial_cost),
            float(temperature),
            int(self.rng.state),
            int(self.rng.draw_count),
        )
        self.rng._state = int(state)
        self.rng._draw_count = int(draws)
        return bool(accepted)

    def _new_generation(
        self,
        generation: CDELSGeneration,
        temperature: float,
    ) -> CDELSGeneration:
        """以編譯的 SA/selection 決策輪替既有 population buffers。"""
        workspace = self.workspace
        if workspace.active_population is not generation.individuals:
            raise ValueError(
                "CDELS generation is not the active population buffer"
            )
        if (
            len(workspace.free_population) != self.population_size
            or len(workspace.spare_population_refs) != self.population_size
        ):
            raise ValueError("CDELS population buffer size mismatch")

        individuals = workspace.free_population
        reclaimed = workspace.spare_population_refs
        old_individuals = generation.individuals
        best_solution = generation.best_solution
        feasible_solutions = 0

        for target_index, target in enumerate(old_individuals):
            trial_buffer = individuals[target_index]
            mutant = self._mutation(generation, target_index)
            trial = self._crossover(
                target,
                mutant,
                destination=trial_buffer,
            )
            self._reevaluate(trial)
            self._local_search(trial)
            self._reevaluate(trial)

            (
                selection,
                best_action,
                feasible_increment,
                state,
                draws,
                _unused,
            ) = _select_workspace_trial_by_sa_numba(
                int(target.cost),
                bool(target.feasible),
                target is best_solution,
                int(trial.cost),
                bool(trial.feasible),
                int(best_solution.cost),
                float(temperature),
                int(self.rng.state),
                int(self.rng.draw_count),
            )
            self.rng._state = int(state)
            self.rng._draw_count = int(draws)
            feasible_solutions += int(feasible_increment)

            if best_action == 1:
                best_solution = trial
            elif best_action == 2:
                best_solution = self._copy_individual_into(
                    workspace.elite,
                    target,
                )

            if selection == 1:
                individuals[target_index] = trial
                reclaimed[target_index] = target
            else:
                individuals[target_index] = target
                reclaimed[target_index] = trial

        workspace.active_population = individuals
        workspace.free_population = reclaimed
        workspace.spare_population_refs = old_individuals
        return CDELSGeneration(
            individuals=individuals,
            best_solution=best_solution,
            feasible_solutions=feasible_solutions,
            generation_id=self._take_generation_id(),
        )

    def _two_swap(self, individual: CDELSIndividual) -> None:
        """以 nopython kernel 執行 two-swap，再寫回原 Workspace。"""
        self._pack_routes_for_numba(individual)
        for route_index, capacity_free in enumerate(
            individual.route_capacities_free
        ):
            self._numba_route_capacities[route_index] = int(capacity_free)
        cost, feasible = _two_swap_numba(
            self.problem.distance_matrix,
            self.problem.demands,
            self._numba_route_customers,
            self._numba_route_offsets,
            individual.positions,
            individual.transfer_mask,
            self._numba_route_capacities,
            int(individual.cost),
            bool(individual.feasible),
        )
        self._unpack_routes_from_numba(individual)
        individual.route_capacities_free[:] = (
            int(value) for value in self._numba_route_capacities
        )
        individual.cost = int(cost)
        individual.feasible = bool(feasible)

    def _strong_drop(self, individual: CDELSIndividual) -> None:
        """以 nopython kernel 執行 reinsertion 與 strong-drop。"""
        self._pack_routes_for_numba(individual)
        for route_index, capacity_free in enumerate(
            individual.route_capacities_free
        ):
            self._numba_route_capacities[route_index] = int(capacity_free)
        cost, feasible = _strong_drop_numba(
            self.problem.distance_matrix,
            self.problem.demands,
            self._numba_route_customers,
            self._numba_route_offsets,
            individual.positions,
            individual.transfer_mask,
            self._numba_route_capacities,
            self._numba_possible_routes,
            int(individual.cost),
            bool(individual.feasible),
        )
        self._unpack_routes_from_numba(individual)
        individual.route_capacities_free[:] = (
            int(value) for value in self._numba_route_capacities
        )
        individual.cost = int(cost)
        individual.feasible = bool(feasible)

    def _turn_random_customer_to_transfer(
        self,
        individual: CDELSIndividual,
    ) -> bool:
        """使用顯式 MSVC state 在 Numba 中抽 customer 並嘗試 transfer。"""
        self._pack_routes_for_numba(individual)
        if len(individual.transfer_capacities_free) != len(
            self.problem.fixed_routes
        ):
            raise ValueError("CDELS transfer-capacity state length changed")
        for route_index, capacity_free in enumerate(
            individual.transfer_capacities_free
        ):
            self._numba_transfer_capacities[route_index] = int(capacity_free)
        (
            cost,
            transfer_vehicle_count,
            transfer_total_capacity_free,
            rng_state,
            rng_draw_count,
            changed,
        ) = _turn_random_customer_to_transfer_numba(
            self.problem.distance_matrix,
            self.problem.demands,
            self.problem.fixed_route_for_customer,
            int(self.problem.transfer_cost_once),
            int(self.problem.capacity),
            self._numba_route_customers,
            self._numba_route_offsets,
            individual.positions,
            individual.transfer_mask,
            self._numba_transfer_capacities,
            int(individual.cost),
            int(individual.transfer_vehicle_count),
            int(individual.transfer_total_capacity_free),
            int(self.rng.state),
            int(self.rng.draw_count),
        )
        for route_index in range(len(self.problem.fixed_routes)):
            individual.transfer_capacities_free[route_index] = int(
                self._numba_transfer_capacities[route_index]
            )
        individual.cost = int(cost)
        individual.transfer_vehicle_count = int(transfer_vehicle_count)
        individual.transfer_total_capacity_free = int(
            transfer_total_capacity_free
        )
        self.rng._state = int(rng_state)
        self.rng._draw_count = int(rng_draw_count)
        return bool(changed)

    def _turn_random_transfer_to_nontransfer(
        self,
        individual: CDELSIndividual,
    ) -> bool:
        """在 Numba 中依升冪 transfer customer 清單抽出一位恢復服務。"""
        self._pack_routes_for_numba(individual)
        (
            cost,
            transfer_vehicle_count,
            transfer_total_capacity_free,
            rng_state,
            rng_draw_count,
            changed,
        ) = _turn_random_transfer_to_nontransfer_numba(
            self.problem.distance_matrix,
            self.problem.demands,
            int(self.problem.transfer_cost_once),
            int(self.problem.capacity),
            self._numba_route_customers,
            self._numba_route_offsets,
            individual.positions,
            individual.transfer_mask,
            self._numba_transfer_customers,
            int(individual.cost),
            int(individual.transfer_vehicle_count),
            int(individual.transfer_total_capacity_free),
            int(self.rng.state),
            int(self.rng.draw_count),
        )
        individual.cost = int(cost)
        individual.transfer_vehicle_count = int(transfer_vehicle_count)
        individual.transfer_total_capacity_free = int(
            transfer_total_capacity_free
        )
        self.rng._state = int(rng_state)
        self.rng._draw_count = int(rng_draw_count)
        return bool(changed)

    def _drop_one_point_infeasible(
        self,
        individual: CDELSIndividual,
    ) -> int:
        """以 Numba kernel 執行帶 MSVC RNG 的不可行修復。"""
        self._pack_routes_for_numba(individual)
        if len(individual.route_capacities_free) != self.problem.vehicle_count:
            raise ValueError("CDELS route-capacity state length changed")
        for route_index, capacity_free in enumerate(
            individual.route_capacities_free
        ):
            self._numba_route_capacities[route_index] = int(capacity_free)
        cost, feasible, rng_state, rng_draw_count, result = (
            _drop_one_point_infeasible_numba(
                self.problem.distance_matrix,
                self.problem.demands,
                self._numba_route_customers,
                self._numba_route_offsets,
                individual.positions,
                individual.transfer_mask,
                self._numba_route_capacities,
                int(individual.cost),
                int(self.rng.state),
                int(self.rng.draw_count),
            )
        )
        self._unpack_routes_from_numba(individual)
        for route_index in range(self.problem.vehicle_count):
            individual.route_capacities_free[route_index] = int(
                self._numba_route_capacities[route_index]
            )
        individual.cost = int(cost)
        individual.feasible = bool(feasible)
        self.rng._state = int(rng_state)
        self.rng._draw_count = int(rng_draw_count)
        return int(result)

    def _local_search(self, individual: CDELSIndividual) -> None:
        """在單次 nopython 呼叫內完成 transfer、swap、drop 與 repair。

        演算法狀態、RNG 與逐代 digest 必須和基準版一致；capacity list 則刻意
        保留同一個 buffer。基準版完整 reevaluate 會換掉 list，但該 Python
        容器 identity 不屬於求解狀態，保留它才能達成 Workspace 減配置目的。
        """
        self._pack_routes_for_numba(individual)
        if len(individual.route_capacities_free) != self.problem.vehicle_count:
            raise ValueError("CDELS route-capacity state length changed")
        if len(individual.transfer_capacities_free) != len(
            self.problem.fixed_routes
        ):
            raise ValueError("CDELS transfer-capacity state length changed")
        for route_index, capacity_free in enumerate(
            individual.route_capacities_free
        ):
            self._numba_route_capacities[route_index] = int(capacity_free)
        for route_index, capacity_free in enumerate(
            individual.transfer_capacities_free
        ):
            self._numba_transfer_capacities[route_index] = int(capacity_free)

        (
            cost,
            feasible,
            transfer_vehicle_count,
            transfer_total_capacity_free,
            rng_state,
            rng_draw_count,
        ) = _local_search_numba(
            self.problem.distance_matrix,
            self.problem.demands,
            self.problem.fixed_route_for_customer,
            self.problem.fixed_route_capacities,
            int(self.problem.capacity),
            int(self.problem.transfer_cost_once),
            self._numba_route_customers,
            self._numba_route_offsets,
            individual.positions,
            individual.transfer_mask,
            self._numba_route_capacities,
            self._numba_transfer_capacities,
            self._numba_possible_routes,
            self._numba_transfer_customers,
            int(individual.cost),
            bool(individual.feasible),
            int(individual.transfer_vehicle_count),
            int(individual.transfer_total_capacity_free),
            int(self.rng.state),
            int(self.rng.draw_count),
        )
        self._unpack_routes_from_numba(individual)
        for route_index in range(self.problem.vehicle_count):
            individual.route_capacities_free[route_index] = int(
                self._numba_route_capacities[route_index]
            )
        for route_index in range(len(self.problem.fixed_routes)):
            individual.transfer_capacities_free[route_index] = int(
                self._numba_transfer_capacities[route_index]
            )
        individual.cost = int(cost)
        individual.feasible = bool(feasible)
        individual.transfer_vehicle_count = int(transfer_vehicle_count)
        individual.transfer_total_capacity_free = int(
            transfer_total_capacity_free
        )
        # Kernel 使用顯式 MSVC state；回寫同一個 RNG 物件，外部引用不失效。
        self.rng._state = int(rng_state)
        self.rng._draw_count = int(rng_draw_count)


    def _reevaluate(
        self,
        individual: CDELSIndividual,
    ) -> SCVRPEvaluation:
        """以 Numba 重算，並原地覆寫 Workspace 中的容量 list。"""
        self._pack_routes_for_numba(individual)
        (
            route_cost,
            transferred_demand,
            transfer_vehicle_count,
            legacy_search_score,
            legacy_feasible,
            strict_feasible,
        ) = _reevaluate_workspace_numba(
            self._numba_route_customers,
            self._numba_route_offsets,
            individual.transfer_mask,
            self.problem.demands,
            self.problem.distance_matrix,
            self.problem.fixed_route_for_customer,
            self.problem.fixed_route_capacities,
            int(self.problem.capacity),
            int(self.problem.transfer_cost_once),
            self._numba_route_capacities,
            self._numba_transfer_capacities,
        )

        objective = int(
            route_cost
            + transfer_vehicle_count * self.problem.transfer_cost_once
        )
        route_capacities = tuple(
            int(value) for value in self._numba_route_capacities
        )
        transfer_capacities = tuple(
            int(value) for value in self._numba_transfer_capacities
        )
        individual.cost = int(legacy_search_score)
        individual.feasible = bool(legacy_feasible)
        individual.route_capacities_free[:] = route_capacities
        individual.transfer_capacities_free[:] = transfer_capacities
        individual.transfer_vehicle_count = int(transfer_vehicle_count)
        individual.transfer_total_capacity_free = int(
            transfer_vehicle_count * self.problem.capacity
            - transferred_demand
        )

        capacity_violations = tuple(
            f"route_capacity:{index}"
            for index, free in enumerate(route_capacities)
            if free < 0
        )
        fixed_capacity_violations = tuple(
            f"fixed_route_capacity:{index}"
            for index, free in enumerate(transfer_capacities)
            if free < 0
        )
        return SCVRPEvaluation(
            objective=objective,
            legacy_penalty=(
                0 if legacy_feasible else LEGACY_INFEASIBILITY_PENALTY
            ),
            legacy_search_score=int(legacy_search_score),
            route_cost=int(route_cost),
            transfer_cost=int(
                transfer_vehicle_count * self.problem.transfer_cost_once
            ),
            transferred_demand=int(transferred_demand),
            transfer_vehicle_count=int(transfer_vehicle_count),
            route_capacities_free=route_capacities,
            transfer_capacities_free=transfer_capacities,
            legacy_feasible=bool(legacy_feasible),
            strict_feasible=bool(strict_feasible),
            violations=capacity_violations + fixed_capacity_violations,
        )


@dataclass(frozen=True)
class CDELS2NumbaSolver(CDELS2Solver):
    """讓正式 Engine 使用保留 Workspace 的 Numba core。"""

    core_class: ClassVar[type[CDELS2]] = CDELS2Numba
    execution_backend: ClassVar[str] = "numba_workspace"
    solver_id: ClassVar[str] = "cdels_2_numba"
