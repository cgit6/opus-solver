"""內建求解器建構子（可由 `build(..., solver_builders=...)` 覆寫）。"""

from __future__ import annotations

from ..solver.BSCA_rc_numba import BSCARCNumbaSolver
from ..solver.BSCASMA_rl_rc_numba import BRLSMASCARLRCNumbaSolver
from ..solver.BSMA_rc_numba import BSMARCNumbaSolver
from ..solver.CDELS import CDELSSolver
from ..solver.CDELS_workspace import CDELSWorkspaceSolver
from ..solver.registry import SolverBuilder, StubMaxIterationsSolver


# 註冊新求解
def solverBuilders() -> dict[str, SolverBuilder]:
    return {
        "stub_solver": lambda: StubMaxIterationsSolver(),
        "bsma_rc_numba": lambda: BSMARCNumbaSolver(),
        "bsca_rc_numba": lambda: BSCARCNumbaSolver(),
        "brlsmasca_rl_rc_numba": lambda: BRLSMASCARLRCNumbaSolver(),
        "cdels": lambda: CDELSSolver(),
        "cdels_workspace": lambda: CDELSWorkspaceSolver(),
    }
