"""Collateral optimisation: allocate inventory to margin requirements at minimum cost."""

from .baseline import greedy
from .models import Asset, ConcentrationLimit, EligibilityRule, Problem, Requirement, load_problem, problem_from_dict
from .optimizer import optimise
from .result import Allocation, AllocationResult

__all__ = [
    "Asset", "ConcentrationLimit", "EligibilityRule", "Problem", "Requirement",
    "Allocation", "AllocationResult", "load_problem", "problem_from_dict", "optimise", "greedy",
]
