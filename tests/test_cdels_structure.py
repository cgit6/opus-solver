from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys

from mkp.engine.builders import solverBuilders
from mkp.tools.solver_config_loader import SolverConfigLoader


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_cdels_and_cdels_2_experiment_are_registered() -> None:
    builders = solverBuilders()

    assert "cdels" in builders
    assert "cdels_2" in builders
    assert "scvrp_legacy_sa" not in builders
    assert builders["cdels"]().__class__.__name__ == "CDELSSolver"
    assert (
        builders["cdels_2"]().__class__.__name__
        == "CDELS2Solver"
    )


def test_cdels_does_not_import_removed_or_native_solver_modules() -> None:
    source_path = REPO_ROOT / "solver/CDELS.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    forbidden_suffixes = {
        "scvrp_legacy",
        "scvrp_legacy_kernel",
        "scvrp_legacy_local_search",
        "scvrp_legacy_sa",
        "scvrp_native_oracle",
        "subprocess",
        "ctypes",
        "cffi",
    }
    assert not any(
        module.split(".")[-1] in forbidden_suffixes
        for module in imported_modules
    )


def test_formal_engine_import_does_not_load_native_oracle() -> None:
    script = """
import json
import sys
from mkp.engine.builders import solverBuilders
solver = solverBuilders()["cdels"]()
print(json.dumps({
    "solver": solver.__class__.__name__,
    "native_loaded": "mkp.tools.scvrp_native_oracle" in sys.modules,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == (
        '{"solver": "CDELSSolver", "native_loaded": false}'
    )


def test_cdels_solver_configs_exist_for_baseline_and_cdels_2() -> None:
    solver_root = REPO_ROOT / "configs/solvers"

    assert (solver_root / "cdels.yaml").is_file()
    assert (solver_root / "cdels_2.yaml").is_file()
    assert not (solver_root / "scvrp_legacy_sa.yaml").exists()


def test_cdels_2_config_resolves_to_registered_solver() -> None:
    solver_root = REPO_ROOT / "configs/solvers"
    config = SolverConfigLoader(solver_root).load(
        "cdels_2",
        param_set_index=0,
    )

    solver = solverBuilders()[config["solver_id"]]()
    assert config["solver_class"] == "CDELS2Solver"
    assert solver.__class__.__name__ == config["solver_class"]
