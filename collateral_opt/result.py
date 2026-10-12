"""Allocation results shared by the optimiser and the baseline heuristic."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Problem


@dataclass
class Allocation:
    asset_id: str
    requirement_id: str
    market_value: float
    haircut: float
    annual_cost: float

    @property
    def collateral_value(self) -> float:
        """Post-haircut value credited against the requirement."""
        return self.market_value * (1 - self.haircut)


@dataclass
class AllocationResult:
    method: str
    allocations: list[Allocation] = field(default_factory=list)
    status: str = "optimal"

    @property
    def total_cost(self) -> float:
        return sum(a.annual_cost for a in self.allocations)

    def coverage(self, requirement_id: str) -> float:
        return sum(a.collateral_value for a in self.allocations if a.requirement_id == requirement_id)

    def used(self, asset_id: str) -> float:
        return sum(a.market_value for a in self.allocations if a.asset_id == asset_id)

    def shortfalls(self, problem: Problem, tol: float = 1e-6) -> dict[str, float]:
        out = {}
        for r in problem.requirements:
            gap = r.amount - self.coverage(r.id)
            if gap > tol * max(1.0, r.amount):
                out[r.id] = gap
        return out

    def to_dict(self, problem: Problem) -> dict:
        return {
            "method": self.method,
            "status": self.status,
            "total_annual_cost": self.total_cost,
            "shortfalls": self.shortfalls(problem),
            "allocations": [
                {
                    "asset_id": a.asset_id,
                    "requirement_id": a.requirement_id,
                    "market_value": a.market_value,
                    "haircut": a.haircut,
                    "collateral_value": a.collateral_value,
                    "annual_cost": a.annual_cost,
                }
                for a in self.allocations
            ],
        }
