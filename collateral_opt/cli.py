"""Command-line entry point: `python -m collateral_opt input.json`."""

from __future__ import annotations

import argparse
import json
import sys

from .baseline import greedy
from .models import load_problem
from .optimizer import optimise
from .report import render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Optimise collateral allocation across margin requirements.")
    parser.add_argument("input", help="JSON file describing inventory and requirements")
    parser.add_argument("--json", metavar="PATH", help="also write the allocation as JSON to PATH ('-' for stdout)")
    parser.add_argument("--no-baseline", action="store_true", help="skip the greedy benchmark comparison")
    args = parser.parse_args(argv)

    try:
        problem = load_problem(args.input)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"Error reading {args.input}: {e}", file=sys.stderr)
        return 2

    result = optimise(problem)
    baseline = None if args.no_baseline else greedy(problem)

    if args.json == "-":
        json.dump(result.to_dict(problem), sys.stdout, indent=2)
        print()
    else:
        print(render(problem, result, baseline))
        if args.json:
            with open(args.json, "w") as f:
                json.dump(result.to_dict(problem), f, indent=2)

    return 1 if result.status == "shortfall" else 0


if __name__ == "__main__":
    sys.exit(main())
