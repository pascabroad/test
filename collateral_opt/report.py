"""Plain-text reporting."""

from __future__ import annotations

from .models import Problem
from .result import AllocationResult


def _money(v: float) -> str:
    return f"{v:,.0f}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(w) if i == 0 else h.rjust(w) for i, (h, w) in enumerate(zip(headers, widths)))
    out = [line, "-" * len(line)]
    for r in rows:
        out.append("  ".join(c.ljust(w) if i == 0 else c.rjust(w) for i, (c, w) in enumerate(zip(r, widths))))
    return "\n".join(out)


def render(problem: Problem, result: AllocationResult, baseline: AllocationResult | None = None) -> str:
    ccy = problem.base_currency
    parts = [f"Collateral allocation ({result.method}, amounts in {ccy})", ""]

    for r in problem.requirements:
        allocs = [a for a in result.allocations if a.requirement_id == r.id]
        cov = result.coverage(r.id)
        parts.append(f"{r.id}  required {_money(r.amount)}  covered {_money(cov)}  ({cov / r.amount:.1%})" if r.amount else r.id)
        rows = [
            [a.asset_id, _money(a.market_value), f"{a.haircut:.1%}", _money(a.collateral_value), _money(a.annual_cost)]
            for a in sorted(allocs, key=lambda a: -a.market_value)
        ]
        parts.append(_table(["asset", "market value", "haircut", "collateral value", "annual cost"], rows))
        parts.append("")

    parts.append("Inventory utilisation")
    rows = []
    for a in problem.assets:
        used = result.used(a.id)
        rows.append([a.id, a.asset_class, _money(a.market_value), _money(used), _money(a.market_value - used), f"{a.cost_bps:g}"])
    parts.append(_table(["asset", "class", "available", "pledged", "free", "cost bps"], rows))
    parts.append("")

    parts.append(f"Total annual cost: {_money(result.total_cost)} {ccy}")
    shortfalls = result.shortfalls(problem)
    if shortfalls:
        for rid, gap in shortfalls.items():
            parts.append(f"SHORTFALL {rid}: {_money(gap)} {ccy} uncovered")
    else:
        parts.append("All requirements fully covered.")

    if baseline is not None:
        parts.append("")
        parts.append(f"Greedy cheapest-to-deliver cost: {_money(baseline.total_cost)} {ccy}"
                     + (f" (shortfall on {', '.join(baseline.shortfalls(problem))})" if baseline.shortfalls(problem) else ""))
        saving = baseline.total_cost - result.total_cost
        if baseline.total_cost > 0:
            parts.append(f"Optimiser saving: {_money(saving)} {ccy} per year ({saving / baseline.total_cost:.1%})")
    return "\n".join(parts)
