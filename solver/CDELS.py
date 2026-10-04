"""CDELS（SCVRP + SA 版本）的單檔、純 Python 邏輯實作。

這個檔案的目的，是讓演算法可以從上到下閱讀，不必在 core、local search、
RNG 等多個檔案之間跳轉。它會完整收錄以下流程：

1. 建立初始族群。
2. Differential Evolution 的 mutation 與 exponential crossover。
3. transfer、two-swap、reinsertion、strong-drop 等 local search。
4. Simulated Annealing 接受判斷與新世代 selection。
5. 溫度更新、停止條件、結果與完整過程快照。

本檔同時提供演算法核心與 Engine adapter。正式系統只從這個檔案建立 CDELS，
不需要另外引用舊版 Python core、local-search 或 native kernel。

術語：

- target：目前族群中準備被更新的解。
- mutant：mutation 產生的中間解。
- trial：target 與 mutant crossover 後，再經 local search 的候選解。
- transfer：客戶仍保留在 route 順序中，但改由固定路線／轉移車輛服務。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
import struct
import time
from typing import Any, Callable, Literal, Sequence

import numpy as np

from ..problem.scvrp import (
    LEGACY_INFEASIBILITY_PENALTY,
    SCVRPEvaluation,
    SCVRPProblem,
    encode_scvrp_solution,
)
from ..problem.interface import Problem
from ..engine.models import SolveResult


# ============================================================
# ** CDELS 固定參數與相容性常數 **
# ============================================================

# Differential Evolution 使用的縮放係數與 crossover 機率。
CDELS_F = 0.7
CDELS_CR = 0.7

# 完整過程驗證使用的格式識別字。欄位順序不能改，否則舊、新版本即使狀態
# 相同，也會產生不同 digest。
_PROCESS_DIGEST_SCHEMA = b"SCVRP_FULL_POP_V1"
_PROCESS_TRACE_SCHEMA = b"SCVRP_FULL_TRACE_V1"

# Visual C++ 執行檔使用的舊版 rand() 參數。
_MSVC_RAND_MAX = 32_767
_UINT32_MASK = 0xFFFF_FFFF
_MSVC_MULTIPLIER = 214_013
_MSVC_INCREMENT = 2_531_011


# ============================================================
# ** 執行過程中的資料結構 **
# ============================================================

@dataclass
class CDELSIndividual:
    """一個候選解，以及 C++ Individual 中所有會影響後續流程的狀態。

    ``routes`` 永遠保留所有客戶。被 transfer 的客戶不會從 route 刪除，而是由
    ``transfer_mask`` 標記；計算一般車輛距離與載重時再跳過它。
    """

    routes: list[list[int]]
    positions: np.ndarray
    transfer_mask: np.ndarray
    cost: int = 0
    feasible: bool = False
    route_capacities_free: list[int] = field(default_factory=list)
    transfer_capacities_free: list[int] = field(default_factory=list)
    transfer_vehicle_count: int = 0
    transfer_total_capacity_free: int = 0

    def genome_dict(self) -> dict[str, object]:
        """回傳不含衍生分數的路線、位置與 transfer 狀態。"""
        return {
            "routes": [list(route) for route in self.routes],
            "positions": [
                [int(value) for value in self.positions[axis].tolist()]
                for axis in range(2)
            ],
            "transfer_mask": [
                int(value) for value in self.transfer_mask.tolist()
            ],
        }

    def canonical_dict(self) -> dict[str, object]:
        """回傳足以重建演算法中這個 individual 的完整狀態。"""
        return {
            **self.genome_dict(),
            "cost": self.cost,
            "feasible": self.feasible,
            "route_capacities_free": list(self.route_capacities_free),
            "transfer_capacities_free": list(
                self.transfer_capacities_free
            ),
            "transfer_vehicle_count": self.transfer_vehicle_count,
            "transfer_total_capacity_free": (
                self.transfer_total_capacity_free
            ),
        }


@dataclass
class CDELSGeneration:
    """一個世代的完整 population，以及跨世代保留的最佳解。"""

    individuals: list[CDELSIndividual]
    best_solution: CDELSIndividual
    feasible_solutions: int
    generation_id: int

    @property
    def best(self) -> CDELSIndividual:
        return self.best_solution

    @property
    def best_index(self) -> int:
        """最佳解在 population 中的位置；不在其中時回傳 -1。

        [相容性] SA selection 可能讓舊世代 elite 獨立保留，但它不一定出現在
        新 population 裡。這裡必須比較物件 identity，不能只比較內容。
        """
        for index, individual in enumerate(self.individuals):
            if individual is self.best_solution:
                return index
        return -1


@dataclass(frozen=True)
class CDELSTrace:
    """方便人工檢查一個世代的簡短指紋。"""

    stage: str
    generation_id: int
    population_sha256: str
    population_size: int
    best_index: int
    best_cost: int
    feasible_solutions: int
    rng_state: int
    rng_draw_count: int


@dataclass(frozen=True)
class CDELSSnapshot:
    """一個世代的最佳解快照；之後的 mutation 不會改到它。"""

    generation: int
    objective: int
    feasible_solutions: int
    feasible: bool
    transfer_vehicle_count: int
    routes: tuple[tuple[int, ...], ...]
    transferred_customers: tuple[int, ...]


@dataclass(frozen=True)
class CDELSProcessTrace:
    """一個世代的完整 population、elite 與 RNG 指紋。"""

    generation: int
    canonical_digest: str
    rng_state: int
    rng_draw_count: int


@dataclass(frozen=True)
class CDELSRunResult:
    """CDELS 主迴圈完成後回傳的所有可觀測狀態。"""

    termination: Literal[
        "fixed_iterations",
        "legacy_temperature_stagnation",
    ]
    stop_cause: Literal[
        "fixed_iterations",
        "legacy_temperature_stagnation",
        "max_transitions",
    ]
    generation: CDELSGeneration
    generation_count: int
    transition_count: int
    temperature_stagnation: int
    final_temperature: float
    rng_state: int
    rng_draw_count: int
    result: CDELSSnapshot
    trace: tuple[CDELSSnapshot, ...]
    process_trace: tuple[CDELSProcessTrace, ...]
    process_trace_sha256: str | None


# ============================================================
# ** Visual C++ 相容亂數產生器 **
# ============================================================

class MSVCRandom:
    """重現 archive 在 Visual C++ v142 使用的 15-bit ``rand()``。

    不能改用 NumPy RNG。只要亂數值或抽取次數差一次，mutation、crossover 與
    local search 後面的所有結果都會不同。
    """

    __slots__ = ("_draw_count", "_state")

    def __init__(self, seed: int = 1) -> None:
        self.srand(seed)

    @property
    def state(self) -> int:
        return self._state

    @property
    def draw_count(self) -> int:
        return self._draw_count

    def srand(self, seed: int) -> None:
        """以 unsigned 32-bit seed 重設狀態與 draw count。"""
        self._state = int(seed) & _UINT32_MASK
        self._draw_count = 0

    def rand(self) -> int:
        """抽出下一個 0..32767 的整數。"""
        self._state = (
            self._state * _MSVC_MULTIPLIER + _MSVC_INCREMENT
        ) & _UINT32_MASK
        self._draw_count += 1
        return (self._state >> 16) & _MSVC_RAND_MAX

    def rand_mod(self, modulus: int) -> int:
        """完全重現 C++ 的 ``rand() % modulus``。"""
        modulus = int(modulus)
        if modulus <= 0:
            raise ValueError("modulus must be > 0")
        return self.rand() % modulus

    def rand_unit(self) -> float:
        """完全重現 ``rand() / (double) RAND_MAX``。"""
        return self.rand() / float(_MSVC_RAND_MAX)


# ============================================================
# ** CDELS 公開介面與初始族群 **
# ============================================================

class CDELS:
    """可獨立閱讀與測試的單檔 CDELS 演算法。"""

    def __init__(self, problem: SCVRPProblem, *, seed: int) -> None:
        self.problem = problem
        # memoryview 直接共用 problem 的 NumPy buffer，不複製距離矩陣。
        # Hot loop 使用 ``view[row, column]`` 取得 Python int，可避開每次
        # NumPy chained indexing 產生暫時 row view 與 NumPy scalar。
        self._distances = memoryview(problem.distance_matrix)
        self.seed = int(seed)
        self.rng = MSVCRandom(self.seed)
        self.population_size = 3 * problem.n_customers
        self._next_generation_id = 1

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
        """執行完整 CDELS。

        每次求解都要建立新的 ``CDELS`` 物件。這個物件會保存 RNG 與下一個
        generation ID；同一物件呼叫第二次 ``solve`` 雖會重建 population，
        卻會沿用上次留下的 RNG 與 generation ID，因此不再是相同 seed 的新實驗。

        主流程只有四個階段：

        1. 建立初始族群。
        2. 反覆用 DE + local search + SA selection 產生下一代。
        3. 每完成一個完整溫度區段才降溫，並更新停滯計數。
        4. 達到停止條件後封裝最佳解與可選的逐代證據。
        """
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
            raise ValueError(
                "start_temperature must be a finite number > 0"
            )
        if (
            isinstance(cooling_rate, bool)
            or not isinstance(cooling_rate, (int, float))
            or not math.isfinite(float(cooling_rate))
            or not 0 < cooling_rate <= 1
        ):
            raise ValueError(
                "cooling_rate must be a finite number in (0, 1]"
            )
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
        if (
            termination_mode == "fixed_iterations"
            and limit > max_transitions
        ):
            raise ValueError(
                "fixed iteration limit cannot exceed max_transitions"
            )

        generation = self.initialize_population()
        snapshots: list[CDELSSnapshot] = []
        process_snapshots: list[CDELSProcessTrace] = []
        if trace:
            snapshots.append(self.snapshot_generation(generation))
        if process_trace:
            process_snapshots.append(
                self.process_trace_generation(generation)
            )

        transitions = 0
        temperature_stagnation = 0
        last_progress_cost = generation.best_solution.cost
        temperature = float(start_temperature)
        safety_limit_reached = False

        while True:
            iterations_this_level = iterations_per_temperature
            if termination_mode == "fixed_iterations":
                remaining = limit - transitions
                if remaining <= 0:
                    break
                iterations_this_level = min(
                    iterations_this_level,
                    remaining,
                )

            for _ in range(iterations_this_level):
                generation = self._new_generation(
                    generation,
                    temperature,
                )
                transitions += 1
                if trace:
                    snapshots.append(
                        self.snapshot_generation(generation)
                    )
                if process_trace:
                    process_snapshots.append(
                        self.process_trace_generation(generation)
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

            # 未跑滿一整個溫度區段時，不降溫也不增加 stagnation。
            if (
                not safety_limit_reached
                and iterations_this_level == iterations_per_temperature
            ):
                temperature *= float(cooling_rate)
                if last_progress_cost <= generation.best_solution.cost:
                    temperature_stagnation += 1
                else:
                    last_progress_cost = generation.best_solution.cost
                    temperature_stagnation = 0

            if safety_limit_reached:
                break
            if termination_mode == "fixed_iterations":
                if transitions >= limit:
                    break
            # [相容性] 舊版是嚴格大於 limit 才停，不是 >=。
            elif temperature_stagnation > limit:
                break

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

    def initialize_population(self) -> CDELSGeneration:
        """建立初始族群，並忠實套用舊版的 best-index 規則。

        1. 每個 individual 先抽一次亂數，決定由 route 0 往下或反向建立。
        2. 每次嘗試把一位尚未檢查的客戶放入當前 route。
        3. best 一開始固定指向 slot 0；後續只用成本更低的可行解取代它。

        [相容性] 若 slot 0 不可行，而且其 penalty cost 仍比後面的可行解低，
        best 可能繼續指向不可行的 slot 0。這是舊版行為，不在此偷偷修正。
        """
        individuals: list[CDELSIndividual] = []
        best_index = 0
        feasible_solutions = 0

        for population_index in range(self.population_size):
            top_to_down = self.rng.rand_mod(2) == 1
            individual = self._generate_individual(
                top_to_down=top_to_down
            )
            individuals.append(individual)

            if individual.feasible:
                feasible_solutions += 1
                if (
                    population_index > 0
                    and individual.cost < individuals[best_index].cost
                ):
                    best_index = population_index

        return CDELSGeneration(
            individuals=individuals,
            best_solution=individuals[best_index],
            feasible_solutions=feasible_solutions,
            generation_id=self._take_generation_id(),
        )

    def trace_generation(
        self,
        generation: CDELSGeneration,
        *,
        stage: str,
    ) -> CDELSTrace:
        """建立方便閱讀的 population SHA-256，不改變演算法狀態。"""
        payload = json.dumps(
            [
                individual.canonical_dict()
                for individual in generation.individuals
            ],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return CDELSTrace(
            stage=stage,
            generation_id=generation.generation_id,
            population_sha256=sha256(payload).hexdigest(),
            population_size=len(generation.individuals),
            best_index=generation.best_index,
            best_cost=generation.best.cost,
            feasible_solutions=generation.feasible_solutions,
            rng_state=self.rng.state,
            rng_draw_count=self.rng.draw_count,
        )

    def snapshot_generation(
        self,
        generation: CDELSGeneration,
    ) -> CDELSSnapshot:
        """複製本世代最佳解的輸出欄位。"""
        best = generation.best_solution
        return CDELSSnapshot(
            generation=generation.generation_id,
            objective=int(best.cost),
            feasible_solutions=int(generation.feasible_solutions),
            feasible=bool(best.feasible),
            transfer_vehicle_count=int(best.transfer_vehicle_count),
            routes=tuple(
                tuple(int(customer) for customer in route)
                for route in best.routes
            ),
            transferred_customers=tuple(
                customer
                for customer in range(1, len(best.transfer_mask))
                if int(best.transfer_mask[customer]) == 1
            ),
        )

    def process_trace_generation(
        self,
        generation: CDELSGeneration,
    ) -> CDELSProcessTrace:
        """序列化整個世代，產生可和 C++／舊 Python 比較的 digest。"""
        population_count = len(generation.individuals)
        if population_count != self.population_size:
            raise ValueError("CDELS population size changed during tracing")
        identity_matches = sum(
            individual is generation.best_solution
            for individual in generation.individuals
        )
        if identity_matches not in {0, 1}:
            raise ValueError(
                "CDELS best identity appears in multiple population slots"
            )
        best_index = generation.best_index
        if (best_index == -1) != (identity_matches == 0):
            raise ValueError("CDELS best identity/index mismatch")

        customer_count = self.problem.n_customers
        route_count = self.problem.vehicle_count
        transfer_route_count = len(self.problem.fixed_routes)
        payload = bytearray(_PROCESS_DIGEST_SCHEMA)
        payload.extend(
            struct.pack(
                "<iIIIIiiIQ",
                generation.generation_id,
                population_count,
                customer_count,
                route_count,
                transfer_route_count,
                generation.feasible_solutions,
                best_index,
                self.rng.state,
                self.rng.draw_count,
            )
        )
        for individual in generation.individuals:
            _append_process_digest_individual(
                payload,
                individual,
                customer_count=customer_count,
                route_count=route_count,
                transfer_route_count=transfer_route_count,
            )
        _append_process_digest_individual(
            payload,
            generation.best_solution,
            customer_count=customer_count,
            route_count=route_count,
            transfer_route_count=transfer_route_count,
        )
        return CDELSProcessTrace(
            generation=generation.generation_id,
            canonical_digest=sha256(payload).hexdigest(),
            rng_state=self.rng.state,
            rng_draw_count=self.rng.draw_count,
        )

    def _take_generation_id(self) -> int:
        generation_id = self._next_generation_id
        self._next_generation_id += 1
        return generation_id

    # ------------------------------------------------------------
    # Differential Evolution：mutation 與 exponential crossover
    # ------------------------------------------------------------

    def _mutation(
        self,
        generation: CDELSGeneration,
        target_index: int,
    ) -> CDELSIndividual:
        """為一個 target 選出三個不同來源，建立 mutant。

        [相容性] r1、r2、r3 的初次抽取與重抽順序不能整理成一般的
        sampling-without-replacement；每一次重抽都會消耗 RNG。
        """
        population_size = len(generation.individuals)
        r1 = self.rng.rand_mod(population_size)
        r2 = self.rng.rand_mod(population_size)
        r3 = self.rng.rand_mod(population_size)

        while r2 == target_index:
            r2 = self.rng.rand_mod(population_size)
        while r3 == target_index or r3 == r2:
            r3 = self.rng.rand_mod(population_size)
        while r1 == target_index or r1 == r2 or r1 == r3:
            r1 = self.rng.rand_mod(population_size)

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
        """以 x1 為底，將約一半 customer 的位置改成 x3 的位置。

        [相容性] C++ 雖然抽出 x2，實際上完全沒有使用它；這個無效參數仍要
        保留，因為選出 x2 的過程已消耗 RNG。
        """
        del x2
        n_customers = self.problem.n_customers
        customers_possible = list(range(n_customers))
        customers_possible_num = n_customers - 1
        mutant = self._make_hard_clone(x1)
        perturbed_components = 0
        perturbed_components_max = int(
            (n_customers / 2.0) * CDELS_F
        )

        while True:
            random_index = self.rng.rand_mod(
                customers_possible_num
            ) + 1
            customer_chosen = customers_possible[random_index]
            mutant_route = int(x3.positions[0, customer_chosen])
            mutant_position = int(x3.positions[1, customer_chosen])

            if len(mutant.routes[mutant_route]) < mutant_position + 1:
                self._remove_customer(mutant, customer_chosen, 0)
                self._insert_customer(
                    mutant,
                    customer_chosen,
                    0,
                    len(mutant.routes[mutant_route]),
                    mutant_route,
                )
            else:
                customer_target = mutant.routes[mutant_route][
                    mutant_position
                ]
                self._swap_customers(
                    mutant,
                    customer_chosen,
                    0,
                    customer_target,
                    0,
                )

            # [相容性] 這是舊程式的 off-by-one 壓縮規則，不是標準的移除。
            # 最後一格不會被往前搬；修成正常寫法會改變後續可抽到的 customer。
            while random_index < customers_possible_num - 1:
                customers_possible[random_index] = (
                    customers_possible[random_index + 1]
                )
                random_index += 1
            customers_possible_num -= 1
            perturbed_components += 1
            if perturbed_components >= perturbed_components_max:
                break

        return mutant

    def _crossover(
        self,
        target: CDELSIndividual,
        mutant: CDELSIndividual,
    ) -> CDELSIndividual:
        """依 route 順序做 DE/rand/1/exp crossover。

        先強制放入一個 mutant component，再按順序為每個 component 抽一次 RNG；
        第一個大於 CR 的值會立刻結束 crossover。
        """
        route_index = self.rng.rand_mod(self.problem.vehicle_count)
        while not mutant.routes[route_index]:
            route_index = (
                route_index + 1
                if route_index < self.problem.vehicle_count - 1
                else 0
            )
        component_index = self.rng.rand_mod(
            len(mutant.routes[route_index])
        )
        customers_closed = [False] * self.problem.n_customers
        customers_closed[0] = True
        trial = self._make_hard_clone(target)

        customer_chosen = mutant.routes[route_index][component_index]
        self._apply_crossover_component(
            trial,
            customer_chosen=customer_chosen,
            route_index=route_index,
            component_index=component_index,
            customers_closed=customers_closed,
        )

        for current_route, mutant_route in enumerate(mutant.routes):
            for current_component, customer_chosen in enumerate(
                mutant_route
            ):
                random_value = self.rng.rand_unit()
                if random_value <= CDELS_CR:
                    if not customers_closed[customer_chosen]:
                        self._apply_crossover_component(
                            trial,
                            customer_chosen=customer_chosen,
                            route_index=current_route,
                            component_index=current_component,
                            customers_closed=customers_closed,
                        )
                else:
                    return trial
        return trial

    def _apply_crossover_component(
        self,
        trial: CDELSIndividual,
        *,
        customer_chosen: int,
        route_index: int,
        component_index: int,
        customers_closed: list[bool],
    ) -> None:
        """把一個 mutant component 套到 trial；本函式不抽 RNG。"""
        if component_index >= len(trial.routes[route_index]):
            self._remove_customer(trial, customer_chosen, 0)
            self._insert_customer(
                trial,
                customer_chosen,
                0,
                len(trial.routes[route_index]),
                route_index,
            )
            customers_closed[customer_chosen] = True
            return

        customer_target = trial.routes[route_index][component_index]
        if customer_chosen == customer_target:
            customers_closed[customer_chosen] = True
            return

        self._swap_customers(
            trial,
            customer_chosen,
            0,
            customer_target,
            0,
        )
        customers_closed[customer_chosen] = True
        customers_closed[customer_target] = True

    # ------------------------------------------------------------
    # Individual 基礎編輯：只改狀態，不抽 RNG
    # ------------------------------------------------------------

    def _make_hard_clone(
        self,
        individual: CDELSIndividual,
    ) -> CDELSIndividual:
        """建立完全獨立的 mutable 副本，避免新舊世代互相改到。"""
        return CDELSIndividual(
            routes=[list(route) for route in individual.routes],
            positions=individual.positions.copy(),
            transfer_mask=individual.transfer_mask.copy(),
            cost=individual.cost,
            feasible=individual.feasible,
            route_capacities_free=list(
                individual.route_capacities_free
            ),
            transfer_capacities_free=list(
                individual.transfer_capacities_free
            ),
            transfer_vehicle_count=individual.transfer_vehicle_count,
            transfer_total_capacity_free=(
                individual.transfer_total_capacity_free
            ),
        )

    def _remove_customer(
        self,
        individual: CDELSIndividual,
        customer: int,
        load: int,
    ) -> None:
        """從 route 移除 customer，並更新其後客戶的位置。"""
        route_index = int(individual.positions[0, customer])
        position = int(individual.positions[1, customer])
        route = individual.routes[route_index]
        if int(individual.transfer_mask[customer]) == 0:
            individual.route_capacities_free[route_index] += int(load)
        route.pop(position)
        for shifted_position in range(position, len(route)):
            shifted_customer = route[shifted_position]
            individual.positions[1, shifted_customer] = shifted_position

    def _insert_customer(
        self,
        individual: CDELSIndividual,
        customer: int,
        load: int,
        new_index: int,
        new_route: int,
    ) -> None:
        """把 customer 插入指定位置，並同步 positions 與剩餘容量。"""
        route = individual.routes[new_route]
        route.insert(new_index, customer)
        for shifted_position in range(new_index + 1, len(route)):
            shifted_customer = route[shifted_position]
            individual.positions[1, shifted_customer] = shifted_position
        individual.positions[0, customer] = new_route
        individual.positions[1, customer] = new_index
        if int(individual.transfer_mask[customer]) == 0:
            individual.route_capacities_free[new_route] -= int(load)

    def _reinsert_customer_in_route(
        self,
        individual: CDELSIndividual,
        customer: int,
        new_index: int,
    ) -> None:
        """在同一條 route 內移動 customer，保留舊版 index 定義。"""
        route_index = int(individual.positions[0, customer])
        old_index = int(individual.positions[1, customer])
        if new_index == old_index:
            return
        route = individual.routes[route_index]
        insertion_index = (
            new_index if new_index < old_index else new_index - 1
        )
        route.pop(old_index)
        route.insert(insertion_index, customer)
        for position, routed_customer in enumerate(route):
            individual.positions[1, routed_customer] = position

    def _swap_customers(
        self,
        individual: CDELSIndividual,
        customer1: int,
        load1: int,
        customer2: int,
        load2: int,
    ) -> None:
        """交換兩位 customer，並更新 route、positions 與剩餘容量。"""
        route1 = int(individual.positions[0, customer1])
        position1 = int(individual.positions[1, customer1])
        route2 = int(individual.positions[0, customer2])
        position2 = int(individual.positions[1, customer2])
        effective_load1 = (
            0
            if int(individual.transfer_mask[customer1]) == 1
            else int(load1)
        )
        effective_load2 = (
            0
            if int(individual.transfer_mask[customer2]) == 1
            else int(load2)
        )

        individual.routes[route2][position2] = customer1
        individual.routes[route1][position1] = customer2
        individual.positions[0, customer2] = route1
        individual.positions[1, customer2] = position1
        individual.route_capacities_free[route1] += (
            effective_load1 - effective_load2
        )
        individual.positions[0, customer1] = route2
        individual.positions[1, customer1] = position2
        individual.route_capacities_free[route2] += (
            effective_load2 - effective_load1
        )

    # ------------------------------------------------------------
    # Local Search 對 core 狀態的操作入口
    # ------------------------------------------------------------

    def _customer_removal_cost(
        self,
        individual: CDELSIndividual,
        customer_preceding: int,
        customer_successor: int,
        customer: int,
    ) -> int:
        return _customer_removal_cost(
            self._distances,
            individual,
            customer_preceding,
            customer_successor,
            customer,
        )

    def _customer_insertion_cost(
        self,
        individual: CDELSIndividual,
        customer_preceding: int,
        customer_successor: int,
        customer: int,
    ) -> int:
        return _customer_insertion_cost(
            self._distances,
            individual,
            customer_preceding,
            customer_successor,
            customer,
        )

    def _reinsert_customer_best_position_if_improves(
        self,
        individual: CDELSIndividual,
        customer: int,
        new_route_idx: int,
    ) -> bool:
        load = (
            0
            if int(individual.transfer_mask[customer]) == 1
            else int(self.problem.demands[customer])
        )
        return _reinsert_customer_best_position_if_improves(
            self._distances,
            individual,
            customer,
            load,
            new_route_idx,
            remove_customer=self._remove_customer,
            insert_customer=self._insert_customer,
        )

    def _reinsert_customer_best_position(
        self,
        individual: CDELSIndividual,
        customer: int,
        new_route_idx: int,
    ) -> None:
        load = (
            0
            if int(individual.transfer_mask[customer]) == 1
            else int(self.problem.demands[customer])
        )
        _reinsert_customer_best_position(
            self._distances,
            individual,
            customer,
            load,
            new_route_idx,
            remove_customer=self._remove_customer,
            insert_customer=self._insert_customer,
        )

    def _turn_random_customer_to_transfer(
        self,
        individual: CDELSIndividual,
    ) -> bool:
        return _turn_random_customer_to_transfer(
            self.problem,
            self._distances,
            individual,
            self.rng,
        )

    def _turn_random_transfer_to_nontransfer(
        self,
        individual: CDELSIndividual,
    ) -> bool:
        return _turn_random_transfer_to_nontransfer(
            self.problem,
            self._distances,
            individual,
            self.rng,
        )

    def _two_swap(self, individual: CDELSIndividual) -> None:
        _two_swap(
            self.problem,
            self._distances,
            individual,
            swap_customers=self._swap_customers,
        )

    def _strong_drop(self, individual: CDELSIndividual) -> None:
        _strong_drop(
            self.problem,
            self._distances,
            individual,
            remove_customer=self._remove_customer,
            insert_customer=self._insert_customer,
        )

    def _drop_one_point_infeasible(
        self,
        individual: CDELSIndividual,
    ) -> int:
        return _drop_one_point_infeasible(
            self.problem,
            self._distances,
            individual,
            self.rng,
            remove_customer=self._remove_customer,
            insert_customer=self._insert_customer,
        )

    def _local_search(self, individual: CDELSIndividual) -> None:
        """依 archive 的固定順序執行完整 local search。"""
        _local_search(
            individual,
            turn_random_customer_to_transfer=(
                self._turn_random_customer_to_transfer
            ),
            two_swap_move=self._two_swap,
            strong_drop_move=self._strong_drop,
            drop_one_point_infeasible_move=(
                self._drop_one_point_infeasible
            ),
            turn_random_transfer_to_nontransfer=(
                self._turn_random_transfer_to_nontransfer
            ),
            reevaluate=self._reevaluate,
        )

    # ------------------------------------------------------------
    # 新世代：DE → local search → SA selection
    # ------------------------------------------------------------

    def _accept_trial_by_sa(
        self,
        target_cost: int,
        trial_cost: int,
        temperature: float,
    ) -> bool:
        """依 Simulated Annealing 決定 trial 是否取代 target。

        [相容性] 每次判斷都先抽一個亂數。C++ 先算一次 exp 存到未使用變數；
        當 trial 沒有嚴格更好時，再算第二次 exp 做比較。不可合併這兩次呼叫。

        Python 的 ``math.exp`` 仍交給作業系統的 libm，因此跨平台時，只有在
        libm 的最後幾個浮點 bit 相容時才保證邊界判斷相同。正溢位會在
        ``_cpp_exp`` 轉成 ``+inf``；溫度下溢成 0 時，``_cpp_float_divide``
        會保留 C++ 的 ``inf``／``-inf``／``nan`` 行為。
        """
        random_value = self.rng.rand_unit()
        exponent = _cpp_float_divide(
            int(target_cost) - int(trial_cost),
            float(temperature),
        )
        _unused_delta_exp = _cpp_exp(exponent)
        return (
            int(trial_cost) < int(target_cost)
            or _cpp_exp(exponent) > random_value
        )

    def _new_generation(
        self,
        generation: CDELSGeneration,
        temperature: float,
    ) -> CDELSGeneration:
        """從舊 population 依序產生並選擇一整個新世代。

        每一個 target 固定執行：

        1. mutation。
        2. exponential crossover。
        3. 完整 reevaluation。
        4. local search。
        5. 再做一次完整 reevaluation，同步刻意 stale 的欄位。
        6. SA selection；必要時保留舊 elite。
        """
        individuals: list[CDELSIndividual] = []
        best_solution = generation.best_solution
        feasible_solutions = 0

        for target_index, target in enumerate(generation.individuals):
            mutant = self._mutation(generation, target_index)
            trial = self._crossover(target, mutant)
            del mutant

            self._reevaluate(trial)
            self._local_search(trial)
            self._reevaluate(trial)

            if self._accept_trial_by_sa(
                target.cost,
                trial.cost,
                temperature,
            ):
                if trial.feasible:
                    feasible_solutions += 1
                    if trial.cost < best_solution.cost:
                        best_solution = trial
                    individuals.append(trial)
                elif target is best_solution:
                    # SA 接受不可行 trial 時，舊 elite 的 slot 仍強制保留 elite。
                    individuals.append(target)
                    feasible_solutions += 1
                else:
                    individuals.append(trial)
            else:
                # 拒絕時直接共享舊 target 物件，不能偷偷 clone。
                individuals.append(target)
                if target.feasible:
                    feasible_solutions += 1

        return CDELSGeneration(
            individuals=individuals,
            best_solution=best_solution,
            feasible_solutions=feasible_solutions,
            generation_id=self._take_generation_id(),
        )

    def _generate_individual(
        self,
        *,
        top_to_down: bool,
    ) -> CDELSIndividual:
        """用 archive 的隨機裝載規則建立一個完整 customer permutation。

        [相容性] 容量判斷使用嚴格的 ``route_load < capacity``，不是 ``<=``。
        每輪換 route 後，只重設「是否檢查過」，已經成功放入路線的客戶不會再抽。
        """
        n_customers = self.problem.n_customers
        checked = np.zeros(n_customers, dtype=np.bool_)
        routed = np.zeros(n_customers, dtype=np.bool_)
        checked[0] = True
        routed[0] = True
        routes: list[list[int]] = [
            [] for _ in range(self.problem.vehicle_count)
        ]
        checked_count = 1
        routed_count = 1
        route_order = (
            range(self.problem.vehicle_count)
            if top_to_down
            else range(self.problem.vehicle_count - 1, -1, -1)
        )
        last_route_index = 0

        for route_index in route_order:
            last_route_index = route_index
            route_load = 0

            while checked_count < n_customers:
                while True:
                    customer = self.rng.rand_mod(n_customers - 1) + 1
                    if not checked[customer]:
                        break

                load = int(self.problem.demands[customer])
                route_load += load
                if route_load < self.problem.capacity:
                    routes[route_index].append(customer)
                    routed[customer] = True
                    routed_count += 1
                else:
                    route_load -= load
                checked[customer] = True
                checked_count += 1

            checked_count = 1
            for customer in range(1, n_customers):
                if routed[customer]:
                    checked[customer] = True
                    checked_count += 1
                else:
                    checked[customer] = False

            if routed_count == n_customers:
                break

        # 理論上最後一條 route 可能仍無法容納所有人。舊版不再檢查容量，而是把
        # 剩餘客戶全部附加到最後處理的 route，再由 reevaluation 標成不可行。
        if routed_count != n_customers:
            for customer in range(1, n_customers):
                if not routed[customer]:
                    routes[last_route_index].append(customer)

        individual = CDELSIndividual(
            routes=routes,
            positions=_build_positions(
                routes,
                n_customers=n_customers,
            ),
            transfer_mask=np.zeros(n_customers, dtype=np.int64),
        )
        self._reevaluate(individual)
        return individual

    def _reevaluate(
        self,
        individual: CDELSIndividual,
    ) -> SCVRPEvaluation:
        """從 routes 與 transfer mask 完整重算 cost、容量及可行性。

        Local search 中某些欄位會刻意暫時過期；只有呼叫這個函式才會重新同步。
        """
        transferred = tuple(
            int(customer)
            for customer in np.flatnonzero(individual.transfer_mask)
        )
        evaluation = self.problem.evaluate(
            individual.routes,
            transferred,
        )
        individual.cost = evaluation.legacy_search_score
        individual.feasible = evaluation.legacy_feasible
        individual.route_capacities_free = list(
            evaluation.route_capacities_free
        )
        individual.transfer_capacities_free = list(
            evaluation.transfer_capacities_free
        )
        individual.transfer_vehicle_count = (
            evaluation.transfer_vehicle_count
        )
        individual.transfer_total_capacity_free = (
            evaluation.transfer_vehicle_count * self.problem.capacity
            - evaluation.transferred_demand
        )
        return evaluation


# ============================================================
# ** 不抽亂數的底層狀態 helper **
# ============================================================

def _build_positions(
    routes: list[list[int]],
    *,
    n_customers: int,
) -> np.ndarray:
    """建立 customer -> (route, position) 的反向索引。"""
    positions = np.zeros((2, n_customers), dtype=np.int64)
    for route_index, route in enumerate(routes):
        for position, customer in enumerate(route):
            positions[0, customer] = route_index
            positions[1, customer] = position
    return positions


# ============================================================
# ** Local Search：路線鄰居與成本差分 **
# ============================================================

def _immediate_customer_neighbors(
    route: Sequence[int],
    component: int,
) -> tuple[int, int]:
    """回傳 customer 左右相鄰的項目；route 邊界以 depot 0 表示。"""
    route_end = len(route)
    if component == route_end - 1:
        preceding = 0 if component == 0 else int(route[component - 1])
        return preceding, 0
    if component == 0:
        return 0, int(route[1])
    return int(route[component - 1]), int(route[component + 1])


def _nearest_nontransfer_neighbors(
    individual: CDELSIndividual,
    customer_preceding: int,
    customer_successor: int,
) -> tuple[int, int]:
    """沿 route 跳過 transfer customer，找到真正會形成距離邊的鄰居。"""
    if int(individual.transfer_mask[customer_successor]) != 0:
        route_index = int(
            individual.positions[0, customer_successor]
        )
        position = int(individual.positions[1, customer_successor])
        route = individual.routes[route_index]
        while (
            int(individual.transfer_mask[customer_successor]) != 0
            and customer_successor != 0
        ):
            position += 1
            customer_successor = (
                int(route[position]) if position < len(route) else 0
            )

    if int(individual.transfer_mask[customer_preceding]) != 0:
        route_index = int(
            individual.positions[0, customer_preceding]
        )
        position = int(individual.positions[1, customer_preceding])
        route = individual.routes[route_index]
        while (
            int(individual.transfer_mask[customer_preceding]) != 0
            and customer_preceding != 0
        ):
            position -= 1
            customer_preceding = (
                int(route[position]) if position >= 0 else 0
            )

    return customer_preceding, customer_successor


def _customer_removal_cost(
    distances: memoryview,
    individual: CDELSIndividual,
    customer_preceding: int,
    customer_successor: int,
    customer: int,
    *,
    cost: int | None = None,
) -> int:
    """只計算移除 customer 後的成本，不實際修改 route。"""
    base_cost = individual.cost if cost is None else int(cost)
    if int(individual.transfer_mask[customer]) != 0:
        return base_cost
    customer_preceding, customer_successor = (
        _nearest_nontransfer_neighbors(
            individual,
            customer_preceding,
            customer_successor,
        )
    )
    return int(
        base_cost
        - distances[customer_preceding, customer]
        - distances[customer, customer_successor]
        + distances[customer_preceding, customer_successor]
    )


def _customer_insertion_cost(
    distances: memoryview,
    individual: CDELSIndividual,
    customer_preceding: int,
    customer_successor: int,
    customer: int,
    *,
    cost: int | None = None,
) -> int:
    """只計算插入 customer 後的成本，不實際修改 route。"""
    base_cost = individual.cost if cost is None else int(cost)
    if int(individual.transfer_mask[customer]) != 0:
        return base_cost
    customer_preceding, customer_successor = (
        _nearest_nontransfer_neighbors(
            individual,
            customer_preceding,
            customer_successor,
        )
    )
    return int(
        base_cost
        + distances[customer_preceding, customer]
        + distances[customer, customer_successor]
        - distances[customer_preceding, customer_successor]
    )


def _swap_cost_exclusive(
    distances: memoryview,
    individual: CDELSIndividual,
    customer_preceding: int,
    customer_successor: int,
    customer_old: int,
    customer_new: int,
    *,
    cost: int = 0,
) -> int:
    """計算跨 route 交換一端 customer 的成本差。

    [相容性] C++ 把「old 是 transfer、new 不是」的條件重複寫了兩次，反方向
    的 mixed-transfer case 因而落入 no-op。這個 typo 會影響 two-swap 結果。
    """
    customer_preceding, customer_successor = (
        _nearest_nontransfer_neighbors(
            individual,
            int(customer_preceding),
            int(customer_successor),
        )
    )
    customer_old = int(customer_old)
    customer_new = int(customer_new)
    base_cost = int(cost)
    old_transfer = int(individual.transfer_mask[customer_old])
    new_transfer = int(individual.transfer_mask[customer_new])

    if old_transfer == 0 and new_transfer == 0:
        result = int(
            base_cost
            - distances[customer_preceding, customer_old]
            - distances[customer_old, customer_successor]
        )

        if not (
            int(individual.transfer_mask[customer_successor]) == 0
            and customer_successor != customer_new
        ):
            if (
                int(individual.transfer_mask[customer_successor]) == 0
                and customer_successor == customer_new
            ):
                customer_successor = customer_old
            else:
                route_index = int(
                    individual.positions[0, customer_successor]
                )
                position = int(
                    individual.positions[1, customer_successor]
                )
                route = individual.routes[route_index]
                while (
                    int(individual.transfer_mask[customer_successor])
                    != 0
                    and customer_successor != 0
                ) or customer_successor == customer_new:
                    position += 1
                    if position >= len(route):
                        customer_successor = 0
                        break
                    customer_successor = int(route[position])

        if not (
            int(individual.transfer_mask[customer_preceding]) == 0
            and customer_preceding != customer_new
        ):
            if (
                int(individual.transfer_mask[customer_preceding]) == 0
                and customer_preceding == customer_new
            ):
                customer_preceding = customer_old
            else:
                route_index = int(
                    individual.positions[0, customer_preceding]
                )
                position = int(
                    individual.positions[1, customer_preceding]
                )
                route = individual.routes[route_index]
                while (
                    int(individual.transfer_mask[customer_preceding])
                    != 0
                    and customer_preceding != 0
                ) or customer_preceding == customer_new:
                    position -= 1
                    if position < 0:
                        customer_preceding = 0
                        break
                    customer_preceding = int(route[position])

        return int(
            result
            + distances[customer_preceding, customer_new]
            + distances[customer_new, customer_successor]
        )

    if old_transfer == 1 and new_transfer == 0:
        return int(
            base_cost
            + distances[customer_preceding, customer_new]
            + distances[customer_new, customer_successor]
        )

    return base_cost


def _swap_cost_inclusive(
    distances: memoryview,
    individual: CDELSIndividual,
    i: int,
    j: int,
    customeri: int,
    icustomer_preceding: int,
    icustomer_successor: int,
    customerj: int,
    jcustomer_preceding: int,
    jcustomer_successor: int,
    *,
    cost: int | None = None,
) -> int:
    """計算同一條 route 內交換兩位 customer 後的成本。"""
    base_cost = individual.cost if cost is None else int(cost)
    customeri = int(customeri)
    customerj = int(customerj)

    if int(i) == int(j) - 1:
        if (
            int(individual.transfer_mask[customeri]) != 0
            or int(individual.transfer_mask[customerj]) != 0
        ):
            return int(base_cost)
        icustomer_preceding, jcustomer_successor = (
            _nearest_nontransfer_neighbors(
                individual,
                int(icustomer_preceding),
                int(jcustomer_successor),
            )
        )
        return int(
            base_cost
            - distances[icustomer_preceding, customeri]
            - distances[customerj, jcustomer_successor]
            + distances[customerj, icustomer_preceding]
            + distances[customeri, jcustomer_successor]
        )

    return int(
        base_cost
        + _swap_cost_exclusive(
            distances,
            individual,
            int(icustomer_preceding),
            int(icustomer_successor),
            customeri,
            customerj,
        )
        + _swap_cost_exclusive(
            distances,
            individual,
            int(jcustomer_preceding),
            int(jcustomer_successor),
            customerj,
            customeri,
        )
    )


def _chosen_customer_neighbors(
    individual: CDELSIndividual,
    customer: int,
) -> tuple[int, int]:
    route_index = int(individual.positions[0, customer])
    component = int(individual.positions[1, customer])
    return _immediate_customer_neighbors(
        individual.routes[route_index],
        component,
    )


def _best_insertion_in_route(
    distances: memoryview,
    individual: CDELSIndividual,
    customer: int,
    route: Sequence[int],
    *,
    base_cost: int,
) -> tuple[int, int]:
    """回傳 nonempty route 中成本最低的插入點；平手取最早位置。"""
    best_cost: int | None = None
    best_position = 0
    customer_preceding = 0

    for position in range(len(route) + 1):
        customer_successor = (
            int(route[position]) if position < len(route) else 0
        )
        candidate_cost = _customer_insertion_cost(
            distances,
            individual,
            customer_preceding,
            customer_successor,
            customer,
            cost=base_cost,
        )
        if best_cost is None or candidate_cost < best_cost:
            best_cost = candidate_cost
            best_position = position
        customer_preceding = customer_successor

    assert best_cost is not None
    return best_cost, best_position


def _reinsert_customer_best_position_if_improves(
    distances: memoryview,
    individual: CDELSIndividual,
    customer: int,
    load: int,
    new_route_idx: int,
    *,
    remove_customer: Callable[[CDELSIndividual, int, int], None],
    insert_customer: Callable[
        [CDELSIndividual, int, int, int, int],
        None,
    ],
) -> bool:
    """只有成本嚴格變好時，才把 customer 搬到另一條 route 的最佳位置。"""
    customer = int(customer)
    load = int(load)
    new_route_idx = int(new_route_idx)
    preceding, successor = _chosen_customer_neighbors(
        individual,
        customer,
    )
    base_cost = _customer_removal_cost(
        distances,
        individual,
        preceding,
        successor,
        customer,
    )
    destination = individual.routes[new_route_idx]

    if not destination:
        # [相容性] 空 route 直接加 depot roundtrip；即使 customer 已 transfer
        # 仍會加，不能改用一般 insertion delta。
        new_cost = int(
            base_cost + distances[0, customer] + distances[customer, 0]
        )
        if new_cost < individual.cost:
            remove_customer(individual, customer, load)
            insert_customer(individual, customer, load, 0, new_route_idx)
            individual.cost = new_cost
            return True
        return False

    new_cost, new_position = _best_insertion_in_route(
        distances,
        individual,
        customer,
        destination,
        base_cost=base_cost,
    )
    if new_cost < individual.cost:
        remove_customer(individual, customer, load)
        insert_customer(
            individual,
            customer,
            load,
            new_position,
            new_route_idx,
        )
        individual.cost = new_cost
        return True
    return False


def _reinsert_customer_best_position(
    distances: memoryview,
    individual: CDELSIndividual,
    customer: int,
    load: int,
    new_route_idx: int,
    *,
    remove_customer: Callable[[CDELSIndividual, int, int], None],
    insert_customer: Callable[
        [CDELSIndividual, int, int, int, int],
        None,
    ],
) -> None:
    """強制搬移 customer，不要求成本改善；不可行解修復會使用這條路徑。"""
    customer = int(customer)
    load = int(load)
    new_route_idx = int(new_route_idx)
    preceding, successor = _chosen_customer_neighbors(
        individual,
        customer,
    )
    base_cost = _customer_removal_cost(
        distances,
        individual,
        preceding,
        successor,
        customer,
    )

    remove_customer(individual, customer, load)
    destination = individual.routes[new_route_idx]
    if not destination:
        insert_customer(individual, customer, load, 0, new_route_idx)
        individual.cost = int(
            base_cost + distances[0, customer] + distances[customer, 0]
        )
        return

    new_cost, new_position = _best_insertion_in_route(
        distances,
        individual,
        customer,
        destination,
        base_cost=base_cost,
    )
    insert_customer(
        individual,
        customer,
        load,
        new_position,
        new_route_idx,
    )
    individual.cost = new_cost


# ============================================================
# ** Local Search：transfer、two-swap 與修復操作 **
# ============================================================

def _drop_one_point_infeasible(
    problem: SCVRPProblem,
    distances: memoryview,
    individual: CDELSIndividual,
    rng: MSVCRandom,
    *,
    remove_customer: Callable[[CDELSIndividual, int, int], None],
    insert_customer: Callable[
        [CDELSIndividual, int, int, int, int],
        None,
    ],
) -> int:
    """隨機把超載 route 的 customer 搬到仍有容量的 route。

    回傳值不是成功布林值：嘗試次數耗盡回傳 -1，成功則回傳扣掉一次不可行
    penalty 後的 cost。
    """
    vehicle_count = int(problem.vehicle_count)
    route_highest_load = 0
    highest_free_capacity = 0
    for route_idx in range(vehicle_count):
        if (
            int(individual.route_capacities_free[route_idx])
            > highest_free_capacity
        ):
            highest_free_capacity = int(
                individual.route_capacities_free[route_idx]
            )
            route_highest_load = route_idx

    infeasible = True
    while infeasible:
        # C++ do/while 至少抽一次，直到抽中負容量 route。
        while True:
            route_invalid = rng.rand_mod(vehicle_count)
            if individual.route_capacities_free[route_invalid] < 0:
                break

        route = individual.routes[route_invalid]
        route_end = len(route)
        retry_count = 0
        retry_max = route_end + route_end // 2

        while True:
            if retry_count == retry_max:
                return -1
            customer = int(route[rng.rand_mod(route_end)])
            load = (
                int(problem.demands[customer])
                if int(individual.transfer_mask[customer]) == 0
                else 0
            )
            retry_count += 1
            if highest_free_capacity >= load:
                break

        while True:
            route_chosen = rng.rand_mod(vehicle_count)
            if individual.route_capacities_free[route_chosen] >= load:
                break

        _reinsert_customer_best_position(
            distances,
            individual,
            customer,
            load,
            route_chosen,
            remove_customer=remove_customer,
            insert_customer=insert_customer,
        )

        # [相容性] 只有目的地剛好是先前記住的最大容量 route 才重新掃描。
        if route_chosen == route_highest_load:
            highest_free_capacity -= load
            for route_idx in range(vehicle_count):
                if (
                    highest_free_capacity
                    < individual.route_capacities_free[route_idx]
                ):
                    highest_free_capacity = int(
                        individual.route_capacities_free[route_idx]
                    )
                    route_highest_load = route_idx

        if individual.route_capacities_free[route_invalid] >= 0:
            infeasible = any(
                individual.route_capacities_free[route_idx] < 0
                for route_idx in range(vehicle_count)
            )

    individual.feasible = True
    individual.cost -= LEGACY_INFEASIBILITY_PENALTY
    return int(individual.cost)


def _strong_drop(
    problem: SCVRPProblem,
    distances: memoryview,
    individual: CDELSIndividual,
    *,
    remove_customer: Callable[[CDELSIndividual, int, int], None],
    insert_customer: Callable[
        [CDELSIndividual, int, int, int, int],
        None,
    ],
) -> None:
    """依 route 順序嘗試把 customer 搬到其他 route 的最佳位置。

    [相容性] customer 搬走後，下一位會往前補到目前 index；舊迴圈仍把 index
    加一，所以那一位會被跳過。這不是一般的完整鄰域掃描。
    """
    possible_routes: list[int] = []
    got_improvement = False

    for source_route_idx in range(problem.vehicle_count):
        source_route = individual.routes[source_route_idx]
        route_end = len(source_route)
        load_old = -1

        if route_end > 0:
            component = 0
            while component < route_end:
                customer = int(source_route[component])
                load = (
                    int(problem.demands[customer])
                    if int(individual.transfer_mask[customer]) == 0
                    else 0
                )

                if load > load_old or got_improvement:
                    possible_routes = [
                        route_idx
                        for route_idx in range(problem.vehicle_count)
                        if route_idx != source_route_idx
                        and load
                        <= individual.route_capacities_free[route_idx]
                    ]

                got_improvement = False
                for destination_route_idx in possible_routes:
                    improved = (
                        _reinsert_customer_best_position_if_improves(
                            distances,
                            individual,
                            customer,
                            load,
                            destination_route_idx,
                            remove_customer=remove_customer,
                            insert_customer=insert_customer,
                        )
                    )
                    if not got_improvement:
                        got_improvement = improved

                if got_improvement:
                    route_end = len(source_route)

                load_old = load
                component += 1

    if not individual.feasible and all(
        individual.route_capacities_free[route_idx] >= 0
        for route_idx in range(problem.vehicle_count)
    ):
        individual.cost -= LEGACY_INFEASIBILITY_PENALTY
        individual.feasible = True


def _two_swap(
    problem: SCVRPProblem,
    distances: memoryview,
    individual: CDELSIndividual,
    *,
    swap_customers: Callable[
        [CDELSIndividual, int, int, int, int],
        None,
    ],
) -> None:
    """以 first-improvement 規則掃描兩兩交換，成功後從目前位置重啟。"""
    original_cost = int(individual.cost)

    for routei in range(problem.vehicle_count):
        route_endi = len(individual.routes[routei])
        for i in range(route_endi):
            while True:
                route_i = individual.routes[routei]
                customeri = int(route_i[i])
                customeri_transferred = int(
                    individual.transfer_mask[customeri]
                )
                load = (
                    int(problem.demands[customeri])
                    if customeri_transferred == 0
                    else 0
                )

                # 同一輪掃描所有 j 時，i 的左右鄰居不會改變。只有接受 swap
                # 並回到 while 開頭後才重新讀取，避免每個候選都建立鄰居 tuple。
                i_pre = 0 if i == 0 else int(route_i[i - 1])
                i_next = (
                    0 if i == route_endi - 1 else int(route_i[i + 1])
                )
                improved = False

                for routej in range(routei, problem.vehicle_count):
                    route_j = individual.routes[routej]
                    route_endj = len(route_j)
                    j_start = i + 1 if routei == routej else 0
                    for j in range(j_start, route_endj):
                        customerj = int(route_j[j])

                        # [相容性] C++ typo：customer-j 的 load 也用 customer-i
                        # 的 transfer flag 決定。
                        loadj = (
                            int(problem.demands[customerj])
                            if customeri_transferred == 0
                            else 0
                        )

                        if routei != routej:
                            if (
                                individual.route_capacities_free[routei]
                                + load
                                < loadj
                                or individual.route_capacities_free[routej]
                                + loadj
                                < load
                            ):
                                continue

                            j_pre = 0 if j == 0 else int(route_j[j - 1])
                            j_next = (
                                0
                                if j == route_endj - 1
                                else int(route_j[j + 1])
                            )
                            cost_new = int(
                                original_cost
                                + _swap_cost_exclusive(
                                    distances,
                                    individual,
                                    i_pre,
                                    i_next,
                                    customeri,
                                    customerj,
                                )
                                + _swap_cost_exclusive(
                                    distances,
                                    individual,
                                    j_pre,
                                    j_next,
                                    customerj,
                                    customeri,
                                )
                            )
                        else:
                            j_pre = int(route_j[j - 1])
                            j_next = (
                                0
                                if j == route_endj - 1
                                else int(route_j[j + 1])
                            )
                            cost_new = _swap_cost_inclusive(
                                distances,
                                individual,
                                i,
                                j,
                                customeri,
                                i_pre,
                                i_next,
                                customerj,
                                j_pre,
                                j_next,
                                cost=original_cost,
                            )

                        if cost_new < original_cost:
                            original_cost = cost_new
                            if routei == routej:
                                swap_customers(
                                    individual,
                                    customeri,
                                    0,
                                    customerj,
                                    0,
                                )
                            else:
                                swap_customers(
                                    individual,
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

    if not individual.feasible and all(
        capacity_free >= 0
        for capacity_free in individual.route_capacities_free[
            : problem.vehicle_count
        ]
    ):
        individual.cost = (
            original_cost - LEGACY_INFEASIBILITY_PENALTY
        )
        individual.feasible = True
        return

    individual.cost = original_cost


def _try_turn_customer_to_transfer(
    problem: SCVRPProblem,
    distances: memoryview,
    individual: CDELSIndividual,
    customer: int,
) -> bool:
    """嘗試把指定 customer 從一般服務改成 transfer。"""
    customer = int(customer)
    if int(individual.transfer_mask[customer]) == 1:
        return False

    fixed_route = int(problem.fixed_route_for_customer[customer])
    demand = int(problem.demands[customer])
    if demand > individual.transfer_capacities_free[fixed_route]:
        return False

    preceding, successor = _chosen_customer_neighbors(
        individual,
        customer,
    )
    change_cost = _customer_removal_cost(
        distances,
        individual,
        preceding,
        successor,
        customer,
    )

    # [相容性] 舊程式錯把 change_cost 拿來跟 transfer 總剩餘容量比較，
    # 正常應該比較 demand；修正會改變車輛數與 objective。
    has_legacy_capacity = (
        individual.transfer_total_capacity_free >= change_cost
    )
    if change_cost >= individual.cost:
        return False

    individual.transfer_mask[customer] = 1
    individual.cost = change_cost
    if not has_legacy_capacity:
        individual.cost += problem.transfer_cost_once
        individual.transfer_vehicle_count += 1
    individual.transfer_total_capacity_free -= demand
    if not has_legacy_capacity:
        individual.transfer_total_capacity_free += problem.capacity
    individual.transfer_capacities_free[fixed_route] -= demand
    return True


def _turn_transfer_customer_to_nontransfer(
    problem: SCVRPProblem,
    distances: memoryview,
    individual: CDELSIndividual,
    customer: int,
) -> bool:
    """把指定 transfer customer 恢復為一般 route 服務。"""
    customer = int(customer)
    if int(individual.transfer_mask[customer]) != 1:
        return False

    individual.transfer_mask[customer] = 0
    preceding, successor = _chosen_customer_neighbors(
        individual,
        customer,
    )
    change_cost = _customer_insertion_cost(
        distances,
        individual,
        preceding,
        successor,
        customer,
    )

    # [相容性] 這裡不會恢復 fixed-route free capacity；減少 transfer 車輛時
    # 也沒有從 total free capacity 扣回一車容量，因此欄位可能暫時 stale。
    individual.transfer_total_capacity_free += int(
        problem.demands[customer]
    )
    if individual.transfer_total_capacity_free >= problem.capacity:
        individual.transfer_vehicle_count -= 1
        change_cost -= problem.transfer_cost_once
    individual.cost = change_cost
    return True


def _turn_random_customer_to_transfer(
    problem: SCVRPProblem,
    distances: memoryview,
    individual: CDELSIndividual,
    rng: MSVCRandom,
) -> bool:
    """固定消耗一次 RNG，再嘗試其選中的 customer。"""
    customer = rng.rand_mod(problem.n_customers - 1) + 1
    return _try_turn_customer_to_transfer(
        problem,
        distances,
        individual,
        customer,
    )


def _turn_random_transfer_to_nontransfer(
    problem: SCVRPProblem,
    distances: memoryview,
    individual: CDELSIndividual,
    rng: MSVCRandom,
) -> bool:
    """從 transfer customer 中隨機選一位；沒有候選時不抽 RNG。"""
    transfer_customers = [
        customer
        for customer in range(1, problem.n_customers)
        if int(individual.transfer_mask[customer]) == 1
    ]
    if not transfer_customers:
        return False
    customer = transfer_customers[
        rng.rand_mod(len(transfer_customers))
    ]
    return _turn_transfer_customer_to_nontransfer(
        problem,
        distances,
        individual,
        customer,
    )


def _local_search(
    individual: CDELSIndividual,
    *,
    turn_random_customer_to_transfer: Callable[
        [CDELSIndividual], bool
    ],
    two_swap_move: Callable[[CDELSIndividual], None],
    strong_drop_move: Callable[[CDELSIndividual], None],
    drop_one_point_infeasible_move: Callable[[CDELSIndividual], int],
    turn_random_transfer_to_nontransfer: Callable[
        [CDELSIndividual], bool
    ],
    reevaluate: Callable[[CDELSIndividual], object],
) -> None:
    """依 transfer → two-swap → strong-drop → repair 的順序反覆改善。

    [相容性] ``original_cost`` 只在兩個嚴格改善檢查時更新。repair 與完整
    reevaluation 可能讓它 stale；所有 primitive 的回傳值也不是都會被採用。
    """
    no_improvement_count = 0
    original_cost = int(individual.cost)

    while True:
        turn_random_customer_to_transfer(individual)
        two_swap_move(individual)

        if original_cost > individual.cost:
            original_cost = int(individual.cost)
            no_improvement_count = 0
        else:
            no_improvement_count += 1

        if no_improvement_count > 1:
            break

        strong_drop_move(individual)
        if original_cost > individual.cost:
            original_cost = int(individual.cost)
            no_improvement_count = 0
        else:
            no_improvement_count += 1

        if not individual.feasible:
            drop_one_point_infeasible_move(individual)
            if individual.feasible:
                no_improvement_count = 0
            else:
                turn_random_transfer_to_nontransfer(individual)
                reevaluate(individual)

        if no_improvement_count >= 2:
            break


# ============================================================
# ** SA 浮點相容 helper **
# ============================================================

def _cpp_exp(value: float) -> float:
    """讓 Python 的 exp overflow 行為和 C++ 一樣回傳正無限。"""
    try:
        return math.exp(value)
    except OverflowError:
        return math.inf


def _cpp_float_divide(numerator: int, denominator: float) -> float:
    """重現 C++ 不拋例外的 IEEE-754 除法語意。"""
    if denominator == 0.0:
        if numerator > 0:
            return math.inf
        if numerator < 0:
            return -math.inf
        return math.nan
    try:
        return int(numerator) / float(denominator)
    except OverflowError:
        return math.copysign(math.inf, numerator * denominator)


# ============================================================
# ** 完整過程 digest 序列化 **
# ============================================================

def _append_process_digest_individual(
    payload: bytearray,
    individual: CDELSIndividual,
    *,
    customer_count: int,
    route_count: int,
    transfer_route_count: int,
) -> None:
    """依 SCVRP_FULL_POP_V1 的固定欄位順序加入一個 individual。"""
    if len(individual.routes) != route_count:
        raise ValueError("process trace route count mismatch")
    routed_customers: list[int] = []
    for route in individual.routes:
        customers = [int(customer) for customer in route]
        payload.extend(struct.pack("<I", len(customers)))
        if customers:
            payload.extend(
                struct.pack(f"<{len(customers)}i", *customers)
            )
        routed_customers.extend(customers)
    if sorted(routed_customers) != list(range(1, customer_count)):
        raise ValueError(
            "process trace routes must contain each customer exactly once"
        )

    if individual.positions.shape != (2, customer_count):
        raise ValueError("process trace positions shape mismatch")
    positions = [
        int(value) for value in individual.positions.reshape(-1).tolist()
    ]
    payload.extend(
        struct.pack(f"<{2 * customer_count}i", *positions)
    )

    if len(individual.transfer_mask) != customer_count:
        raise ValueError("process trace transfer mask length mismatch")
    transfer_mask = [
        int(value) for value in individual.transfer_mask.tolist()
    ]
    if any(value not in {0, 1} for value in transfer_mask):
        raise ValueError("process trace transfer mask must contain only 0/1")
    payload.extend(
        struct.pack(f"<{customer_count}i", *transfer_mask)
    )

    if not isinstance(individual.feasible, (bool, np.bool_)):
        raise ValueError("process trace feasible flag must be boolean")
    payload.extend(
        struct.pack("<iB", int(individual.cost), int(individual.feasible))
    )

    if len(individual.route_capacities_free) != route_count:
        raise ValueError("process trace route capacity length mismatch")
    payload.extend(
        struct.pack(
            f"<{route_count}i",
            *(int(value) for value in individual.route_capacities_free),
        )
    )
    if len(individual.transfer_capacities_free) != transfer_route_count:
        raise ValueError("process trace transfer capacity length mismatch")
    payload.extend(
        struct.pack(
            f"<{transfer_route_count}i",
            *(int(value) for value in individual.transfer_capacities_free),
        )
    )
    payload.extend(
        struct.pack(
            "<ii",
            int(individual.transfer_vehicle_count),
            int(individual.transfer_total_capacity_free),
        )
    )


def _process_trace_sha256(trace: list[CDELSProcessTrace]) -> str:
    """把每代 digest 再合成一次整段 process SHA-256。"""
    payload = bytearray(_PROCESS_TRACE_SCHEMA)
    payload.extend(struct.pack("<I", len(trace)))
    for entry in trace:
        raw_digest = bytes.fromhex(entry.canonical_digest)
        if len(raw_digest) != 32:
            raise ValueError("process trace digest must be SHA-256")
        payload.extend(raw_digest)
    return sha256(payload).hexdigest()


# ============================================================
# ** OptiForge Engine adapter **
# ============================================================

# Engine、solver config 與輸出報告一律使用這個 ID。
CDELS_SOLVER_ID = "cdels"
COMPATIBILITY_PROFILE = "vs2019_v142_archive"
DE_TECHNIQUE = "rand_1_exp"
_EXPECTED_START_TEMPERATURE = 1.0
_EXPECTED_COOLING_RATE = 0.95
_EXPECTED_ITERATIONS_PER_TEMPERATURE = 110
_ALLOWED_ADAPTER_PARAMS = {
    "compatibility_profile",
    "de_technique",
    "termination_mode",
    "start_temperature",
    "cooling_rate",
    "iterations_per_temperature",
}


@dataclass(frozen=True)
class _CDELSAdapterConfig:
    """把通用 Engine config 收斂成 CDELS 真正使用的欄位。"""

    run_seed: int
    max_iterations: int
    termination_mode: Literal["fixed_iterations"]
    start_temperature: float
    cooling_rate: float
    iterations_per_temperature: int


class CDELSSolverError(RuntimeError):
    """CDELS 核心回傳的狀態違反 Engine contract 時拋出。"""


@dataclass(frozen=True)
class CDELSSolver:
    """讓 Engine 以標準 ``Solver.solve`` 介面執行單檔 CDELS。"""

    def solve(
        self,
        problem: Problem,
        config: dict[str, Any],
        rng: np.random.Generator,
    ) -> SolveResult:
        # CDELS 必須使用內建的 MSVC RNG；Engine 傳進來的 NumPy RNG 不可混用。
        del rng
        if not isinstance(problem, SCVRPProblem):
            raise TypeError("CDELSSolver only supports SCVRPProblem")
        adapter = _parse_adapter_config(config)

        algorithm = CDELS(problem, seed=adapter.run_seed)
        started = time.perf_counter()
        output = algorithm.solve(
            termination_mode=adapter.termination_mode,
            limit=adapter.max_iterations,
            start_temperature=adapter.start_temperature,
            cooling_rate=adapter.cooling_rate,
            iterations_per_temperature=adapter.iterations_per_temperature,
            max_transitions=adapter.max_iterations,
            trace=False,
            process_trace=False,
        )
        algorithm_runtime = time.perf_counter() - started

        _validate_adapter_output(output)
        if output.termination != adapter.termination_mode:
            raise CDELSSolverError(
                "CDELS returned a different termination mode"
            )
        if output.stop_cause != "fixed_iterations":
            raise CDELSSolverError(
                f"CDELS stopped unexpectedly: {output.stop_cause}"
            )
        if output.transition_count != adapter.max_iterations:
            raise CDELSSolverError(
                "CDELS returned a different transition count"
            )
        if output.generation_count != output.transition_count + 1:
            raise CDELSSolverError(
                "CDELS returned an invalid generation count"
            )
        if output.result.generation != output.generation_count:
            raise CDELSSolverError("CDELS snapshot generation mismatch")
        if output.trace != () or output.process_trace != ():
            raise CDELSSolverError(
                "Engine adapter requires CDELS trace output to be disabled"
            )
        if output.process_trace_sha256 is not None:
            raise CDELSSolverError(
                "Engine adapter received an unexpected process-trace digest"
            )

        result = output.result
        evaluation = problem.evaluate(
            result.routes,
            result.transferred_customers,
        )
        if result.objective != evaluation.legacy_search_score:
            raise CDELSSolverError(
                "CDELS/evaluator objective mismatch: "
                f"{result.objective} != {evaluation.legacy_search_score}"
            )
        if result.feasible != evaluation.legacy_feasible:
            raise CDELSSolverError(
                "CDELS/evaluator compatibility feasibility mismatch"
            )
        if result.transfer_vehicle_count != evaluation.transfer_vehicle_count:
            raise CDELSSolverError(
                "CDELS/evaluator transfer vehicle count mismatch"
            )

        encoded = encode_scvrp_solution(
            result.routes,
            result.transferred_customers,
            n_customers=problem.n_customers,
        )
        population_size = 3 * problem.n_customers
        if not 0 <= result.feasible_solutions <= population_size:
            raise CDELSSolverError(
                "CDELS returned an invalid feasible solution count"
            )
        evaluation_count = population_size * output.generation_count
        return SolveResult(
            problem_id=problem.problem_id,
            solver_id=str(config.get("solver_id", CDELS_SOLVER_ID)),
            run_seed=adapter.run_seed,
            best_solution=encoded,
            best_objective=result.objective,
            feasible=result.feasible,
            evaluation_count=evaluation_count,
            stop_reason=_adapter_stop_reason(output.stop_cause),
            runtime=algorithm_runtime,
            linprog_runtime=0.0,
            error=None,
            metadata={
                "compatibility_profile": COMPATIBILITY_PROFILE,
                "de_technique": DE_TECHNIQUE,
                "execution_backend": "python",
                "termination_mode": adapter.termination_mode,
                "stop_cause": output.stop_cause,
                "population_size": population_size,
                "generation_count": output.generation_count,
                "transition_count": output.transition_count,
                "feasible_solution_count": result.feasible_solutions,
                "temperature_stagnation": output.temperature_stagnation,
                "final_temperature_hex": _cpp_hexfloat(
                    output.final_temperature
                ),
                "rng_algorithm": "msvc_rand",
                "rng_state": output.rng_state,
                "rng_draw_count": output.rng_draw_count,
                "transfer_vehicle_count": result.transfer_vehicle_count,
                "raw_objective": evaluation.objective,
                "legacy_penalty": evaluation.legacy_penalty,
                "legacy_search_score": evaluation.legacy_search_score,
            },
        )


def _parse_adapter_config(config: dict[str, Any]) -> _CDELSAdapterConfig:
    """嚴格解析設定，避免拼錯欄位時默默改變可重現結果。"""
    if not isinstance(config, dict):
        raise TypeError("config must be a mapping")
    if "run_seed" not in config:
        raise ValueError("run_seed is required for CDELS")
    run_seed = _strict_int(config["run_seed"], name="run_seed")
    if run_seed <= 0:
        raise ValueError("run_seed must be > 0 for CDELS")
    if run_seed > 0xFFFF_FFFF:
        raise ValueError("run_seed must fit in an unsigned 32-bit integer")

    solver_id = str(config.get("solver_id", CDELS_SOLVER_ID))
    if solver_id != CDELS_SOLVER_ID:
        raise ValueError(f"solver_id must be {CDELS_SOLVER_ID!r}")

    stop_condition = config.get("stop_condition")
    if (
        not isinstance(stop_condition, dict)
        or stop_condition.get("type") != "max_iterations"
    ):
        raise ValueError("CDELS requires stop_condition.type=max_iterations")
    max_iterations = _strict_int(
        stop_condition.get("max_iterations"),
        name="stop_condition.max_iterations",
    )
    if max_iterations <= 0:
        raise ValueError("stop_condition.max_iterations must be > 0")
    if max_iterations > 0x7FFF_FFFE:
        raise ValueError("stop_condition.max_iterations is too large")

    params = config.get("params")
    if not isinstance(params, dict):
        raise ValueError("params must be a mapping")
    unknown = sorted(set(params) - _ALLOWED_ADAPTER_PARAMS)
    if unknown:
        raise ValueError(f"unsupported CDELS params: {unknown}")
    missing = sorted(_ALLOWED_ADAPTER_PARAMS - set(params))
    if missing:
        raise ValueError(f"missing CDELS params: {missing}")

    if params["compatibility_profile"] != COMPATIBILITY_PROFILE:
        raise ValueError(
            "params.compatibility_profile must be "
            f"{COMPATIBILITY_PROFILE!r}"
        )
    if params["de_technique"] != DE_TECHNIQUE:
        raise ValueError(f"params.de_technique must be {DE_TECHNIQUE!r}")
    termination_mode = str(params["termination_mode"])
    if termination_mode != "fixed_iterations":
        raise ValueError("params.termination_mode must be 'fixed_iterations'")

    start_temperature = _strict_float(
        params["start_temperature"],
        name="params.start_temperature",
    )
    cooling_rate = _strict_float(
        params["cooling_rate"],
        name="params.cooling_rate",
    )
    iterations_per_temperature = _strict_int(
        params["iterations_per_temperature"],
        name="params.iterations_per_temperature",
    )
    if start_temperature != _EXPECTED_START_TEMPERATURE:
        raise ValueError(
            "params.start_temperature must be 1.0 in the compatibility profile"
        )
    if cooling_rate != _EXPECTED_COOLING_RATE:
        raise ValueError(
            "params.cooling_rate must be 0.95 in the compatibility profile"
        )
    if iterations_per_temperature != _EXPECTED_ITERATIONS_PER_TEMPERATURE:
        raise ValueError(
            "params.iterations_per_temperature must be 110 in the "
            "compatibility profile"
        )
    return _CDELSAdapterConfig(
        run_seed=run_seed,
        max_iterations=max_iterations,
        termination_mode="fixed_iterations",
        start_temperature=start_temperature,
        cooling_rate=cooling_rate,
        iterations_per_temperature=iterations_per_temperature,
    )


def _strict_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _strict_float(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(
        value,
        (int, float, np.integer, np.floating),
    ):
        raise ValueError(f"{name} must be numeric")
    return float(value)


def _validate_adapter_output(output: CDELSRunResult) -> None:
    """在輸出交給 Engine 前，檢查所有跨層 contract。"""
    if not isinstance(output, CDELSRunResult):
        raise CDELSSolverError("CDELS returned an invalid loop result")
    if not isinstance(output.result, CDELSSnapshot):
        raise CDELSSolverError("CDELS returned an invalid result snapshot")
    integer_fields = {
        "generation_count": output.generation_count,
        "transition_count": output.transition_count,
        "temperature_stagnation": output.temperature_stagnation,
        "rng_state": output.rng_state,
        "rng_draw_count": output.rng_draw_count,
        "result.generation": output.result.generation,
        "result.objective": output.result.objective,
        "result.feasible_solutions": output.result.feasible_solutions,
        "result.transfer_vehicle_count": output.result.transfer_vehicle_count,
    }
    for name, value in integer_fields.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise CDELSSolverError(
                f"CDELS field {name} must be an integer"
            )
    for name, value in integer_fields.items():
        if name != "result.objective" and value < 0:
            raise CDELSSolverError(f"CDELS field {name} must be >= 0")
    if output.generation_count == 0 or output.result.generation == 0:
        raise CDELSSolverError("CDELS generation count must be > 0")
    if not 0 <= output.rng_state <= 0xFFFF_FFFF:
        raise CDELSSolverError(
            "CDELS RNG state must fit in an unsigned 32-bit integer"
        )
    if (
        isinstance(output.final_temperature, bool)
        or not isinstance(output.final_temperature, (int, float))
        or not math.isfinite(float(output.final_temperature))
        or output.final_temperature < 0
    ):
        raise CDELSSolverError(
            "CDELS final temperature must be finite and >= 0"
        )
    if not isinstance(output.result.feasible, bool):
        raise CDELSSolverError("CDELS feasible flag must be a boolean")
    if not isinstance(output.result.routes, tuple) or not all(
        isinstance(route, tuple) for route in output.result.routes
    ):
        raise CDELSSolverError("CDELS routes must be tuples")
    if not isinstance(output.result.transferred_customers, tuple):
        raise CDELSSolverError(
            "CDELS transferred customers must be a tuple"
        )


def _cpp_hexfloat(value: float) -> str:
    """格式化成 archive C++ ``std::hexfloat`` 使用的字串。"""
    significand, exponent = float(value).hex().split("p", maxsplit=1)
    if "." in significand:
        significand = significand.rstrip("0").rstrip(".")
    return f"{significand}p{exponent}"


def _adapter_stop_reason(stop_cause: str) -> str:
    if stop_cause in {"fixed_iterations", "max_transitions"}:
        return "max_iterations_reached"
    raise CDELSSolverError(
        f"CDELS returned unknown stop cause: {stop_cause!r}"
    )
