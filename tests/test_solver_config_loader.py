from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mkp.tools.solver_config_loader import SolverConfigLoader


def _write_solver_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_load_valid_solver_config(tmp_path: Path):
    root = tmp_path / "solvers"
    _write_solver_yaml(
        root / "stub_solver.yaml",
        """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 10
  max_seconds: null
params:
  - {}
""".strip(),
    )
    loader = SolverConfigLoader(config_root=root)
    config = loader.load("stub_solver", param_set_index=0)

    assert config["solver_id"] == "stub_solver"
    assert config["stop_condition"]["type"] == "max_iterations"
    assert config["params"] == {}
    assert config["param_set_index"] == 0


def test_load_selects_requested_param_set(tmp_path: Path) -> None:
    root = tmp_path / "solvers"
    _write_solver_yaml(
        root / "stub_solver.yaml",
        """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 10
  max_seconds: null
params:
  - {pop_size: 20, z: 0.08}
  - {pop_size: 30, z: 0.03, ctf: sigmoid_s0}
""".strip(),
    )
    loader = SolverConfigLoader(config_root=root)

    config = loader.load("stub_solver", param_set_index=1)

    assert config["params"] == {"pop_size": 30, "z": 0.03, "ctf": "sigmoid_s0"}
    assert config["param_set_index"] == 1


def test_load_all_returns_each_param_set(tmp_path: Path) -> None:
    root = tmp_path / "solvers"
    _write_solver_yaml(
        root / "stub_solver.yaml",
        """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 10
  max_seconds: null
params:
  - {pop_size: 20, z: 0.08}
  - {pop_size: 30, z: 0.03}
""".strip(),
    )
    loader = SolverConfigLoader(config_root=root)

    configs = loader.load_all("stub_solver")

    assert [config["param_set_index"] for config in configs] == [0, 1]
    assert [config["params"] for config in configs] == [
        {"pop_size": 20, "z": 0.08},
        {"pop_size": 30, "z": 0.03},
    ]


def test_solver_id_must_match_file_name(tmp_path: Path):
    root = tmp_path / "solvers"
    _write_solver_yaml(
        root / "stub_solver.yaml",
        """
solver_id: other_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 10
params:
  - {}
""".strip(),
    )
    loader = SolverConfigLoader(config_root=root)

    with pytest.raises(ValueError, match="solver_id mismatch"):
        loader.load("stub_solver", param_set_index=0)


def test_stop_condition_type_validation(tmp_path: Path):
    root = tmp_path / "solvers"
    _write_solver_yaml(
        root / "stub_solver.yaml",
        """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: unsupported
  max_iterations: 10
params:
  - {}
""".strip(),
    )
    loader = SolverConfigLoader(config_root=root)

    with pytest.raises(ValueError, match="stop_condition.type"):
        loader.load("stub_solver", param_set_index=0)


def test_missing_capabilities_rejected(tmp_path: Path) -> None:
    root = tmp_path / "solvers"
    _write_solver_yaml(
        root / "stub_solver.yaml",
        """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
stop_condition:
  type: max_iterations
  max_iterations: 10
params:
  - {}
""".strip(),
    )
    loader = SolverConfigLoader(config_root=root)

    with pytest.raises(ValueError, match="Missing required field"):
        loader.load("stub_solver", param_set_index=0)


@pytest.mark.parametrize(
    "content, error_match",
    [
        (
            """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 0
params:
  - {}
""",
            "max_iterations must be > 0",
        ),
        (
            """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_seconds
  max_seconds: 0
params:
  - {}
""",
            "max_seconds must be > 0",
        ),
    ],
)
def test_stop_condition_value_validation(tmp_path: Path, content: str, error_match: str):
    root = tmp_path / "solvers"
    _write_solver_yaml(root / "stub_solver.yaml", content.strip())
    loader = SolverConfigLoader(config_root=root)

    with pytest.raises(ValueError, match=error_match):
        loader.load("stub_solver", param_set_index=0)


@pytest.mark.parametrize(
    "content, error_match",
    [
        (
            """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 10
params: {}
""",
            "params must be a non-empty list",
        ),
        (
            """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 10
params: []
""",
            "params must be a non-empty list",
        ),
        (
            """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 10
params:
  - {}
  - 123
""",
            "params\\[1\\] must be a mapping",
        ),
    ],
)
def test_params_schema_validation(tmp_path: Path, content: str, error_match: str) -> None:
    root = tmp_path / "solvers"
    _write_solver_yaml(root / "stub_solver.yaml", content.strip())
    loader = SolverConfigLoader(config_root=root)

    with pytest.raises(ValueError, match=error_match):
        loader.load("stub_solver", param_set_index=0)


def test_param_set_index_range_validation(tmp_path: Path) -> None:
    root = tmp_path / "solvers"
    _write_solver_yaml(
        root / "stub_solver.yaml",
        """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 10
params:
  - {}
""".strip(),
    )
    loader = SolverConfigLoader(config_root=root)

    with pytest.raises(ValueError, match="param_set_index out of range"):
        loader.load("stub_solver", param_set_index=1)


def test_load_group_selects_stable_key_and_exposes_resolved_index(tmp_path: Path) -> None:
    root = tmp_path / "solvers"
    _write_solver_yaml(
        root / "stub_solver.yaml",
        """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 10
parameter_groups:
  - key: baseline
    params: {pop_size: 20, z: 0.08}
  - key: exploratory
    params: {pop_size: 30, z: 0.03}
""".strip(),
    )
    loader = SolverConfigLoader(config_root=root)

    config = loader.load_group("stub_solver", group_key="exploratory")

    assert config["group_key"] == "exploratory"
    assert config["param_set_index"] == 1
    assert config["params"] == {"pop_size": 30, "z": 0.03}
    assert "parameter_groups" not in config


def test_load_group_reference_is_stable_when_groups_are_reordered(tmp_path: Path) -> None:
    root = tmp_path / "solvers"
    path = root / "stub_solver.yaml"
    prefix = """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 10
parameter_groups:
""".strip()
    baseline = "  - key: baseline\n    params: {pop_size: 20, z: 0.08}"
    exploratory = "  - key: exploratory\n    params: {pop_size: 30, z: 0.03}"
    _write_solver_yaml(path, f"{prefix}\n{baseline}\n{exploratory}")
    loader = SolverConfigLoader(config_root=root)
    before = loader.load_group("stub_solver", group_key="baseline")

    _write_solver_yaml(path, f"{prefix}\n{exploratory}\n{baseline}")
    after = loader.load_group("stub_solver", group_key="baseline")

    assert before["params"] == after["params"] == {"pop_size": 20, "z": 0.08}
    assert before["group_key"] == after["group_key"] == "baseline"
    assert before["param_set_index"] == 0
    assert after["param_set_index"] == 1


@pytest.mark.parametrize(
    "groups, error_match",
    [
        (
            """
  - key: baseline
    params: {}
  - key: baseline
    params: {z: 0.1}
""",
            "duplicate parameter group key",
        ),
        (
            """
  - key: ""
    params: {}
""",
            "parameter_groups\\[0\\].key",
        ),
        (
            """
  - key: baseline
    params: 123
""",
            "parameter_groups\\[0\\].params",
        ),
    ],
)
def test_parameter_group_schema_validation(
    tmp_path: Path,
    groups: str,
    error_match: str,
) -> None:
    root = tmp_path / "solvers"
    _write_solver_yaml(
        root / "stub_solver.yaml",
        f"""
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 10
parameter_groups:
{groups.rstrip()}
""".strip(),
    )
    loader = SolverConfigLoader(config_root=root)

    with pytest.raises(ValueError, match=error_match):
        loader.load_all("stub_solver")


def test_solver_config_rejects_params_and_parameter_groups_together(tmp_path: Path) -> None:
    root = tmp_path / "solvers"
    _write_solver_yaml(
        root / "stub_solver.yaml",
        """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 10
params:
  - {}
parameter_groups:
  - key: baseline
    params: {}
""".strip(),
    )
    loader = SolverConfigLoader(config_root=root)

    with pytest.raises(ValueError, match="exactly one of params or parameter_groups"):
        loader.load_all("stub_solver")


def test_load_group_rejects_legacy_params_schema(tmp_path: Path) -> None:
    root = tmp_path / "solvers"
    _write_solver_yaml(
        root / "stub_solver.yaml",
        """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 10
params:
  - {pop_size: 20}
""".strip(),
    )
    loader = SolverConfigLoader(config_root=root)

    with pytest.raises(ValueError, match="managed group lookup requires parameter_groups"):
        loader.load_group("stub_solver", group_key="baseline")


def test_load_bscasma_rl_rc_numba_param_20_from_default_configs() -> None:
    loader = SolverConfigLoader()

    config = loader.load("hsmsca", param_set_index=20)

    assert config["solver_id"] == "hsmsca"
    assert config["solver_class"] == "HSMSCASolver"
    assert config["params"] == {
        "pop_size": 20,
        "z": 0.01,
        "a": 2.5,
        "alpha": 0.1,
        "gamma": 0.9,
        "ctf": "abs_pow_16",
        "eval_group_decimals": 1,
        "eval_group_shuffle": False,
        "eval_rc_eps": 1.0e-9,
        "eval_x_eps": 1.0e-9,
        "repair_passes": 2,
        "repair_swap_limit": 4,
        "mixed_init_enabled": True,
        "restart_enabled": True,
        "restart_window": 40,
        "restart_ratio": 0.25,
        "restart_strong_p": 0.85,
        "restart_core_p": 0.50,
        "restart_weak_p": 0.15,
        "guided_binary_enabled": True,
        "guided_lambda_lp": 0.30,
        "guided_lambda_bucket": 0.08,
        "guided_lambda_slack": 0.10,
        "local_search_enabled": True,
        "ls_budget_per_run": 1500,
        "ls_max_passes": 2,
        "ls_cooldown": 10,
        "ls_add_cap": 80,
        "ls_drop_cap": 80,
        "archive_pr_enabled": True,
        "archive_size": 8,
        "pr_interval": 15,
        "pr_max_steps": 15,
        "pr_core_only": True,
    }
    assert config["stop_condition"]["max_iterations"] == 5000


def test_concurrent_solver_config_loads(tmp_path: Path) -> None:
    root = tmp_path / "solvers"
    _write_solver_yaml(
        root / "stub_solver.yaml",
        """
solver_id: stub_solver
solver_class: StubMaxIterationsSolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
stop_condition:
  type: max_iterations
  max_iterations: 10
params:
  - {}
""".strip(),
    )
    loader = SolverConfigLoader(config_root=root)

    def _load(_: int) -> str:
        return loader.load("stub_solver", param_set_index=0)["solver_id"]

    with ThreadPoolExecutor(16) as pool:
        ids = list(pool.map(_load, range(32)))

    assert ids == ["stub_solver"] * 32
