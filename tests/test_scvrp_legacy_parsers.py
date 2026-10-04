from __future__ import annotations

from pathlib import Path

from mkp.problem.scvrp import (
    parse_legacy_cvrp_instance,
    parse_legacy_fixed_route_plan,
    parse_legacy_scvrp_solutions,
)


FIXTURES = Path(__file__).parent / "fixtures" / "scvrp"


def test_parse_archived_p_n16_k8_instance() -> None:
    instance = parse_legacy_cvrp_instance(FIXTURES / "p_n16_k8.vrp")

    assert instance.name == "P-n16-k8"
    assert instance.vehicle_count == 8
    assert instance.cvrp_best_known == 450
    assert instance.n_customers == 16
    assert instance.capacity == 35
    assert instance.coords[0].tolist() == [30.0, 40.0]
    assert instance.coords[15].tolist() == [37.0, 69.0]
    assert instance.demands.tolist() == [0, 19, 30, 16, 23, 11, 31, 15, 28, 8, 8, 7, 14, 6, 19, 11]


def test_parse_legacy_instance_accepts_archive_section_marker_whitespace(
    tmp_path: Path,
) -> None:
    source = (FIXTURES / "p_n16_k8.vrp").read_text(encoding="ascii")
    archived_format = source.replace(
        "NODE_COORD_SECTION\n",
        "NODE_COORD_SECTION \r\n",
    ).replace(
        "DEMAND_SECTION\n",
        "DEMAND_SECTION \r\n",
    ).replace(
        "DEPOT_SECTION\n",
        "DEPOT_SECTION \r\n",
    )
    path = tmp_path / "p_n16_k8_archive_spacing.vrp"
    path.write_text(archived_format, encoding="ascii", newline="")

    instance = parse_legacy_cvrp_instance(path)

    assert instance.name == "P-n16-k8"
    assert instance.n_customers == 16
    assert instance.demands.tolist()[-1] == 11


def test_parse_archived_fixed_routes_and_seed_one_solution() -> None:
    plan = parse_legacy_fixed_route_plan(
        FIXTURES / "p_n16_k8_routecap2_transfer1.txt",
        n_customers=16,
    )
    solutions = parse_legacy_scvrp_solutions(FIXTURES / "p_n16_k8_seed1_solution.txt")

    assert plan.routes == (
        (7, 9),
        (13, 8),
        (14, 5),
        (10, 3),
        (1,),
        (6,),
        (15, 12),
        (2,),
        (11, 4),
    )
    assert plan.capacities_free == (8, 6, 11, 8, 19, 31, 11, 30, 7)
    assert len(solutions) == 1

    solution = solutions[0]
    assert solution.seed == 1
    assert solution.objective == 350
    assert solution.feasible is True
    assert solution.routes[5] == ()
    assert solution.transferred_customers == (1, 2, 5, 9, 10, 11, 13, 15)
    assert solution.transfer_vehicle_count == 3
