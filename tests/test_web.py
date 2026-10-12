import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from collateral_opt.web import Handler

from .test_optimizer import SAMPLE


@pytest.fixture(scope="module")
def base_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _open(req):
    # Bypass any proxy configured in the environment for loopback requests.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=10)


def _post(url, body: bytes):
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with _open(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_serves_dashboard(base_url):
    with _open(base_url + "/") as r:
        assert r.status == 200
        assert b"Collateral optimiser" in r.read()


def test_sample_endpoint(base_url):
    with _open(base_url + "/api/sample") as r:
        assert json.loads(r.read())["requirements"]


def test_optimise_endpoint(base_url):
    status, body = _post(base_url + "/api/optimise", SAMPLE.read_bytes())
    assert status == 200
    assert body["optimised"]["status"] == "optimal"
    assert body["optimised"]["total_annual_cost"] <= body["greedy"]["total_annual_cost"]


@pytest.mark.parametrize("payload", [b"not json", b'{"assets": []}'])
def test_optimise_rejects_bad_input(base_url, payload):
    status, body = _post(base_url + "/api/optimise", payload)
    assert status == 400
    assert "error" in body
