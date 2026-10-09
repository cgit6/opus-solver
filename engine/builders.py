"""內建求解器建構子（可由 `build(..., solver_builders=...)` 覆寫）。"""

from __future__ import annotations

from ..solver.ABC import ABCSolver
from ..solver.BSCA import BSCASolver
from ..solver.BSMA import BSMASolver
from ..solver.CDELS import CDELSSolver
from ..solver.CDELS_2 import CDELS2Solver
from ..solver.CDELS_2_numba import CDELS2NumbaSolver
from ..solver.CDELS_numba import CDELSNumbaSolver
from ..solver.CDELS_packed_numba import CDELSPackedNumbaSolver
from ..solver.HSMSCA import HSMSCASolver
from ..solver.registry import SolverBuilder, StubMaxIterationsSolver


# 註冊新求解
def solverBuilders() -> dict[str, SolverBuilder]:
    return {
        "stub_solver": lambda: StubMaxIterationsSolver(),
        "abc": lambda: ABCSolver(),
        "bsma": lambda: BSMASolver(),
        "bsca": lambda: BSCASolver(),
        "hsmsca": lambda: HSMSCASolver(),
        "cdels": lambda: CDELSSolver(),
        "cdels_2": lambda: CDELS2Solver(),
        "cdels_numba": lambda: CDELSNumbaSolver(),
        "cdels_packed_numba": lambda: CDELSPackedNumbaSolver(),
        "cdels_2_numba": lambda: CDELS2NumbaSolver(),
    }
