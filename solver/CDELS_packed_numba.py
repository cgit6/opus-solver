"""CDELS 的整代 packed-population Numba 實驗版本。

``CDELS_numba`` 已把個別計算搬進 Numba，但每處理一個候選解仍會反覆把
Python ``Individual`` 打包成陣列、再拆回 Python 物件。本模組保留已驗證版本
不動，改用兩組固定大小的連續陣列保存整個 population：

* ``current``：本代所有候選解，產生下一代期間保持唯讀。
* ``next``：下一代的固定寫入空間。
* ``elite``：即使最佳解被 SA 從 population 換掉，仍可獨立保留舊最佳解。

路線客戶與位置使用 ``uint16``；題目索引上限因此是 65,535，涵蓋目前約
2,000 點的需求。成本、容量與所有算術仍使用 ``int64``，避免壓縮儲存型別
改變計算結果。
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import ClassVar, Literal

import numpy as np
from numba import njit

from ..problem.scvrp import SCVRPProblem
from .CDELS import (
    CDELS_CR,
    CDELS_F,
    CDELSGeneration,
    CDELSIndividual,
    CDELSProcessTrace,
    CDELSRunResult,
    CDELSSolver,
    CDELSSnapshot,
    _process_trace_sha256,
)
from .CDELS_numba import (
    CDELSNumba,
    _crossover_numba,
    _generate_new_mutant_numba,
    _local_search_numba,
    _reevaluate_packed_numba,
    _select_mutation_indices_numba,
    _select_trial_by_sa_numba,
)


_UINT16_MAX = int(np.iinfo(np.uint16).max)


@njit(cache=True)
def _copy_packed_individual_numba(
    source_route_customers: np.ndarray,
    source_route_offsets: np.ndarray,
    source_positions: np.ndarray,
    source_transfer_mask: np.ndarray,
    source_costs: np.ndarray,
    source_feasible: np.ndarray,
    source_route_capacities: np.ndarray,
    source_transfer_capacities: np.ndarray,
    source_transfer_vehicle_count: np.ndarray,
    source_transfer_total_capacity: np.ndarray,
    source_index: int,
    target_route_customers: np.ndarray,
    target_route_offsets: np.ndarray,
    target_positions: np.ndarray,
    target_transfer_mask: np.ndarray,
    target_costs: np.ndarray,
    target_feasible: np.ndarray,
    target_route_capacities: np.ndarray,
    target_transfer_capacities: np.ndarray,
    target_transfer_vehicle_count: np.ndarray,
    target_transfer_total_capacity: np.ndarray,
    target_index: int,
) -> None:
    """複製固定陣列中的一列；沒有配置新陣列或 Python 物件。"""
    for index in range(source_route_customers.shape[1]):
        target_route_customers[target_index, index] = (
            source_route_customers[source_index, index]
        )
    for index in range(source_route_offsets.shape[1]):
        target_route_offsets[target_index, index] = source_route_offsets[
            source_index, index
        ]
    for axis in range(2):
        for customer in range(source_positions.shape[2]):
            target_positions[target_index, axis, customer] = source_positions[
                source_index, axis, customer
            ]
    for customer in range(source_transfer_mask.shape[1]):
        target_transfer_mask[target_index, customer] = source_transfer_mask[
            source_index, customer
        ]
    for route_index in range(source_route_capacities.shape[1]):
        target_route_capacities[target_index, route_index] = (
            source_route_capacities[source_index, route_index]
        )
    for fixed_index in range(source_transfer_capacities.shape[1]):
        target_transfer_capacities[target_index, fixed_index] = (
            source_transfer_capacities[source_index, fixed_index]
        )
    target_costs[target_index] = source_costs[source_index]
    target_feasible[target_index] = source_feasible[source_index]
    target_transfer_vehicle_count[target_index] = (
        source_transfer_vehicle_count[source_index]
    )
    target_transfer_total_capacity[target_index] = (
        source_transfer_total_capacity[source_index]
    )


@njit(cache=True)
def _packed_generation_numba(
    current_route_customers: np.ndarray,
    current_route_offsets: np.ndarray,
    current_positions: np.ndarray,
    current_transfer_mask: np.ndarray,
    current_costs: np.ndarray,
    current_feasible: np.ndarray,
    current_route_capacities: np.ndarray,
    current_transfer_capacities: np.ndarray,
    current_transfer_vehicle_count: np.ndarray,
    current_transfer_total_capacity: np.ndarray,
    next_route_customers: np.ndarray,
    next_route_offsets: np.ndarray,
    next_positions: np.ndarray,
    next_transfer_mask: np.ndarray,
    next_costs: np.ndarray,
    next_feasible: np.ndarray,
    next_route_capacities: np.ndarray,
    next_transfer_capacities: np.ndarray,
    next_transfer_vehicle_count: np.ndarray,
    next_transfer_total_capacity: np.ndarray,
    elite_route_customers: np.ndarray,
    elite_route_offsets: np.ndarray,
    elite_positions: np.ndarray,
    elite_transfer_mask: np.ndarray,
    elite_costs: np.ndarray,
    elite_feasible: np.ndarray,
    elite_route_capacities: np.ndarray,
    elite_transfer_capacities: np.ndarray,
    elite_transfer_vehicle_count: np.ndarray,
    elite_transfer_total_capacity: np.ndarray,
    best_index: int,
    distances: np.ndarray,
    demands: np.ndarray,
    fixed_route_for_customer: np.ndarray,
    fixed_route_capacities: np.ndarray,
    capacity: int,
    transfer_cost_once: int,
    temperature: float,
    state: int,
    draw_count: int,
    mutant_route_customers: np.ndarray,
    mutant_route_offsets: np.ndarray,
    mutant_positions: np.ndarray,
    mutant_route_capacities: np.ndarray,
    customers_possible: np.ndarray,
    possible_routes: np.ndarray,
    transfer_customers: np.ndarray,
    customers_closed: np.ndarray,
    perturbed_components_max: int,
    crossover_rate: float,
) -> tuple[int, int, int, int]:
    """完成一整代，期間資料不離開 Numba 固定陣列。

    回傳 ``best_index``、可行解數、RNG state 與 RNG draw count。最佳解若已
    不在新 population 中，``best_index`` 為 -1，但完整內容仍保留在 elite。
    """
    population_size = current_costs.shape[0]
    feasible_solutions = 0
    next_best_index = best_index
    # 只有 generation 開始時 best 確實指向 current 的某列，identity 規則才生效。
    best_still_in_current = best_index >= 0
    best_cost = int(elite_costs[0])

    for target_index in range(population_size):
        # 同一 target 的 row view 只建立一次。舊寫法在 crossover、兩次
        # reevaluate 與 local search 的每個呼叫點都重新建立相同 view。
        target_route_customers = current_route_customers[target_index]
        target_route_offsets = current_route_offsets[target_index]
        target_positions = current_positions[target_index]
        target_transfer_mask = current_transfer_mask[target_index]
        trial_route_customers = next_route_customers[target_index]
        trial_route_offsets = next_route_offsets[target_index]
        trial_positions = next_positions[target_index]
        trial_transfer_mask = next_transfer_mask[target_index]
        trial_route_capacities = next_route_capacities[target_index]
        trial_transfer_capacities = next_transfer_capacities[target_index]

        r1, _, r3, state, draw_count = _select_mutation_indices_numba(
            population_size,
            target_index,
            state,
            draw_count,
        )

        # Mutation 以 r1 為底，只改 route/position/capacity；x2 是 legacy 未用值。
        for route_index in range(current_route_capacities.shape[1]):
            mutant_route_capacities[route_index] = current_route_capacities[
                r1, route_index
            ]
        state, draw_count = _generate_new_mutant_numba(
            current_route_customers[r1],
            current_route_offsets[r1],
            current_positions[r1],
            current_transfer_mask[r1],
            current_positions[r3],
            mutant_route_customers,
            mutant_route_offsets,
            mutant_positions,
            mutant_route_capacities,
            customers_possible,
            perturbed_components_max,
            state,
            draw_count,
        )

        # Trial 一開始繼承 target 的非 route 狀態。Crossover 直接寫 next 的該列。
        for customer in range(current_transfer_mask.shape[1]):
            next_transfer_mask[target_index, customer] = current_transfer_mask[
                target_index, customer
            ]
        for route_index in range(current_route_capacities.shape[1]):
            next_route_capacities[target_index, route_index] = (
                current_route_capacities[target_index, route_index]
            )
        for fixed_index in range(current_transfer_capacities.shape[1]):
            next_transfer_capacities[target_index, fixed_index] = (
                current_transfer_capacities[target_index, fixed_index]
            )
        next_costs[target_index] = current_costs[target_index]
        next_feasible[target_index] = current_feasible[target_index]
        next_transfer_vehicle_count[target_index] = (
            current_transfer_vehicle_count[target_index]
        )
        next_transfer_total_capacity[target_index] = (
            current_transfer_total_capacity[target_index]
        )

        state, draw_count = _crossover_numba(
            target_route_customers,
            target_route_offsets,
            target_positions,
            target_transfer_mask,
            mutant_route_customers,
            mutant_route_offsets,
            trial_route_customers,
            trial_route_offsets,
            trial_positions,
            trial_route_capacities,
            customers_closed,
            crossover_rate,
            state,
            draw_count,
        )

        (
            _,
            transferred_demand,
            transfer_vehicle_count,
            trial_cost,
            trial_feasible,
            _,
        ) = _reevaluate_packed_numba(
            trial_route_customers,
            trial_route_offsets,
            trial_transfer_mask,
            demands,
            distances,
            fixed_route_for_customer,
            fixed_route_capacities,
            capacity,
            transfer_cost_once,
            trial_route_capacities,
            trial_transfer_capacities,
        )
        transfer_total_capacity = (
            transfer_vehicle_count * capacity - transferred_demand
        )

        (
            trial_cost,
            trial_feasible,
            transfer_vehicle_count,
            transfer_total_capacity,
            state,
            draw_count,
        ) = _local_search_numba(
            distances,
            demands,
            fixed_route_for_customer,
            fixed_route_capacities,
            capacity,
            transfer_cost_once,
            trial_route_customers,
            trial_route_offsets,
            trial_positions,
            trial_transfer_mask,
            trial_route_capacities,
            trial_transfer_capacities,
            possible_routes,
            transfer_customers,
            trial_cost,
            trial_feasible,
            transfer_vehicle_count,
            transfer_total_capacity,
            state,
            draw_count,
        )

        # 保留 legacy 流程：local search 後必定再完整重算一次所有衍生狀態。
        (
            _,
            transferred_demand,
            transfer_vehicle_count,
            trial_cost,
            trial_feasible,
            _,
        ) = _reevaluate_packed_numba(
            trial_route_customers,
            trial_route_offsets,
            trial_transfer_mask,
            demands,
            distances,
            fixed_route_for_customer,
            fixed_route_capacities,
            capacity,
            transfer_cost_once,
            trial_route_capacities,
            trial_transfer_capacities,
        )
        next_costs[target_index] = trial_cost
        next_feasible[target_index] = 1 if trial_feasible else 0
        next_transfer_vehicle_count[target_index] = transfer_vehicle_count
        next_transfer_total_capacity[target_index] = (
            transfer_vehicle_count * capacity - transferred_demand
        )

        target_is_best = (
            best_still_in_current and target_index == best_index
        )
        (
            choose_trial,
            feasible_increment,
            update_best,
            state,
            draw_count,
            _,
        ) = _select_trial_by_sa_numba(
            int(current_costs[target_index]),
            bool(current_feasible[target_index]),
            target_is_best,
            int(next_costs[target_index]),
            bool(next_feasible[target_index]),
            best_cost,
            temperature,
            state,
            draw_count,
        )
        feasible_solutions += feasible_increment

        if update_best:
            _copy_packed_individual_numba(
                next_route_customers,
                next_route_offsets,
                next_positions,
                next_transfer_mask,
                next_costs,
                next_feasible,
                next_route_capacities,
                next_transfer_capacities,
                next_transfer_vehicle_count,
                next_transfer_total_capacity,
                target_index,
                elite_route_customers,
                elite_route_offsets,
                elite_positions,
                elite_transfer_mask,
                elite_costs,
                elite_feasible,
                elite_route_capacities,
                elite_transfer_capacities,
                elite_transfer_vehicle_count,
                elite_transfer_total_capacity,
                0,
            )
            best_cost = int(next_costs[target_index])
            next_best_index = target_index
            best_still_in_current = False
        elif target_is_best:
            # 接受較差但可行 trial 時，舊 elite 會離開 population；其內容已在
            # elite buffer。拒絕或不可行 trial 則把舊 target 留在同一索引。
            next_best_index = -1 if choose_trial else target_index
            best_still_in_current = False

        if not choose_trial:
            _copy_packed_individual_numba(
                current_route_customers,
                current_route_offsets,
                current_positions,
                current_transfer_mask,
                current_costs,
                current_feasible,
                current_route_capacities,
                current_transfer_capacities,
                current_transfer_vehicle_count,
                current_transfer_total_capacity,
                target_index,
                next_route_customers,
                next_route_offsets,
                next_positions,
                next_transfer_mask,
                next_costs,
                next_feasible,
                next_route_capacities,
                next_transfer_capacities,
                next_transfer_vehicle_count,
                next_transfer_total_capacity,
                target_index,
            )

    return next_best_index, feasible_solutions, state, draw_count


@njit(cache=True)
def _packed_generations_numba(
    current_route_customers: np.ndarray,
    current_route_offsets: np.ndarray,
    current_positions: np.ndarray,
    current_transfer_mask: np.ndarray,
    current_costs: np.ndarray,
    current_feasible: np.ndarray,
    current_route_capacities: np.ndarray,
    current_transfer_capacities: np.ndarray,
    current_transfer_vehicle_count: np.ndarray,
    current_transfer_total_capacity: np.ndarray,
    next_route_customers: np.ndarray,
    next_route_offsets: np.ndarray,
    next_positions: np.ndarray,
    next_transfer_mask: np.ndarray,
    next_costs: np.ndarray,
    next_feasible: np.ndarray,
    next_route_capacities: np.ndarray,
    next_transfer_capacities: np.ndarray,
    next_transfer_vehicle_count: np.ndarray,
    next_transfer_total_capacity: np.ndarray,
    elite_route_customers: np.ndarray,
    elite_route_offsets: np.ndarray,
    elite_positions: np.ndarray,
    elite_transfer_mask: np.ndarray,
    elite_costs: np.ndarray,
    elite_feasible: np.ndarray,
    elite_route_capacities: np.ndarray,
    elite_transfer_capacities: np.ndarray,
    elite_transfer_vehicle_count: np.ndarray,
    elite_transfer_total_capacity: np.ndarray,
    best_index: int,
    distances: np.ndarray,
    demands: np.ndarray,
    fixed_route_for_customer: np.ndarray,
    fixed_route_capacities: np.ndarray,
    capacity: int,
    transfer_cost_once: int,
    temperature: float,
    state: int,
    draw_count: int,
    mutant_route_customers: np.ndarray,
    mutant_route_offsets: np.ndarray,
    mutant_positions: np.ndarray,
    mutant_route_capacities: np.ndarray,
    customers_possible: np.ndarray,
    possible_routes: np.ndarray,
    transfer_customers: np.ndarray,
    customers_closed: np.ndarray,
    perturbed_components_max: int,
    crossover_rate: float,
    transition_count: int,
) -> tuple[int, int, int, int, bool]:
    """在同一個 Numba 呼叫內連跑多代；每代仍完全依序處理所有 target。"""
    feasible_solutions = 0
    for _ in range(transition_count):
        best_index, feasible_solutions, state, draw_count = (
            _packed_generation_numba(
                current_route_customers,
                current_route_offsets,
                current_positions,
                current_transfer_mask,
                current_costs,
                current_feasible,
                current_route_capacities,
                current_transfer_capacities,
                current_transfer_vehicle_count,
                current_transfer_total_capacity,
                next_route_customers,
                next_route_offsets,
                next_positions,
                next_transfer_mask,
                next_costs,
                next_feasible,
                next_route_capacities,
                next_transfer_capacities,
                next_transfer_vehicle_count,
                next_transfer_total_capacity,
                elite_route_customers,
                elite_route_offsets,
                elite_positions,
                elite_transfer_mask,
                elite_costs,
                elite_feasible,
                elite_route_capacities,
                elite_transfer_capacities,
                elite_transfer_vehicle_count,
                elite_transfer_total_capacity,
                best_index,
                distances,
                demands,
                fixed_route_for_customer,
                fixed_route_capacities,
                capacity,
                transfer_cost_once,
                temperature,
                state,
                draw_count,
                mutant_route_customers,
                mutant_route_offsets,
                mutant_positions,
                mutant_route_capacities,
                customers_possible,
                possible_routes,
                transfer_customers,
                customers_closed,
                perturbed_components_max,
                crossover_rate,
            )
        )
        current_route_customers, next_route_customers = (
            next_route_customers,
            current_route_customers,
        )
        current_route_offsets, next_route_offsets = (
            next_route_offsets,
            current_route_offsets,
        )
        current_positions, next_positions = next_positions, current_positions
        current_transfer_mask, next_transfer_mask = (
            next_transfer_mask,
            current_transfer_mask,
        )
        current_costs, next_costs = next_costs, current_costs
        current_feasible, next_feasible = next_feasible, current_feasible
        current_route_capacities, next_route_capacities = (
            next_route_capacities,
            current_route_capacities,
        )
        current_transfer_capacities, next_transfer_capacities = (
            next_transfer_capacities,
            current_transfer_capacities,
        )
        current_transfer_vehicle_count, next_transfer_vehicle_count = (
            next_transfer_vehicle_count,
            current_transfer_vehicle_count,
        )
        current_transfer_total_capacity, next_transfer_total_capacity = (
            next_transfer_total_capacity,
            current_transfer_total_capacity,
        )

    return (
        best_index,
        feasible_solutions,
        state,
        draw_count,
        transition_count % 2 == 0,
    )


@dataclass
class _PackedPopulation:
    """一個世代的固定連續儲存；所有第一維索引都代表同一候選解。"""

    route_customers: np.ndarray
    route_offsets: np.ndarray
    positions: np.ndarray
    transfer_mask: np.ndarray
    costs: np.ndarray
    feasible: np.ndarray
    route_capacities_free: np.ndarray
    transfer_capacities_free: np.ndarray
    transfer_vehicle_count: np.ndarray
    transfer_total_capacity_free: np.ndarray

    @classmethod
    def create(
        cls,
        *,
        population_size: int,
        customer_count: int,
        vehicle_count: int,
        fixed_route_count: int,
    ) -> _PackedPopulation:
        """一次配置整個求解期間會重複使用的 population 空間。"""
        return cls(
            route_customers=np.empty(
                (population_size, customer_count - 1),
                dtype=np.uint16,
            ),
            route_offsets=np.empty(
                (population_size, vehicle_count + 1),
                dtype=np.uint16,
            ),
            positions=np.empty(
                (population_size, 2, customer_count),
                dtype=np.uint16,
            ),
            transfer_mask=np.empty(
                (population_size, customer_count),
                dtype=np.uint8,
            ),
            costs=np.empty(population_size, dtype=np.int64),
            feasible=np.empty(population_size, dtype=np.uint8),
            route_capacities_free=np.empty(
                (population_size, vehicle_count),
                dtype=np.int64,
            ),
            transfer_capacities_free=np.empty(
                (population_size, fixed_route_count),
                dtype=np.int64,
            ),
            transfer_vehicle_count=np.empty(
                population_size,
                dtype=np.int64,
            ),
            transfer_total_capacity_free=np.empty(
                population_size,
                dtype=np.int64,
            ),
        )

    @property
    def population_size(self) -> int:
        return int(self.costs.shape[0])

    @property
    def owned_nbytes(self) -> int:
        """回報這組陣列本身持有的 bytes，供空間測試使用。"""
        return sum(
            int(array.nbytes)
            for array in (
                self.route_customers,
                self.route_offsets,
                self.positions,
                self.transfer_mask,
                self.costs,
                self.feasible,
                self.route_capacities_free,
                self.transfer_capacities_free,
                self.transfer_vehicle_count,
                self.transfer_total_capacity_free,
            )
        )


class CDELSPackedNumba(CDELSNumba):
    """以固定連續陣列保存完整 population 的 CDELS Numba 核心。"""

    def __init__(self, problem: SCVRPProblem, *, seed: int) -> None:
        super().__init__(problem, seed=seed)
        if (
            problem.n_customers > _UINT16_MAX
            or problem.vehicle_count > _UINT16_MAX
        ):
            raise ValueError(
                "CDELSPackedNumba uint16 indices support at most 65535 "
                "customers and routes"
            )

        fixed_route_count = len(problem.fixed_routes)
        population_shape = dict(
            population_size=self.population_size,
            customer_count=problem.n_customers,
            vehicle_count=problem.vehicle_count,
            fixed_route_count=fixed_route_count,
        )
        # 兩組 population 只配置一次；每代結束時交換 Python 引用，不複製整代。
        self._packed_current = _PackedPopulation.create(**population_shape)
        self._packed_next = _PackedPopulation.create(**population_shape)
        # Elite 只有一列，負責保存可能已不在 population 裡的歷史最佳解。
        self._packed_elite = _PackedPopulation.create(
            population_size=1,
            customer_count=problem.n_customers,
            vehicle_count=problem.vehicle_count,
            fixed_route_count=fixed_route_count,
        )
        self._packed_best_index = -1
        self._packed_feasible_solutions = 0
        self._packed_generation_id = 0

        # 下列 scratch 也只配置一次。每個 target 依序覆寫，不會隨迭代累積。
        self._mutant_route_customers = np.empty(
            problem.n_customers - 1,
            dtype=np.uint16,
        )
        self._mutant_route_offsets = np.empty(
            problem.vehicle_count + 1,
            dtype=np.uint16,
        )
        self._mutant_positions = np.empty(
            (2, problem.n_customers),
            dtype=np.uint16,
        )
        self._mutant_route_capacities = np.empty(
            problem.vehicle_count,
            dtype=np.int64,
        )
        self._customers_possible = np.empty(
            problem.n_customers,
            dtype=np.uint16,
        )
        self._possible_routes = np.empty(
            problem.vehicle_count,
            dtype=np.uint16,
        )
        self._transfer_customers = np.empty(
            problem.n_customers,
            dtype=np.uint16,
        )
        self._customers_closed = np.empty(
            problem.n_customers,
            dtype=np.uint8,
        )

    @property
    def packed_population_nbytes(self) -> int:
        """current、next 與 elite 的固定持有空間，不含共用題目資料。"""
        return (
            self._packed_current.owned_nbytes
            + self._packed_next.owned_nbytes
            + self._packed_elite.owned_nbytes
        )

    def solve(
        self,
        *,
        termination_mode: Literal[
            "fixed_iterations",
            "legacy_temperature_stagnation",
        ],
        limit: int,
        start_temperature: float = 1.0,
        cooling_rate: float = 0.95,
        iterations_per_temperature: int = 110,
        max_transitions: int = 500_000,
        trace: bool = False,
        process_trace: bool = False,
    ) -> CDELSRunResult:
        """執行 CDELS；無 trace 時只有初始化與最終輸出會建立 Python 解物件。"""
        if termination_mode not in {
            "fixed_iterations",
            "legacy_temperature_stagnation",
        }:
            raise ValueError("unsupported termination_mode")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be an integer >= 0")
        if (
            isinstance(start_temperature, bool)
            or not isinstance(start_temperature, (int, float))
            or not math.isfinite(float(start_temperature))
            or start_temperature <= 0
        ):
            raise ValueError("start_temperature must be a finite number > 0")
        if (
            isinstance(cooling_rate, bool)
            or not isinstance(cooling_rate, (int, float))
            or not math.isfinite(float(cooling_rate))
            or not 0 < cooling_rate <= 1
        ):
            raise ValueError("cooling_rate must be a finite number in (0, 1]")
        if (
            isinstance(iterations_per_temperature, bool)
            or not isinstance(iterations_per_temperature, int)
            or iterations_per_temperature <= 0
        ):
            raise ValueError(
                "iterations_per_temperature must be an integer > 0"
            )
        if (
            isinstance(max_transitions, bool)
            or not isinstance(max_transitions, int)
            or max_transitions <= 0
        ):
            raise ValueError("max_transitions must be an integer > 0")
        if not isinstance(trace, bool):
            raise ValueError("trace must be a boolean")
        if not isinstance(process_trace, bool):
            raise ValueError("process_trace must be a boolean")
        if termination_mode == "fixed_iterations" and limit > max_transitions:
            raise ValueError(
                "fixed iteration limit cannot exceed max_transitions"
            )

        initial_generation = super().initialize_population()
        self._pack_generation(initial_generation)
        snapshots: list[CDELSSnapshot] = []
        process_snapshots: list[CDELSProcessTrace] = []
        if trace:
            snapshots.append(self.snapshot_generation(initial_generation))
        if process_trace:
            process_snapshots.append(
                self.process_trace_generation(initial_generation)
            )
        # 後續世代不再讀 Python initial population，現在即可讓它被回收。
        del initial_generation

        transitions = 0
        temperature_stagnation = 0
        last_progress_cost = int(self._packed_elite.costs[0])
        temperature = float(start_temperature)
        safety_limit_reached = False

        while True:
            iterations_this_level = iterations_per_temperature
            if termination_mode == "fixed_iterations":
                remaining = limit - transitions
                if remaining <= 0:
                    break
                iterations_this_level = min(iterations_this_level, remaining)
            elif transitions + iterations_this_level > max_transitions:
                iterations_this_level = max_transitions - transitions

            if not trace and not process_trace:
                # 沒有逐代觀測需求時，同一溫度區段只跨一次 Numba 邊界。
                self._advance_packed_generations(
                    temperature,
                    iterations_this_level,
                )
                transitions += iterations_this_level
                fixed_target_reached = (
                    termination_mode == "fixed_iterations"
                    and transitions >= limit
                )
                if transitions >= max_transitions and not fixed_target_reached:
                    safety_limit_reached = True
            else:
                for _ in range(iterations_this_level):
                    self._advance_packed_generation(temperature)
                    transitions += 1
                    observable_generation = self._unpack_generation()
                    if trace:
                        snapshots.append(
                            self.snapshot_generation(observable_generation)
                        )
                    if process_trace:
                        process_snapshots.append(
                            self.process_trace_generation(
                                observable_generation
                            )
                        )

                    fixed_target_reached = (
                        termination_mode == "fixed_iterations"
                        and transitions >= limit
                    )
                    if (
                        transitions >= max_transitions
                        and not fixed_target_reached
                    ):
                        safety_limit_reached = True
                        break

            if (
                not safety_limit_reached
                and iterations_this_level == iterations_per_temperature
            ):
                temperature *= float(cooling_rate)
                best_cost = int(self._packed_elite.costs[0])
                if last_progress_cost <= best_cost:
                    temperature_stagnation += 1
                else:
                    last_progress_cost = best_cost
                    temperature_stagnation = 0

            if safety_limit_reached:
                break
            if termination_mode == "fixed_iterations":
                if transitions >= limit:
                    break
            elif temperature_stagnation > limit:
                break

        generation = self._unpack_generation()
        result = self.snapshot_generation(generation)
        process_trace_sha256 = (
            _process_trace_sha256(process_snapshots)
            if process_trace
            else None
        )
        stop_cause: Literal[
            "fixed_iterations",
            "legacy_temperature_stagnation",
            "max_transitions",
        ] = "max_transitions" if safety_limit_reached else termination_mode
        return CDELSRunResult(
            termination=termination_mode,
            stop_cause=stop_cause,
            generation=generation,
            generation_count=result.generation,
            transition_count=transitions,
            temperature_stagnation=temperature_stagnation,
            final_temperature=temperature,
            rng_state=self.rng.state,
            rng_draw_count=self.rng.draw_count,
            result=result,
            trace=tuple(snapshots),
            process_trace=tuple(process_snapshots),
            process_trace_sha256=process_trace_sha256,
        )

    def _write_individual(
        self,
        packed: _PackedPopulation,
        index: int,
        individual: CDELSIndividual,
    ) -> None:
        """把一個 Python Individual 寫入既有列；不配置新的 NumPy 陣列。"""
        cursor = 0
        packed.route_offsets[index, 0] = 0
        for route_index, route in enumerate(individual.routes):
            for customer in route:
                packed.route_customers[index, cursor] = int(customer)
                cursor += 1
            packed.route_offsets[index, route_index + 1] = cursor
        if cursor != self.problem.n_customers - 1:
            raise ValueError(
                "CDELS individual does not contain every customer exactly once"
            )

        packed.positions[index] = individual.positions
        packed.transfer_mask[index] = individual.transfer_mask
        packed.costs[index] = int(individual.cost)
        packed.feasible[index] = 1 if individual.feasible else 0
        packed.route_capacities_free[index] = individual.route_capacities_free
        packed.transfer_capacities_free[index] = (
            individual.transfer_capacities_free
        )
        packed.transfer_vehicle_count[index] = int(
            individual.transfer_vehicle_count
        )
        packed.transfer_total_capacity_free[index] = int(
            individual.transfer_total_capacity_free
        )

    def _read_individual(
        self,
        packed: _PackedPopulation,
        index: int,
    ) -> CDELSIndividual:
        """只在 trace 或最終輸出時，把指定列還原成 Python Individual。"""
        routes = []
        for route_index in range(self.problem.vehicle_count):
            start = int(packed.route_offsets[index, route_index])
            end = int(packed.route_offsets[index, route_index + 1])
            routes.append(
                [
                    int(customer)
                    for customer in packed.route_customers[index, start:end]
                ]
            )
        return CDELSIndividual(
            routes=routes,
            positions=packed.positions[index].astype(np.int64),
            transfer_mask=packed.transfer_mask[index].astype(np.int64),
            cost=int(packed.costs[index]),
            feasible=bool(packed.feasible[index]),
            route_capacities_free=[
                int(value)
                for value in packed.route_capacities_free[index]
            ],
            transfer_capacities_free=[
                int(value)
                for value in packed.transfer_capacities_free[index]
            ],
            transfer_vehicle_count=int(
                packed.transfer_vehicle_count[index]
            ),
            transfer_total_capacity_free=int(
                packed.transfer_total_capacity_free[index]
            ),
        )

    def _pack_generation(self, generation: CDELSGeneration) -> None:
        """求解開始時執行一次，把 Python 初始族群搬入 current buffer。"""
        if len(generation.individuals) != self.population_size:
            raise ValueError("CDELS population size changed")
        for index, individual in enumerate(generation.individuals):
            self._write_individual(self._packed_current, index, individual)
        self._write_individual(
            self._packed_elite,
            0,
            generation.best_solution,
        )
        self._packed_best_index = generation.best_index
        self._packed_feasible_solutions = int(
            generation.feasible_solutions
        )
        self._packed_generation_id = int(generation.generation_id)

    def _unpack_generation(self) -> CDELSGeneration:
        """由 current buffer 建立可供既有 trace／輸出程式讀取的完整世代。"""
        individuals = [
            self._read_individual(self._packed_current, index)
            for index in range(self.population_size)
        ]
        if self._packed_best_index >= 0:
            best_solution = individuals[self._packed_best_index]
        else:
            best_solution = self._read_individual(self._packed_elite, 0)
        return CDELSGeneration(
            individuals=individuals,
            best_solution=best_solution,
            feasible_solutions=self._packed_feasible_solutions,
            generation_id=self._packed_generation_id,
        )

    def _advance_packed_generation(self, temperature: float) -> None:
        """呼叫一次整代 kernel，完成後只交換 current/next 的 Python 引用。"""
        current = self._packed_current
        next_population = self._packed_next
        elite = self._packed_elite
        (
            best_index,
            feasible_solutions,
            rng_state,
            rng_draw_count,
        ) = _packed_generation_numba(
            current.route_customers,
            current.route_offsets,
            current.positions,
            current.transfer_mask,
            current.costs,
            current.feasible,
            current.route_capacities_free,
            current.transfer_capacities_free,
            current.transfer_vehicle_count,
            current.transfer_total_capacity_free,
            next_population.route_customers,
            next_population.route_offsets,
            next_population.positions,
            next_population.transfer_mask,
            next_population.costs,
            next_population.feasible,
            next_population.route_capacities_free,
            next_population.transfer_capacities_free,
            next_population.transfer_vehicle_count,
            next_population.transfer_total_capacity_free,
            elite.route_customers,
            elite.route_offsets,
            elite.positions,
            elite.transfer_mask,
            elite.costs,
            elite.feasible,
            elite.route_capacities_free,
            elite.transfer_capacities_free,
            elite.transfer_vehicle_count,
            elite.transfer_total_capacity_free,
            int(self._packed_best_index),
            self.problem.distance_matrix,
            self.problem.demands,
            self.problem.fixed_route_for_customer,
            self.problem.fixed_route_capacities,
            int(self.problem.capacity),
            int(self.problem.transfer_cost_once),
            float(temperature),
            int(self.rng.state),
            int(self.rng.draw_count),
            self._mutant_route_customers,
            self._mutant_route_offsets,
            self._mutant_positions,
            self._mutant_route_capacities,
            self._customers_possible,
            self._possible_routes,
            self._transfer_customers,
            self._customers_closed,
            int((self.problem.n_customers / 2.0) * CDELS_F),
            float(CDELS_CR),
        )
        self._packed_current, self._packed_next = (
            self._packed_next,
            self._packed_current,
        )
        self._packed_best_index = int(best_index)
        self._packed_feasible_solutions = int(feasible_solutions)
        self._packed_generation_id = self._take_generation_id()
        self.rng._state = int(rng_state)
        self.rng._draw_count = int(rng_draw_count)

    def _advance_packed_generations(
        self,
        temperature: float,
        transition_count: int,
    ) -> None:
        """無 trace 快速路徑：一次跨越 Python/Numba 邊界連跑多代。"""
        if transition_count <= 0:
            raise ValueError("transition_count must be > 0")
        current = self._packed_current
        next_population = self._packed_next
        elite = self._packed_elite
        (
            best_index,
            feasible_solutions,
            rng_state,
            rng_draw_count,
            current_is_original,
        ) = _packed_generations_numba(
            current.route_customers,
            current.route_offsets,
            current.positions,
            current.transfer_mask,
            current.costs,
            current.feasible,
            current.route_capacities_free,
            current.transfer_capacities_free,
            current.transfer_vehicle_count,
            current.transfer_total_capacity_free,
            next_population.route_customers,
            next_population.route_offsets,
            next_population.positions,
            next_population.transfer_mask,
            next_population.costs,
            next_population.feasible,
            next_population.route_capacities_free,
            next_population.transfer_capacities_free,
            next_population.transfer_vehicle_count,
            next_population.transfer_total_capacity_free,
            elite.route_customers,
            elite.route_offsets,
            elite.positions,
            elite.transfer_mask,
            elite.costs,
            elite.feasible,
            elite.route_capacities_free,
            elite.transfer_capacities_free,
            elite.transfer_vehicle_count,
            elite.transfer_total_capacity_free,
            int(self._packed_best_index),
            self.problem.distance_matrix,
            self.problem.demands,
            self.problem.fixed_route_for_customer,
            self.problem.fixed_route_capacities,
            int(self.problem.capacity),
            int(self.problem.transfer_cost_once),
            float(temperature),
            int(self.rng.state),
            int(self.rng.draw_count),
            self._mutant_route_customers,
            self._mutant_route_offsets,
            self._mutant_positions,
            self._mutant_route_capacities,
            self._customers_possible,
            self._possible_routes,
            self._transfer_customers,
            self._customers_closed,
            int((self.problem.n_customers / 2.0) * CDELS_F),
            float(CDELS_CR),
            int(transition_count),
        )
        if not current_is_original:
            self._packed_current, self._packed_next = (
                self._packed_next,
                self._packed_current,
            )
        self._packed_best_index = int(best_index)
        self._packed_feasible_solutions = int(feasible_solutions)
        self._packed_generation_id += int(transition_count)
        self._next_generation_id += int(transition_count)
        self.rng._state = int(rng_state)
        self.rng._draw_count = int(rng_draw_count)


@dataclass(frozen=True)
class CDELSPackedNumbaSolver(CDELSSolver):
    """讓 Engine 使用整代 packed-population Numba 核心。"""

    core_class: ClassVar[type[CDELSPackedNumba]] = CDELSPackedNumba
    execution_backend: ClassVar[str] = "numba_packed_population"
    solver_id: ClassVar[str] = "cdels_packed_numba"
