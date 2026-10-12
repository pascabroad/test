"""Local web dashboard: `python -m collateral_opt.web` then open http://localhost:8000.

Uses only the standard library HTTP server. Endpoints:

* GET  /             the dashboard page
* GET  /api/sample   the bundled sample portfolio
* POST /api/optimise a portfolio JSON body -> optimised and greedy allocations
"""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from .baseline import greedy
from .models import problem_from_dict
from .optimizer import optimise

MAX_BODY = 5 * 1024 * 1024
SAMPLE_PATH = Path(__file__).resolve().parent.parent / "examples" / "sample_portfolio.json"


def _static(name: str) -> bytes:
    return resources.files("collateral_opt").joinpath("static", name).read_bytes()


def _sample() -> dict | None:
    try:
        with open(SAMPLE_PATH) as f:
            return json.load(f)
    except OSError:
        return None


def run_optimisation(data: dict) -> dict:
    problem = problem_from_dict(data)
    result = optimise(problem)
    baseline = greedy(problem)
    return {
        "base_currency": problem.base_currency,
        "optimised": result.to_dict(problem),
        "greedy": baseline.to_dict(problem),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "collateral-opt"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send(HTTPStatus.OK, _static("index.html"), "text/html; charset=utf-8")
        elif self.path == "/api/sample":
            sample = _sample()
            if sample is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "sample portfolio not found"})
            else:
                self._json(HTTPStatus.OK, sample)
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/optimise":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request too large"})
            return
        try:
            data = json.loads(self.rfile.read(length))
            self._json(HTTPStatus.OK, run_optimisation(data))
        except (ValueError, KeyError, TypeError) as e:
            self._json(HTTPStatus.BAD_REQUEST, {"error": f"Invalid portfolio: {e}"})
        except RuntimeError as e:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(e)})

    def log_message(self, fmt: str, *args) -> None:
        pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the collateral optimiser dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Collateral optimiser dashboard on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
