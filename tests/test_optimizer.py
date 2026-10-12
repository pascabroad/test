from pathlib import Path

import pytest

from collateral_opt import (
    Asset,
    ConcentrationLimit,
    EligibilityRule,
    Problem,
    Requirement,
    greedy,
    load_problem,
    optimise,
    problem_from_dict,
)
from collateral_opt.cli import main

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample_portfolio.json"


def req(id="R", amount=100.0, currency="USD", rules=None, **kw):
    rules = rules or [EligibilityRule("GOVT", 0.0)]
    return Requirement(id=id, amount=amount, currency=currency, eligibility=rules, **kw)


def assert_feasible(problem, result, tol=1e-4):
    for a in problem.assets:
        assert result.used(a.id) <= a.market_value + tol
    for r in problem.requirements:
        for lim in r.concentration_limits:
            assets = {a.id: a for a in problem.assets}
            cv = sum(x.collateral_value for x in result.allocations
                     if x.requirement_id == r.id and lim.applies_to(assets[x.asset_id]))
            assert cv <= lim.max_share * r.amount + tol


def test_picks_cheapest_eligible_asset():
    p = Problem(
        assets=[Asset("A", "GOVT", 200, "USD", cost_bps=30), Asset("B", "GOVT", 200, "USD", cost_bps=10)],
        requirements=[req()],
    )
    res = optimise(p)
    assert res.used("B") == pytest.approx(100)
    assert res.used("A") == pytest.approx(0, abs=1e-6)
    assert res.total_cost == pytest.approx(100 * 10 / 1e4)


def test_haircut_grosses_up_market_value():
    p = Problem(assets=[Asset("A", "GOVT", 500, "USD")], requirements=[req(rules=[EligibilityRule("GOVT", 0.2)])])
    res = optimise(p)
    assert res.used("A") == pytest.approx(125)
    assert res.coverage("R") == pytest.approx(100)


def test_fx_haircut_applies_on_currency_mismatch():
    r = req(rules=[EligibilityRule("GOVT", 0.02)], fx_haircut=0.08)
    assert r.haircut_for(Asset("A", "GOVT", 1, "EUR")) == pytest.approx(0.10)
    assert r.haircut_for(Asset("B", "GOVT", 1, "USD")) == pytest.approx(0.02)


def test_eligibility_rating_and_currency_filters():
    r = req(rules=[EligibilityRule("GOVT", 0.0, min_rating="A-", currencies=["USD"])])
    assert r.haircut_for(Asset("ok", "GOVT", 1, "USD", rating="AA")) is not None
    assert r.haircut_for(Asset("low", "GOVT", 1, "USD", rating="BBB")) is None
    assert r.haircut_for(Asset("unrated", "GOVT", 1, "USD")) is None
    assert r.haircut_for(Asset("eur", "GOVT", 1, "EUR", rating="AAA")) is None
    assert r.haircut_for(Asset("eq", "EQUITY", 1, "USD")) is None


def test_concentration_limit_forces_diversification():
    p = Problem(
        assets=[Asset("EQ", "EQUITY", 1000, "USD", cost_bps=1), Asset("G", "GOVT", 1000, "USD", cost_bps=20)],
        requirements=[req(
            rules=[EligibilityRule("EQUITY", 0.0), EligibilityRule("GOVT", 0.0)],
            concentration_limits=[ConcentrationLimit({"asset_class": "EQUITY"}, 0.3)],
        )],
    )
    res = optimise(p)
    assert res.coverage("R") == pytest.approx(100)
    assert res.used("EQ") == pytest.approx(30)
    assert res.used("G") == pytest.approx(70)


def test_issuer_limit():
    p = Problem(
        assets=[
            Asset("X1", "GOVT", 1000, "USD", cost_bps=1, issuer="X"),
            Asset("X2", "GOVT", 1000, "USD", cost_bps=1, issuer="X"),
            Asset("Y", "GOVT", 1000, "USD", cost_bps=5, issuer="Y"),
        ],
        requirements=[req(max_share_per_issuer=0.6)],
    )
    res = optimise(p)
    assert res.used("X1") + res.used("X2") == pytest.approx(60)
    assert res.used("Y") == pytest.approx(40)


def test_shortfall_reported_when_inventory_insufficient():
    p = Problem(assets=[Asset("A", "GOVT", 60, "USD")], requirements=[req()])
    res = optimise(p)
    assert res.status == "shortfall"
    assert res.shortfalls(p) == {"R": pytest.approx(40)}
    assert res.used("A") == pytest.approx(60)


def test_optimiser_beats_greedy_under_contention():
    # Asset C is cheapest for both requirements. Greedy hands it to the larger
    # requirement R1, forcing R2 onto expensive cash. R1 has a near-equal alternative.
    p = Problem(
        assets=[
            Asset("C", "GOVT", 50, "USD", cost_bps=5),
            Asset("D", "CORP", 100, "USD", cost_bps=6),
            Asset("CASH", "CASH", 100, "USD", cost_bps=50),
        ],
        requirements=[
            req("R1", 80, rules=[EligibilityRule("GOVT", 0.0), EligibilityRule("CORP", 0.0)]),
            req("R2", 50, rules=[EligibilityRule("GOVT", 0.0), EligibilityRule("CASH", 0.0)]),
        ],
    )
    opt, base = optimise(p), greedy(p)
    assert not opt.shortfalls(p) and not base.shortfalls(p)
    assert opt.total_cost < base.total_cost
    assert opt.used("CASH") == pytest.approx(0, abs=1e-6)


def test_sample_portfolio():
    p = load_problem(SAMPLE)
    opt, base = optimise(p), greedy(p)
    assert opt.status == "optimal"
    assert_feasible(p, opt)
    assert_feasible(p, base)
    assert opt.total_cost <= base.total_cost + 1e-6
    for r in p.requirements:
        assert opt.coverage(r.id) == pytest.approx(r.amount, rel=1e-6)


@pytest.mark.parametrize("bad", [
    {"assets": [{"id": "A", "asset_class": "G", "currency": "USD", "market_value": -1}], "requirements": []},
    {"assets": [], "requirements": [{"id": "R", "amount": 1, "currency": "USD",
                                     "eligibility": [{"asset_class": "G", "haircut": 1.5}]}]},
    {"assets": [], "requirements": [{"id": "R", "amount": 1, "currency": "USD",
                                     "eligibility": [{"asset_class": "G", "haircut": 0.1, "min_rating": "XYZ"}]}]},
])
def test_validation_errors(bad):
    with pytest.raises(ValueError):
        problem_from_dict(bad)


def test_cli_runs_on_sample(capsys):
    assert main([str(SAMPLE)]) == 0
    out = capsys.readouterr().out
    assert "Total annual cost" in out
    assert "Optimiser saving" in out
