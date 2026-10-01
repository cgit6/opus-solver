"""內建求解器建構子（可由 `build(..., solver_builders=...)` 覆寫）。"""

from __future__ import annotations

from ..solver.BSCA_numba import BSCANumbaSolver
from ..solver.BSCA_rc_numba import BSCARCNumbaSolver
from ..solver.BSCASMA_rl_rc_numba import BRLSMASCARLRCNumbaSolver
from ..solver.BSCASMA_rl_numba import BRLSMASCARLNumbaSolver
from ..solver.BSMA_numba import BSMANumbaSolver
from ..solver.BSMA_rc_numba import BSMARCNumbaSolver
from ..solver.scvrp_legacy_sa import SCVRPLegacySASolver
from ..solver.registry import SolverBuilder, StubMaxIterationsSolver


# 註冊新求解
def solverBuilders() -> dict[str, SolverBuilder]:
    return {
        "stub_solver": lambda: StubMaxIterationsSolver(),
        "bsma_numba": lambda: BSMANumbaSolver(),
        "bsma_rc_numba": lambda: BSMARCNumbaSolver(),
        "bsca_numba": lambda: BSCANumbaSolver(),
        "bsca_rc_numba": lambda: BSCARCNumbaSolver(),
        "brlsmasca_rl_numba": lambda: BRLSMASCARLNumbaSolver(),
        "brlsmasca_rl_rc_numba": lambda: BRLSMASCARLRCNumbaSolver(),
        "scvrp_legacy_sa": lambda: SCVRPLegacySASolver(),
    }
