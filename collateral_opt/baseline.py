"""Greedy "cheapest-to-deliver" heuristic, used as a benchmark for the optimiser.

Requirements are filled one at a time, largest first. Each takes the cheapest
eligible assets still available (ranked by cost per unit of post-haircut value),
respecting concentration limits. This mirrors a typical manual allocation
process and ignores the knock-on effect on later requirements.
"""

from __future__ import annotations

from .models import Problem
from .result import Allocation, AllocationResult


def greedy(problem: Problem) -> AllocationResult:
    remaining = {a.id: a.market_value for a in problem.assets}
    allocations: list[Allocation] = []

    for r in sorted(problem.requirements, key=lambda r: -r.amount):
        candidates = []
        for a in problem.assets:
            h = r.haircut_for(a)
            if h is not None:
                candidates.append((a.cost_bps / (1 - h), a.id, a, h))
        candidates.sort(key=lambda t: (t[0], t[1]))

        # Post-haircut headroom left under each limit.
        limit_room = [lim.max_share * r.amount for lim in r.concentration_limits]
        issuer_room: dict[str, float] = {}
        need = r.amount

        for _, _, a, h in candidates:
            if need <= 1e-9:
                break
            avail_cv = remaining[a.id] * (1 - h)
            take_cv = min(need, avail_cv)
            for i, lim in enumerate(r.concentration_limits):
                if lim.applies_to(a):
                    take_cv = min(take_cv, limit_room[i])
            if r.max_share_per_issuer is not None and a.issuer is not None:
                room = issuer_room.setdefault(a.issuer, r.max_share_per_issuer * r.amount)
                take_cv = min(take_cv, room)
            if take_cv <= 1e-9:
                continue

            mv = take_cv / (1 - h)
            remaining[a.id] -= mv
            need -= take_cv
            for i, lim in enumerate(r.concentration_limits):
                if lim.applies_to(a):
                    limit_room[i] -= take_cv
            if r.max_share_per_issuer is not None and a.issuer is not None:
                issuer_room[a.issuer] -= take_cv
            allocations.append(
                Allocation(
                    asset_id=a.id,
                    requirement_id=r.id,
                    market_value=mv,
                    haircut=h,
                    annual_cost=mv * a.cost_bps / 1e4,
                )
            )

    result = AllocationResult(method="greedy", allocations=allocations)
    if result.shortfalls(problem):
        result.status = "shortfall"
    return result
