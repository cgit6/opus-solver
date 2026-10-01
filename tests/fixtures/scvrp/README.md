# SCVRP legacy fixtures

These normalized-text fixtures were recovered from `note/study/SCRP.rar` and
are used only as compatibility test vectors.

- `p_n16_k8.vrp`
  - archive member: `CDELS_project(SA版)/instances/P/P-n16-k8.vrp`
  - recovered SHA-256: `122bf4349112f700d351def4ffee143f146346f2ec6e5618af07513d5cf8be7b`
- `p_n16_k8_routecap2_transfer1.txt`
  - archive member: `CDELS_project(SA版)/instances/P/P-n16-k8_RouteCap_2.txt_WithSpareCapacity_MaxTransfer_1_Gurobi.txt`
  - recovered SHA-256: `cb40e6defb2d1c41d9d422307a4261cd8d8d643e7d574a406213710bca17f8d3`
- `p_n16_k8_seed1_solution.txt`
  - extracted from seed 1 in `Set_p-n16-k8/P-n16-k8_RouteCap_2.txt_WithSpareCapacity_MaxTransfer_1_solution.csv`
  - full recovered file SHA-256: `9391fd96c6ddec3d1cb140b06c746083bbc8fcd72e4875e4b36f4c947c168507`
- `p_n16_k8_seed1_initial_report.txt`
  - extracted from the first generation in `Set_p-n16-k8/P-n16-k8_RouteCap_2.txt_WithSpareCapacity_MaxTransfer_1_report.txt`
  - full recovered file SHA-256: `2df25f4ed2a7d8341c8d2bfeba8243d5af41a460b944a56be6e9393f8d6490aa`
- `p_n16_k8_seeds_1_10_golden.json`
  - compact, runtime-free oracle for all ten archived seeds
  - preserves final route order and empty routes, transfer state, first optimum
    generation, and hashes of the 11,221-generation traces
  - both the solution and report members pass the CRC stored in the RAR header

## Trace normalization

The archived executable ran seeds 1 through 10 in one process and its static
generation counter was not reset between seeds. The raw report ranges are
therefore `1..11221`, `11222..22442`, through `100990..112210`. The golden
oracle normalizes every seed block to local generations `1..11221`, matching
the isolated one-seed compatibility runner.

The trace digests use the following canonical ASCII records, each terminated by
LF (including the final record):

- `best_trace_sha256`: `<objective>\n`
- `objective_feasible_trace_sha256`:
  `<local_generation>,<objective>,<feasible_solution_count>\n`
- `semantic_trace_sha256`: compact JSON with sorted keys containing local
  generation, objective, feasible-solution count, and the exact best route,
  transfer order, and transfer-vehicle count. Generation 1 uses
  `"solution":null` because the archived report does not print its solution.

These hashes establish equality of the archived best-of-generation observable
trace. They do not cover the complete population, rejected candidates, every
RNG draw, floating-point intermediate bits, runtime, or byte-for-byte report
formatting.

Line endings are normalized to LF, so fixture hashes intentionally differ
from the recovered archive members.
