"""poller/poll_weather.py: a malformed SNOTEL reading is skipped, never inserted.
One such row used to make /weather/* return 500
until someone edited the database.

Every run also writes data/stamp-weather.json, saying when it ran and how the snow source
answered, so /health can tell an upstream outage from a dead poller. No test here reaches the
network: requests.get is replaced for every test, and an unplanned call fails it.

poll_weather imports config, which loads .env; a stub config stands in for it, so
this test process never reads a real key."""
import importlib
import json
import sqlite3
import stat
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

import main
from tests import seeded

POLLER = Path(__file__).resolve().parents[2] / "poller"


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "traffic.db"
    conn = sqlite3.connect(path)
    conn.executescript(seeded.SCHEMA)
    conn.close()
    return path


STATION = {"id": "snotel-791", "name": "SNOTEL 791 - Stevens Pass", "triplet": "791:WA:SNTL",
           "elevation": 3940, "type": "base"}


class Upstream:
    """Stands in for requests.get: answers from `self.answer`, counts the calls."""

    def __init__(self):
        self.calls = 0
        self.answer = AssertionError("an unplanned request.get: no test may reach USDA")

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


class Response:
    def __init__(self, status_code, body=None, bad_json=False):
        self.status_code = status_code
        self.body = body
        self.bad_json = bad_json

    def json(self):
        if self.bad_json:
            raise requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)
        return self.body


# The shape of a real AWDB answer, cut to one element
SNOTEL_OK = [{"stationTriplet": "791:WA:SNTL", "data": [
    {"stationElement": {"elementCode": "SNWD"},
     "values": [{"date": "2026-11-20 21:00", "value": 40.0},
                {"date": "2026-11-20 22:00", "value": 41.0}]}]}]


@pytest.fixture
def upstream():
    return Upstream()


@pytest.fixture
def poller(db, upstream, monkeypatch):
    stub = types.SimpleNamespace(DB_PATH=db, AWDB_API_URL="http://test.invalid",
                                 WEATHER_STATIONS=[STATION])
    monkeypatch.setitem(sys.modules, "config", stub)
    monkeypatch.syspath_prepend(str(POLLER))
    monkeypatch.delitem(sys.modules, "poll_weather", raising=False)
    module = importlib.import_module("poll_weather")
    monkeypatch.setattr(module.requests, "get", upstream.get)
    return module


def reading(**kw):
    r = {"station_id": "snotel-791", "station_name": "SNOTEL 791 - Stevens Pass",
         "station_elevation": 3940, "station_type": "base", "temperature_f": 28.4,
         "snow_depth_inches": 41.0, "total_precip_inches": 20.3, "measured_at": "2026-11-10 22:00"}
    r.update(kw)
    return r


GOOD = [
    reading(),
    reading(temperature_f=None, total_precip_inches=None),  # 282 live rows look like this
    reading(snow_depth_inches=0, temperature_f=-3),
    reading(measured_at="2026-01-04"),  # date-only, as 3 live rows are
]

BAD = {
    "no values at all": reading(temperature_f=None, snow_depth_inches=None,
                                total_precip_inches=None, measured_at=None),
    "measured_at missing": reading(measured_at=None),
    "measured_at empty": reading(measured_at=""),
    "measured_at garbage": reading(measured_at="yesterday-ish"),
    "measured_at compact date": reading(measured_at="20261110"),  # SQLite would store an integer
    "measured_at compact date and time": reading(measured_at="20261110T2200"),
    "measured_at impossible date": reading(measured_at="2026-13-45"),
    "measured_at not a string": reading(measured_at=20261110),
    "all values empty": reading(temperature_f=None, snow_depth_inches=None, total_precip_inches=None),
    "value is text": reading(snow_depth_inches="abc"),
    "value is empty text": reading(temperature_f=""),
    "value is numeric text": reading(total_precip_inches="20.3"),
    "value is bool": reading(snow_depth_inches=True),
    "value is NaN": reading(temperature_f=float("nan")),
    "value is inf": reading(snow_depth_inches=float("inf")),
}


def rows(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT measured_at, temperature_f, snow_depth_inches,"
                            " total_precip_inches FROM weather_data").fetchall()


@pytest.mark.parametrize("good", GOOD)
def test_good_reading_is_saved(poller, db, good):
    poller.save_to_database(good)
    assert rows(db) == [(good["measured_at"], good["temperature_f"],
                         good["snow_depth_inches"], good["total_precip_inches"])]


@pytest.mark.parametrize("bad", BAD.values(), ids=BAD.keys())
def test_malformed_reading_is_skipped(poller, db, bad):
    poller.save_to_database(bad)
    assert rows(db) == []


@pytest.mark.parametrize("bad", BAD.values(), ids=BAD.keys())
def test_weather_endpoints_survive_after_a_malformed_poll(poller, db, bad, monkeypatch):
    """End to end: a good poll, then the malformed one, then every weather endpoint."""
    poller.save_to_database(reading())
    poller.save_to_database(bad)
    monkeypatch.setattr(main, "DB_PATH", db)
    client = TestClient(main.app, raise_server_exceptions=False)
    for path in ["/weather/current", "/weather/history?hours=720", "/weather/snotel-791"]:
        r = client.get(path)
        assert r.status_code == 200, (path, r.text)
        assert len(r.json()) >= 1


# --- the per-run heartbeat stamp -----------------------------------------------------

def heartbeat(db):
    path = db.parent / "stamp-weather.json"
    stamp = json.loads(path.read_text())
    at = datetime.fromisoformat(stamp.pop("at"))
    assert at.tzinfo is not None
    assert abs(datetime.now(timezone.utc) - at) < timedelta(minutes=1)
    assert stat.S_IMODE(path.stat().st_mode) == 0o644  # the API user reads it through "other"
    return stamp


def test_a_good_run_writes_the_heartbeat(poller, db, upstream):
    upstream.answer = Response(200, SNOTEL_OK)
    poller.main()
    assert upstream.calls == 1
    assert heartbeat(db) == {"status": 200, "error": None, "saved": 1}
    assert rows(db) == [("2026-11-20 22:00", None, 41.0, None)]


@pytest.mark.parametrize("status", [500, 502, 403])
def test_an_http_error_writes_the_heartbeat(poller, db, upstream, status):
    upstream.answer = Response(status)
    poller.main()
    assert upstream.calls == 1  # one request a run, no retry
    assert heartbeat(db) == {"status": status, "error": None, "saved": 0}
    assert rows(db) == []


@pytest.mark.parametrize("exc", [requests.exceptions.ReadTimeout("read timed out"),
                                 requests.exceptions.ConnectTimeout("connect timed out"),
                                 requests.exceptions.ConnectionError("refused")])
def test_a_timeout_or_refused_connection_writes_the_heartbeat(poller, db, upstream, exc):
    upstream.answer = exc
    poller.main()
    assert upstream.calls == 1
    assert heartbeat(db) == {"status": None, "error": type(exc).__name__, "saved": 0}


def test_a_200_we_cannot_read_writes_the_heartbeat(poller, db, upstream):
    upstream.answer = Response(200, bad_json=True)
    poller.main()
    assert heartbeat(db) == {"status": 200, "error": "JSONDecodeError", "saved": 0}


def test_a_200_with_a_malformed_reading_says_nothing_saved(poller, db, upstream):
    upstream.answer = Response(200, [{"data": []}])
    poller.main()
    assert heartbeat(db) == {"status": 200, "error": None, "saved": 0}


def test_a_failed_db_write_still_writes_the_heartbeat_and_fails_the_run(poller, db, upstream):
    """The heartbeat must not paper over our own failure: it says the upstream answered and
    nothing was saved, and the run still exits with the traceback."""
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE weather_data")
    upstream.answer = Response(200, SNOTEL_OK)
    with pytest.raises(sqlite3.OperationalError):
        poller.main()
    assert heartbeat(db) == {"status": 200, "error": None, "saved": 0}


def test_a_heartbeat_write_failure_does_not_stop_the_poll(poller, db, upstream, monkeypatch):
    """The row matters more than the stamp: an unwritable stamp is printed, the row is saved."""
    (db.parent / "stamp-weather.json").mkdir()  # os.replace onto a directory fails
    upstream.answer = Response(200, SNOTEL_OK)
    poller.main()
    assert len(rows(db)) == 1


def test_the_temp_file_never_matches_the_backup_sweep(poller, db, upstream, monkeypatch):
    """The nightly sweep uploads traffic*.db* from data/: the stamp and its temp must not match."""
    seen = []
    real_replace = poller.os.replace

    def spy(src, dst):
        seen.append((Path(src).name, Path(dst).name))
        return real_replace(src, dst)
    monkeypatch.setattr(poller.os, "replace", spy)
    upstream.answer = Response(502)
    poller.main()
    assert len(seen) == 1
    for name in seen[0]:
        assert not Path(name).match("traffic*.db*")
    assert seen[0][1] == "stamp-weather.json"
    assert [p.name for p in db.parent.iterdir() if "stamp" in p.name] == ["stamp-weather.json"]


def test_an_outage_seen_by_the_poller_is_degraded_in_health(poller, db, upstream, monkeypatch):
    """End to end: the poller's own stamp, read by the API. Stale weather plus a 502 run is
    degraded, not failing; the same stale weather after a 200 run that saved nothing is red."""
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO weather_data (station_id, measured_at, recorded_at)"
                     " VALUES ('snotel-791', '2026-11-16 19:00', ?)",
                     ((datetime.now() - timedelta(hours=5)).isoformat(),))
    monkeypatch.setattr(main, "DB_PATH", db)
    client = TestClient(main.app)

    upstream.answer = Response(502)
    poller.main()
    body = client.get("/internal/health").json()
    assert "weather" in body["degraded"]
    assert "weather" not in body["failing"] and "weather_poller" not in body["failing"]

    upstream.answer = Response(200, [{"data": []}])
    poller.main()
    body = client.get("/internal/health").json()
    assert "weather" in body["failing"]
