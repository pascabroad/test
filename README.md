# collateral-opt

A collateral optimisation tool. It allocates a firm's collateral inventory across its margin
requirements (CCP initial margin, bilateral CSAs, triparty repo, …) at the lowest total
opportunity cost while respecting each counterparty's eligibility schedule, haircuts and
concentration limits.

## How it works

The allocation is solved as a linear program (SciPy / HiGHS). The decision variable `x[a, r]` is
the market value of asset `a` pledged to requirement `r`, and the solver:

- **minimises** Σ `cost_bps[a]` × `x[a, r]`, the annual opportunity cost of what is pledged
- **subject to**
  - *inventory*: an asset can't be pledged beyond its market value
  - *coverage*: Σ (1 − haircut) × `x[a, r]` ≥ requirement amount
  - *eligibility*: only assets that match an eligibility rule (asset class, minimum rating, currency) can be used
  - *FX haircut*: an extra haircut applies when the asset currency differs from the requirement currency
  - *concentration limits*: post-haircut value of matching assets ≤ `max_share` × requirement, optionally per issuer

If the inventory can't cover everything, the tool still returns the best possible allocation and
reports the shortfall. It doesn't fail.

Each run is also compared with a **greedy cheapest-to-deliver** heuristic, similar to filling
requirements one by one by hand, so you can see the saving from optimising globally.

## Usage

```bash
pip install -e ".[dev]"
collateral-opt examples/sample_portfolio.json            # text report
collateral-opt examples/sample_portfolio.json --json out.json
collateral-opt examples/sample_portfolio.json --json -   # JSON to stdout
pytest
```

The exit code is `0` when every requirement is covered, `1` on a shortfall and `2` on bad input.

## Web dashboard

```bash
collateral-opt-web            # or: python -m collateral_opt.web --port 8000
```

Open http://127.0.0.1:8000. The dashboard loads the sample portfolio. From there you can:

- see the annual cost, the saving against the greedy approach and the coverage status
- view stacked bars of the collateral posted per requirement by asset class (hover for the assets)
  and how much of each inventory position is pledged
- edit market values, costs or requirement amounts inline; it re-optimises automatically
- upload a full portfolio as JSON, or replace just the inventory with a CSV that has the columns
  `id, asset_class, currency, market_value[, cost_bps, issuer, rating]`
- download the allocation as CSV or the edited portfolio as JSON

It uses only the Python standard library HTTP server, so it needs no extra dependencies. It is
meant to run locally and has no authentication.

## Input format

```jsonc
{
  "base_currency": "USD",
  "assets": [
    {"id": "UST-10Y", "asset_class": "GOVT", "currency": "USD",
     "market_value": 35000000,      // in base currency
     "cost_bps": 20,                // annual opportunity cost of pledging
     "issuer": "US Treasury", "rating": "AA+"}
  ],
  "requirements": [
    {"id": "CSA-BANK-A", "amount": 45000000, "currency": "USD",
     "fx_haircut": 0.08,                       // default 0.08
     "max_share_per_issuer": 0.4,              // optional
     "eligibility": [                          // first matching rule wins
       {"asset_class": "GOVT", "haircut": 0.03, "min_rating": "A-", "currencies": ["USD", "EUR"]}
     ],
     "concentration_limits": [
       {"match": {"asset_class": "CORP"}, "max_share": 0.25}
     ]}
  ]
}
```

## Current limitations

- Positions are treated as divisible (no lot sizes or minimum transfer amounts).
- Concentration limits are measured against the requirement amount, not the total collateral posted.
- Market values must already be converted into the base currency.
- It is a single-period optimisation, so it ignores substitution costs and the existing allocation.
