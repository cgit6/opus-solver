from __future__ import annotations

from pathlib import Path

from .support import (
    _resolveSeedStrategy,
    buildSimulationBundle,
    createExperimentSpec,
    executeSimulator,
    parser,
)


def main(
    argv: list[str] | None = None,
    *,
    problem_root: Path | str = Path("configs/problems"),
    solver_root: Path | str = Path("configs/solvers"),
    output_root: Path | str = Path("output"),
):
    """CLI 入口；可由程式呼叫並注入 `argv` / `problem_root` / `solver_root`（測試用）"""

    arg_parser = parser() # 獲取命令行參數，並解析&驗證
    args = arg_parser.parse_args(argv) # 獲取命令行參數
    spec = createExperimentSpec(args) # 實驗規格物件
    seed_strategy = _resolveSeedStrategy(raw_run_seeds=args.run_seeds, repeat=spec.repeat)
    bundle = buildSimulationBundle(
        spec,
        param_set_index=args.param_set_index,
        seed_strategy=seed_strategy,
        problem_root=Path(problem_root),
        solver_root=Path(solver_root),
    )

    # 執行模擬
    return executeSimulator(
        bundle=bundle,
        output_root=Path(output_root),
    )
