"""Optimization problem definitions and registration helpers."""

from __future__ import annotations

from .builders import buildProblemRegistry, problemBuilders
from .continuous import ContinuousProblem
from .interface import Direction, Problem
from .mkp import MKPProblem
from .registry import ProblemRegistry, ProblemTypeSpec
from .scvrp import SCVRPEvaluation, SCVRPProblem
from .tsp import TSPProblem
from .validation import DirectionSpec, ObjectiveValue, ScalarObjective, ValidationReport

ProblemModel = MKPProblem

__all__ = [
    "Direction",
    "DirectionSpec",
    "ObjectiveValue",
    "ScalarObjective",
    "Problem",
    "ProblemModel",
    "ContinuousProblem",
    "MKPProblem",
    "SCVRPEvaluation",
    "SCVRPProblem",
    "TSPProblem",
    "ProblemRegistry",
    "ProblemTypeSpec",
    "ValidationReport",
    "problemBuilders",
    "buildProblemRegistry",
]
