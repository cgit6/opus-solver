"""MKP simulation system package."""

if __name__ == "__init__" and not __package__:
    import os as _os

    __package__ = "mkp"
    if __spec__ is not None:
        __spec__.name = "mkp"
        __spec__.submodule_search_locations = [_os.path.dirname(__file__)]
    del _os

from .cli.convert import getConverter, listConverters, register
from .cli.run import executeSimulator
from .converter import transformToMomery, transformToYaml
from .engine import Engine, SimulationBundle, SolverConfigsSnapshot, build
from .engine.models import ExperimentSpec, SolveResult, RunTask
from .machine import Machine, MachinePool, MachinePoolSession, MachineResult
from .engine.repository import ProblemRepository
from .problem import Problem, MKPProblem, ProblemModel, ProblemRegistry, ProblemTypeSpec, TSPProblem, ValidationReport
from .simulator import Simulator, SimulatorResult, SimulatorRunRow
from .solver.BSCA_numba import BSCANumbaCore, BSCANumbaSolver
from .solver.BSCA_rc_numba import BSCARCNumbaCore, BSCARCNumbaSolver
from .solver.BSCASMA_rl_numba import BRLSMASCARLNumbaSolver
from .solver.BSCASMA_rl_rc_numba import BRLSMASCARLRCNumbaSolver
from .solver.BSMA_numba import BSMANumbaCore, BSMANumbaSolver
from .solver.BSMA_rc_numba import BSMARCNumbaCore, BSMARCNumbaSolver
from .solver.registry import SolverRegistry, StubMaxIterationsSolver
from .tools.show import write_simulator_result
from .tools.solver_config_loader import SolverConfigLoader
from .tools.stat import ResultEntry


def __getattr__(name: str):
    """延遲載入 `main`（實作於 `mkp.cli.run`）。"""
    if name == "main":
        from .cli.run.main import main as _main

        return _main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Engine",
    "ExperimentSpec",
    "SimulationBundle",
    "SimulatorResult",
    "SimulatorRunRow",
    "SolverConfigsSnapshot",
    "build",
    "executeSimulator",
    "BSCANumbaCore",
    "BSCANumbaSolver",
    "BSCARCNumbaCore",
    "BSCARCNumbaSolver",
    "BRLSMASCARLNumbaSolver",
    "BRLSMASCARLRCNumbaSolver",
    "BSMANumbaCore",
    "BSMANumbaSolver",
    "BSMARCNumbaCore",
    "BSMARCNumbaSolver",
    "main",
    "Machine",
    "MachinePool",
    "MachinePoolSession",
    "MachineResult",
    "ProblemModel",
    "Problem",
    "MKPProblem",
    "TSPProblem",
    "ProblemRegistry",
    "ProblemTypeSpec",
    "SolveResult",
    "RunTask",
    "getConverter",
    "listConverters",
    "register",
    "transformToMomery",
    "transformToYaml",
    "ProblemRepository",
    "ResultEntry",
    "Simulator",
    "SolverConfigLoader",
    "SolverRegistry",
    "StubMaxIterationsSolver",
    "ValidationReport",
    "write_simulator_result",
]
