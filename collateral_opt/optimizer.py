"""Linear-programming collateral optimiser.

Decision variable x[a, r] is the market value of asset `a` pledged to requirement
`r` (only created for eligible pairs). The model minimises total annual
opportunity cost subject to:

* inventory:      sum_r x[a, r]                       <= market_value[a]
* coverage:       sum_a (1 - h[a, r]) x[a, r] + s[r]  >= amount[r]
* concentration:  sum_{a in group} (1 - h) x[a, r]    <= max_share * amount[r]

s[r] is a shortfall slack carrying a large penalty, so an infeasible book still
returns the best achievable allocation together with the uncovered amounts.

The model is solved lexicographically: first for minimum cost, then, holding
cost at that optimum, for minimum total market value pledged. The second stage
stops zero-cost assets being over-posted beyond what the requirement needs.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import csr_matrix, lil_matrix, vstack

from .models import Problem
from .result import Allocation, AllocationResult

# Penalty per unit of shortfall, as an annual rate. Far above any realistic
# funding cost so the solver only leaves a requirement short when it must.
SHORTFALL_PENALTY = 10.0
# Relative slack on the stage-one optimum allowed in the stage-two solve.
COST_TOLERANCE = 1e-9


def optimise(problem: Problem) -> AllocationResult:
    assets, reqs = problem.assets, problem.requirements

    # Enumerate eligible (asset, requirement) pairs.
    pairs: list[tuple[int, int, float]] = []
    for ai, a in enumerate(assets):
        for ri, r in enumerate(reqs):
            h = r.haircut_for(a)
            if h is not None and a.market_value > 0:
                pairs.append((ai, ri, h))

    n_x, n_s = len(pairs), len(reqs)
    n = n_x + n_s

    # Scale monetary amounts to O(1) for numerical stability.
    scale = max([a.market_value for a in assets] + [r.amount for r in reqs] + [1.0])

    c = np.zeros(n)
    for k, (ai, _, _) in enumerate(pairs):
        c[k] = assets[ai].cost_bps / 1e4
    c[n_x:] = SHORTFALL_PENALTY

    rows: list[tuple[dict[int, float], float]] = []

    by_asset: dict[int, list[int]] = defaultdict(list)
    by_req: dict[int, list[int]] = defaultdict(list)
    for k, (ai, ri, _) in enumerate(pairs):
        by_asset[ai].append(k)
        by_req[ri].append(k)

    for ai, ks in by_asset.items():
        rows.append(({k: 1.0 for k in ks}, assets[ai].market_value / scale))

    for ri, r in enumerate(reqs):
        coeffs = {k: -(1 - pairs[k][2]) for k in by_req[ri]}
        coeffs[n_x + ri] = -1.0
        rows.append((coeffs, -r.amount / scale))

        for lim in r.concentration_limits:
            ks = [k for k in by_req[ri] if lim.applies_to(assets[pairs[k][0]])]
            if ks:
                rows.append(({k: 1 - pairs[k][2] for k in ks}, lim.max_share * r.amount / scale))

        if r.max_share_per_issuer is not None:
            by_issuer: dict[str, list[int]] = defaultdict(list)
            for k in by_req[ri]:
                issuer = assets[pairs[k][0]].issuer
                if issuer is not None:
                    by_issuer[issuer].append(k)
            for ks in by_issuer.values():
                rows.append(
                    ({k: 1 - pairs[k][2] for k in ks}, r.max_share_per_issuer * r.amount / scale)
                )

    A = lil_matrix((len(rows), n))
    b = np.zeros(len(rows))
    for i, (coeffs, rhs) in enumerate(rows):
        for k, v in coeffs.items():
            A[i, k] = v
        b[i] = rhs

    bounds = [(0, assets[ai].market_value / scale) for ai, _, _ in pairs]
    bounds += [(0, r.amount / scale) for r in reqs]

    A = A.tocsr()
    res = linprog(c, A_ub=A, b_ub=b, bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"Solver failed: {res.message}")

    # Stage two: minimise total pledged market value without increasing cost.
    c2 = np.zeros(n)
    c2[:n_x] = 1.0
    A2 = vstack([A, csr_matrix(c)])
    b2 = np.append(b, res.fun * (1 + COST_TOLERANCE) + COST_TOLERANCE)
    res2 = linprog(c2, A_ub=A2, b_ub=b2, bounds=bounds, method="highs")
    if res2.success:
        res = res2

    x = res.x * scale
    allocations = []
    for k, (ai, ri, h) in enumerate(pairs):
        mv = float(x[k])
        if mv > 1e-6 * scale:
            a = assets[ai]
            allocations.append(
                Allocation(
                    asset_id=a.id,
                    requirement_id=reqs[ri].id,
                    market_value=mv,
                    haircut=h,
                    annual_cost=mv * a.cost_bps / 1e4,
                )
            )

    result = AllocationResult(method="optimised", allocations=allocations)
    if result.shortfalls(problem):
        result.status = "shortfall"
    return result
