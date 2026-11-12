"""CORS: only the production domain may read the API cross-origin.

main.py reads CORS_ORIGINS at import time, so each test sets the env and
reloads the module, then reloads it again on teardown so later tests get
the default app back.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

# The value set on the VPS in the ski-tracker-api systemd drop-in.
PROD_ORIGINS = "https://firstchair.live,https://www.firstchair.live"


@pytest.fixture
def prod_client(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", PROD_ORIGINS)
    import main
    importlib.reload(main)
    yield TestClient(main.app)
    monkeypatch.undo()
    importlib.reload(main)


def preflight(client, origin):
    return client.options(
        "/",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )


@pytest.mark.parametrize("origin", ["https://firstchair.live", "https://www.firstchair.live"])
def test_domain_origin_allowed(prod_client, origin):
    r = prod_client.get("/", headers={"Origin": origin})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin

    r = preflight(prod_client, origin)
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin


@pytest.mark.parametrize("origin", [
    "https://evil.example",
    "http://firstchair.live",          # plain http is not the site
    "https://firstchair.live.evil.example",
    "http://localhost:5173",           # dev default is off in production
])
def test_other_origin_refused(prod_client, origin):
    r = prod_client.get("/", headers={"Origin": origin})
    assert "access-control-allow-origin" not in r.headers

    r = preflight(prod_client, origin)
    assert r.status_code == 400
    assert r.text == "Disallowed CORS origin"
    assert "access-control-allow-origin" not in r.headers


def test_write_methods_refused_for_domain(prod_client):
    r = prod_client.options(
        "/",
        headers={"Origin": "https://firstchair.live", "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 400


@pytest.mark.parametrize("origin", [
    "https://firstchair.live", "https://www.firstchair.live",
    "https://evil.example", "http://localhost:5173", "null",
])
def test_no_credentials_header_for_any_origin(prod_client, origin):
    """No cookies or auth exist to share, so CORS never says credentials are allowed.
    The allowed origins above still get Allow-Origin."""
    for r in (prod_client.get("/", headers={"Origin": origin}), preflight(prod_client, origin)):
        assert "access-control-allow-credentials" not in r.headers
