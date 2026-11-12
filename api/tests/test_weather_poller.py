"""poller/poll_weather.py: a malformed SNOTEL reading is skipped, never inserted.
One such row used to make /weather/* return 500
until someone edited the database.

poll_weather imports config, which loads .env; a stub config stands in for it, so
this test process never reads a real key."""
import importlib
import sqlite3
import sys
import types
from pathlib import Path

import pytest
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


@pytest.fixture
def poller(db, monkeypatch):
    stub = types.SimpleNamespace(DB_PATH=db, AWDB_API_URL="http://test.invalid", WEATHER_STATIONS=[])
    monkeypatch.setitem(sys.modules, "config", stub)
    monkeypatch.syspath_prepend(str(POLLER))
    monkeypatch.delitem(sys.modules, "poll_weather", raising=False)
    return importlib.import_module("poll_weather")


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
