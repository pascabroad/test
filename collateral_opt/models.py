"""Domain model: collateral inventory, margin requirements and eligibility schedules."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Long-term rating scale, best to worst. Used for minimum-rating eligibility checks.
RATING_SCALE = [
    "AAA", "AA+", "AA", "AA-", "A+", "A", "A-",
    "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-",
    "CCC+", "CCC", "CCC-", "CC", "C", "D",
]
_RATING_RANK = {r: i for i, r in enumerate(RATING_SCALE)}


def rating_at_least(rating: str | None, minimum: str | None) -> bool:
    """True if `rating` is at or above `minimum`. Unrated assets fail any minimum."""
    if minimum is None:
        return True
    if rating is None or rating not in _RATING_RANK:
        return False
    return _RATING_RANK[rating] <= _RATING_RANK[minimum]


@dataclass
class Asset:
    """A position in the collateral inventory.

    `market_value` is expressed in the base (reporting) currency.
    `cost_bps` is the annual opportunity cost of pledging the asset, e.g. lost
    repo/securities-lending income or funding value.
    """

    id: str
    asset_class: str
    market_value: float
    currency: str
    cost_bps: float = 0.0
    issuer: str | None = None
    rating: str | None = None

    def attr(self, name: str) -> Any:
        return getattr(self, name, None)


@dataclass
class EligibilityRule:
    """One line of an eligibility schedule. The first matching rule wins."""

    asset_class: str
    haircut: float
    min_rating: str | None = None
    currencies: list[str] | None = None

    def matches(self, asset: Asset) -> bool:
        if asset.asset_class != self.asset_class:
            return False
        if self.currencies is not None and asset.currency not in self.currencies:
            return False
        return rating_at_least(asset.rating, self.min_rating)


@dataclass
class ConcentrationLimit:
    """Caps the post-haircut value of matching assets at `max_share` of the requirement.

    `match` is a dict of asset attributes, e.g. {"asset_class": "EQUITY"}.
    """

    match: dict[str, Any]
    max_share: float

    def applies_to(self, asset: Asset) -> bool:
        return all(asset.attr(k) == v for k, v in self.match.items())


@dataclass
class Requirement:
    """A margin call / collateral obligation to a counterparty, CCP or triparty agent."""

    id: str
    amount: float
    currency: str
    eligibility: list[EligibilityRule]
    concentration_limits: list[ConcentrationLimit] = field(default_factory=list)
    max_share_per_issuer: float | None = None
    fx_haircut: float = 0.08

    def haircut_for(self, asset: Asset) -> float | None:
        """Total haircut for posting `asset`, or None if it is ineligible."""
        for rule in self.eligibility:
            if rule.matches(asset):
                h = rule.haircut
                if asset.currency != self.currency:
                    h += self.fx_haircut
                return h if h < 1.0 else None
        return None


@dataclass
class Problem:
    assets: list[Asset]
    requirements: list[Requirement]
    base_currency: str = "USD"

    def validate(self) -> None:
        ids = [a.id for a in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate asset ids in inventory")
        rids = [r.id for r in self.requirements]
        if len(rids) != len(set(rids)):
            raise ValueError("Duplicate requirement ids")
        for a in self.assets:
            if a.market_value < 0:
                raise ValueError(f"Asset {a.id}: market_value must be non-negative")
        for r in self.requirements:
            if r.amount < 0:
                raise ValueError(f"Requirement {r.id}: amount must be non-negative")
            for rule in r.eligibility:
                if not 0 <= rule.haircut < 1:
                    raise ValueError(f"Requirement {r.id}: haircut must be in [0, 1)")
                if rule.min_rating is not None and rule.min_rating not in _RATING_RANK:
                    raise ValueError(f"Requirement {r.id}: unknown rating {rule.min_rating!r}")
            for lim in r.concentration_limits:
                if not 0 <= lim.max_share <= 1:
                    raise ValueError(f"Requirement {r.id}: max_share must be in [0, 1]")


def problem_from_dict(data: dict[str, Any]) -> Problem:
    assets = [Asset(**a) for a in data["assets"]]
    requirements = []
    for r in data["requirements"]:
        r = dict(r)
        r["eligibility"] = [EligibilityRule(**e) for e in r["eligibility"]]
        r["concentration_limits"] = [
            ConcentrationLimit(**c) for c in r.get("concentration_limits", [])
        ]
        requirements.append(Requirement(**r))
    problem = Problem(
        assets=assets,
        requirements=requirements,
        base_currency=data.get("base_currency", "USD"),
    )
    problem.validate()
    return problem


def load_problem(path: str | Path) -> Problem:
    with open(path) as f:
        return problem_from_dict(json.load(f))
