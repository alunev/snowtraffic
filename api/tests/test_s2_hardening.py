"""S2 hardening (comb-0xqi.20): hours capped at 720 with every UI request still valid,
docs off, no trailing-slash redirect, archived and unknown routes 404, and weather
rows with no measured_at no longer break /weather/*."""
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from tests import seeded
from routes import ROUTES, ARCHIVED_ROUTES

UI_SRC = Path(__file__).resolve().parents[2] / "ui" / "src"
ACTIVE = [r["id"] for r in ROUTES if r["id"] not in ARCHIVED_ROUTES]
HOURS_ENDPOINTS = ["/history/redmond-stevens-eb", "/segments/redmond-stevens-eb",
                   "/weather/history"]


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "traffic.db"
    seeded.build(path, datetime.now(), seed=7)
    monkeypatch.setattr(main, "DB_PATH", path)
    return path


@pytest.fixture
def client(db):
    # 500s come back as responses, so a crash is a status code, not a test error
    return TestClient(main.app, raise_server_exceptions=False, follow_redirects=False)


# --- hours cap and the UI's own requests --------------------------------------

@pytest.mark.parametrize("path", HOURS_ENDPOINTS)
def test_hours_cap_is_720(client, path):
    assert client.get(f"{path}?hours=720").status_code == 200
    assert client.get(f"{path}?hours=721").status_code == 422


def ui_requests():
    """Every API URL the UI builds, read from ui/src: each fetch(`${API_BASE_URL}...`)
    template, with ${hours} expanded to every setTimeRange(N) value and the route
    placeholder to every active route. An unknown placeholder fails the test."""
    files = sorted(UI_SRC.rglob("*.jsx")) + sorted(UI_SRC.rglob("*.js"))
    text = "".join(f.read_text() for f in files)
    templates = re.findall(r"fetch\(`\$\{API_BASE_URL\}([^`]*)`", text)
    ranges = sorted({int(n) for n in re.findall(r"setTimeRange\((\d+)\)", text)})
    urls = set()
    for t in templates:
        expanded = [t]
        for name in set(re.findall(r"\$\{(\w+)\}", t)):
            values = {"hours": ranges, "routeId": ACTIVE}.get(name)
            assert values, f"unknown placeholder ${{{name}}} in UI request {t}"
            expanded = [u.replace(f"${{{name}}}", str(v)) for u in expanded for v in values]
        urls.update(expanded)
    return templates, ranges, sorted(urls)


def test_ui_request_list():
    """The list quoted on the bead. A new UI request shows up here first."""
    templates, ranges, urls = ui_requests()
    assert sorted(templates) == ["/current", "/routes", "/segments/${routeId}?hours=${hours}",
                                 "/weather/current", "/weather/history?hours=${hours}"]
    assert ranges == [24, 168, 720]
    assert not any(u.split("?")[0].endswith("/") for u in urls)  # no trailing slash anywhere
    assert len(urls) == 3 + 2 * 3 + 3


@pytest.mark.parametrize("url", ui_requests()[2])
def test_every_ui_request_stays_valid(client, url):
    r = client.get(url)
    assert r.status_code == 200, r.text
    assert r.json()


# --- docs and redirects -------------------------------------------------------

@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"])
def test_docs_are_off(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/routes/", "/current/", "/weather/history/",
                                  "/current/redmond-stevens-eb/"])
def test_trailing_slash_is_not_redirected(client, path):
    r = client.get(path, headers={"Host": "evil.example"})
    assert r.status_code == 404
    assert "location" not in r.headers


# --- archived and unknown routes ----------------------------------------------

PER_ROUTE = ["/current/{}", "/history/{}?hours=720", "/segments/{}?hours=720"]


@pytest.mark.parametrize("route_id", ARCHIVED_ROUTES + ["nonexistent-route", "x" * 300])
@pytest.mark.parametrize("path", PER_ROUTE)
def test_archived_or_unknown_route_is_404(client, path, route_id):
    r = client.get(path.format(route_id))
    assert r.status_code == 404
    assert r.json() == {"detail": "Route not found"}


def test_fixture_holds_archived_rows(db):
    """Positive control for the test above: the archived route has data on the fixture,
    so a 404 there is the route check, not an empty table."""
    with sqlite3.connect(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM route_segments WHERE route_id = 'redmond-mtbaker-eb'"
                         " AND recorded_at >= datetime('now', '-720 hours')").fetchone()[0]
    assert "redmond-mtbaker-eb" in ARCHIVED_ROUTES and n > 100


@pytest.mark.parametrize("route_id", ACTIVE)
@pytest.mark.parametrize("path", PER_ROUTE)
def test_active_route_still_answers(client, path, route_id):
    r = client.get(path.format(route_id))
    assert r.status_code == 200, r.text
    assert r.json()


# --- weather rows with no measured_at ------------------------------------------

WEATHER = ["/weather/current", "/weather/history?hours=720", "/weather/snotel-791"]


@pytest.mark.parametrize("path", WEATHER)
def test_null_measured_at_row_is_ignored(db, client, path):
    clean = client.get(path)
    assert clean.status_code == 200
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO weather_data (station_id, station_name, station_type,"
                     " snow_depth_inches, measured_at, recorded_at)"
                     " VALUES ('snotel-791', 'x', 'base', 1.0, NULL, ?)",
                     (datetime.now().isoformat(),))
    r = client.get(path)
    assert r.status_code == 200, r.text
    assert r.content == clean.content
