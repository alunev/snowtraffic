"""API hygiene: the Maps key stays out of the API process, queries are capped,
and the database is opened read-only."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
FAKE_KEY = "fake-key-for-test"

PROBE = (
    "import os, sys, json; import {module}; "
    "print(json.dumps({{'config_loaded': 'config' in sys.modules, "
    "'key_in_env': os.environ.get('GOOGLE_MAPS_API_KEY')}}))"
)


@pytest.fixture
def app_tree_with_env(tmp_path):
    """A copy of api/ and poller/ under a root that holds a .env with a fake key,
    the way /opt/snowtraffic is laid out on the VPS."""
    (tmp_path / "api").mkdir()
    shutil.copy(REPO / "api" / "main.py", tmp_path / "api" / "main.py")
    shutil.copytree(REPO / "poller", tmp_path / "poller",
                    ignore=shutil.ignore_patterns("__pycache__", "venv"))
    (tmp_path / ".env").write_text(f"GOOGLE_MAPS_API_KEY={FAKE_KEY}\n")
    return tmp_path


def run_probe(tree, cwd, module):
    env = {k: v for k, v in os.environ.items() if k != "GOOGLE_MAPS_API_KEY"}
    out = subprocess.run(
        [sys.executable, "-c", PROBE.format(module=module)],
        cwd=tree / cwd, env=env, capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_tripwire_config_import_loads_the_key(app_tree_with_env):
    """Positive control for the fixture: importing config DOES pull the fake
    key into the environment, so the next test can see the bug if it returns."""
    result = run_probe(app_tree_with_env, "poller", "config")
    assert result == {"config_loaded": True, "key_in_env": FAKE_KEY}


def test_import_main_leaves_config_and_key_out(app_tree_with_env):
    result = run_probe(app_tree_with_env, "api", "main")
    # Both at once, so a failure shows whether config, the key, or both leaked.
    assert result == {"config_loaded": False, "key_in_env": None}


def test_config_still_reexports_routes(monkeypatch):
    """The pollers import ROUTES/ARCHIVED_ROUTES from config; keep that working."""
    monkeypatch.syspath_prepend(str(REPO / "poller"))
    import config
    import routes
    assert config.ROUTES is routes.ROUTES
    assert config.ARCHIVED_ROUTES is routes.ARCHIVED_ROUTES


# --- query caps and read-only database ---------------------------------------

@pytest.fixture
def full_db(tmp_path):
    """A database with all three tables the capped endpoints read."""
    path = tmp_path / "traffic.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE travel_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT, route_id TEXT NOT NULL,
            route_name TEXT, current_min INTEGER, average_min INTEGER,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP, wsdot_updated_at DATETIME);
        CREATE TABLE route_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, route_id TEXT NOT NULL,
            segment_order INTEGER NOT NULL, segment_from TEXT NOT NULL,
            segment_to TEXT NOT NULL, duration_min INTEGER,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE weather_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT, station_id TEXT NOT NULL,
            station_name TEXT, station_elevation INTEGER, station_type TEXT,
            temperature_f REAL, snow_depth_inches REAL, snow_accum_inches REAL,
            rain_accum_inches REAL, snow_density REAL, total_precip_inches REAL,
            accumulation_period TEXT, measured_at DATETIME,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    """)
    now = datetime.now()
    conn.execute(
        "INSERT INTO travel_times (route_id, route_name, current_min, average_min, recorded_at)"
        " VALUES ('redmond-stevens-eb', 'Redmond to Stevens Pass', 90, 85, ?)",
        (now.isoformat(),))
    conn.execute(
        "INSERT INTO route_segments (route_id, segment_order, segment_from, segment_to,"
        " duration_min, recorded_at) VALUES ('redmond-stevens-eb', 0, 'Redmond', 'Monroe', 30, ?)",
        (now.isoformat(),))
    conn.execute(
        "INSERT INTO weather_data (station_id, station_name, station_type, temperature_f,"
        " snow_depth_inches, total_precip_inches, measured_at, recorded_at)"
        " VALUES ('snotel-791', 'SNOTEL 791', 'base', 30.0, 40.0, 20.0, ?, datetime('now'))",
        (now.strftime('%Y-%m-%d %H:%M:%S'),))
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def full_client(full_db, monkeypatch):
    monkeypatch.setattr("main.DB_PATH", full_db)
    from main import app
    return TestClient(app)


CAPPED = [
    "/history/redmond-stevens-eb",
    "/segments/redmond-stevens-eb",
    "/weather/history",
]


@pytest.mark.parametrize("path", CAPPED)
@pytest.mark.parametrize("query", ["limit=100000", "limit=5001", "limit=0",
                                   "hours=100000", "hours=721", "hours=0"])
def test_over_cap_query_refused(full_client, path, query):
    r = full_client.get(f"{path}?{query}")
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("path", CAPPED)
@pytest.mark.parametrize("query", ["", "limit=5000", "hours=720", "hours=720&limit=1"])
def test_at_cap_query_answered(full_client, path, query):
    r = full_client.get(f"{path}?{query}")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


def test_db_connection_string_is_read_only(full_db, monkeypatch):
    import main
    monkeypatch.setattr(main, "DB_PATH", full_db)
    calls = []
    real_connect = sqlite3.connect

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(main.sqlite3, "connect", spy)
    main.get_db_connection().close()
    (target,), kwargs = calls[0]
    assert "mode=ro" in str(target)
    assert kwargs.get("uri") is True


def test_db_write_through_api_connection_fails(full_db, monkeypatch):
    import main
    monkeypatch.setattr(main, "DB_PATH", full_db)
    conn = main.get_db_connection()
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("DELETE FROM travel_times")
    conn.close()
    assert sqlite3.connect(full_db).execute("SELECT COUNT(*) FROM travel_times").fetchone() == (1,)
