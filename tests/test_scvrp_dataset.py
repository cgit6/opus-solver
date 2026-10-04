from __future__ import annotations

from pathlib import Path

from mkp.tools.scvrp_dataset import (
    BASE_INSTANCES,
    LEGACY_OWNER_ZERO_STATUS,
    PARAMETER_COMBINATIONS,
    _ensure_plan,
    _load_record_problem,
    build_validation_plan,
    inventory,
    load_manifest,
    main,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "note/study/scvrp/dataset/legacy_sa/instances"


def test_inventory_preserves_all_sources_and_marks_legacy_owner_zero_inputs() -> None:
    manifest = inventory(SOURCE_ROOT)

    assert manifest["summary"] == {
        "total": 112,
        "valid": 96,
        "legacy_compatible": 16,
        "runnable": 112,
        "blocked": 0,
    }
    assert len(BASE_INSTANCES) == 7
    assert len(PARAMETER_COMBINATIONS) == 16
    compatible = [
        record
        for record in manifest["records"]
        if record["status"] == LEGACY_OWNER_ZERO_STATUS
    ]
    assert {record["base_instance"] for record in compatible} == {
        "A-n32-k5",
        "A-n48-k7",
        "A-n64-k9",
        "A-n80-k10",
    }
    assert {record["route_cap"] for record in compatible} == {8}
    assert {record["max_transfer"] for record in compatible} == {1, 2, 3, 4}
    assert all(
        record["issues"][0].startswith("missing_customers:")
        for record in compatible
    )
    assert all(record["legacy_missing_owner"] == 0 for record in compatible)


def test_legacy_owner_zero_loader_preserves_capacities_and_adds_missing_customer() -> None:
    manifest = inventory(SOURCE_ROOT)
    record = next(
        record
        for record in manifest["records"]
        if record["problem_id"] == "A-n32-k5-routecap8-transfer2"
    )

    problem = _load_record_problem(
        record=record,
        source_root=SOURCE_ROOT,
        best_known=None,
    )

    assert problem.fixed_route_for_customer[2] == 0
    assert problem.fixed_routes[0][-1] == 2
    assert problem.fixed_route_capacities.tolist() == [30, 44, 6, 5, 7]


def test_cli_without_subcommand_only_prints_help(capsys) -> None:
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "inventory" in captured.out
    assert "import-configs" in captured.out


def test_validation_plan_counts_valid_tasks_without_running_solver() -> None:
    manifest_path = REPO_ROOT / "note/study/scvrp/dataset_manifest.json"
    plan = build_validation_plan(
        manifest=load_manifest(manifest_path),
        manifest_path=manifest_path,
        problem_root=REPO_ROOT / "configs/problems",
        seeds=(1, 2),
        iterations=111,
    )

    assert len(plan["tasks"]) == 112 * 2
    assert len(plan["blocked"]) == 0
    assert len(plan["legacy_compatible"]) == 16
    assert plan["deep_process_trace"] is True
    assert plan["comparison"] == "cdels_python_vs_archived_sa_cpp_oracle"
    assert len(plan["solver_contract_sha256"]) == 64


def test_validate_run_defaults_to_plan_only(capsys) -> None:
    assert main(["validate-run", "--seeds", "1", "--iterations", "0"]) == 0
    captured = capsys.readouterr()
    assert '"tasks": 112' in captured.out
    assert '"will_execute": false' in captured.out


def test_validate_run_can_start_from_task_46(capsys) -> None:
    assert main(
        [
            "validate-run",
            "--seeds",
            "1",
            "--iterations",
            "0",
            "--start-task",
            "46",
        ]
    ) == 0
    captured = capsys.readouterr()
    assert '"start_task": 46' in captured.out
    assert '"selected_tasks": 67' in captured.out


def test_continuation_plan_does_not_conflict_with_existing_base_plan(
    tmp_path: Path,
) -> None:
    old_plan = {"plan_sha256": "old"}
    continuation_plan = {"plan_sha256": "new"}

    _ensure_plan(tmp_path, old_plan, start_task=1)
    _ensure_plan(tmp_path, continuation_plan, start_task=46)

    assert (tmp_path / "plan.json").read_text(encoding="utf-8") == (
        '{"plan_sha256":"old"}\n'
    )
    assert (tmp_path / "plan.from-task-46.json").read_text(
        encoding="utf-8"
    ) == '{"plan_sha256":"new"}\n'
