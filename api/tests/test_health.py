"""GET /internal/health: one row per moving part. Every stale case below is a positive
control: it makes one defect present on top of the all-fresh fixture and must
turn the endpoint red, while the all-fresh fixture must stay green.

GET /health is the public twin: the same verdict with no detail, exactly
{"status":"ok"} (200) or {"status":"fail"} (503) (comb-0xqi.20)."""
import json
import sqlite3
from collections import namedtuple
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import main
from routes import ROUTES, ARCHIVED_ROUTES

# The exact substring his GCP uptime check matches on. Changing the body so this
# moves breaks the external check: update the check's content match with it.
OK_MARKER = '"status":"ok"'

ACTIVE = [r["id"] for r in ROUTES if r["id"] not in ARCHIVED_ROUTES]
DiskUsage = namedtuple("DiskUsage", "total used free")


def naive_ago(**kw):
    """A poller-style timestamp: naive datetime.now().isoformat()."""
    return (datetime.now() - timedelta(**kw)).isoformat()


def utc_stamp_ago(**kw):
    """A backup-stamp-style timestamp: UTC with a Z suffix."""
    return (datetime.now(timezone.utc) - timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Box:
    """A fake /opt/snowtraffic/data: traffic.db, backups/ stamps, and disk usage."""

    def __init__(self, tmp_path, monkeypatch):
        self.db = tmp_path / "traffic.db"
        self.backups = tmp_path / "backups"
        self.backups.mkdir()
        conn = sqlite3.connect(self.db)
        conn.executescript("""
            CREATE TABLE travel_times (
                id INTEGER PRIMARY KEY AUTOINCREMENT, route_id TEXT NOT NULL,
                route_name TEXT, current_min INTEGER, average_min INTEGER,
                recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP, wsdot_updated_at DATETIME);
            CREATE TABLE weather_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT, station_id TEXT NOT NULL,
                station_name TEXT, measured_at DATETIME,
                recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP);
        """)
        conn.close()
        self.disk_pct = 23
        monkeypatch.setattr(main, "DB_PATH", self.db)
        monkeypatch.setattr(main, "BACKUPS_DIR", self.backups)
        monkeypatch.setattr(main.shutil, "disk_usage",
                            lambda path: DiskUsage(100, self.disk_pct, 100 - self.disk_pct))
        self.client = TestClient(main.app)

    def traffic(self, route_id, recorded_at):
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO travel_times (route_id, route_name, current_min, recorded_at)"
                         " VALUES (?, ?, 90, ?)", (route_id, route_id, recorded_at))

    def weather(self, recorded_at):
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO weather_data (station_id, measured_at, recorded_at)"
                         " VALUES ('snotel-791', ?, ?)", (recorded_at, recorded_at))

    def stamp(self, name, text):
        (self.backups / name).write_text(text)

    def snapshot(self, at, check="ok"):
        self.stamp("stamp-snapshot.json", json.dumps(
            {"at": at, "file": "x.db", "integrity_check": check, "bytes": 1}))

    def offbox(self, at):
        self.stamp("stamp-offbox.json", json.dumps(
            {"at": at, "key": "s3://b/x.db", "md5": "m", "etag": "m", "etag_match": True}))

    def all_fresh(self):
        for route_id in ACTIVE:
            # an old row first: the check must read the newest one
            self.traffic(route_id, naive_ago(days=3))
            self.traffic(route_id, naive_ago(minutes=5))
        self.weather(naive_ago(days=3))
        self.weather(naive_ago(minutes=5))
        self.snapshot(utc_stamp_ago(hours=2))
        self.offbox(utc_stamp_ago(hours=2))
        return self

    def get(self):
        """The detail, with the public answer for the same state riding along as r.public."""
        r = self.client.get("/internal/health")
        r.public = self.client.get("/health")
        return r, r.json()


@pytest.fixture
def box(tmp_path, monkeypatch):
    return Box(tmp_path, monkeypatch)


def assert_red(r, body, *rows):
    assert r.status_code == 503
    assert body["status"] == "fail"
    assert body["failing"] == list(rows)
    assert OK_MARKER not in r.text
    # the public twin agrees, and says nothing more
    assert (r.public.status_code, r.public.content) == (503, b'{"status":"fail"}')


def test_active_routes_come_from_the_route_list():
    """Today the two Stevens routes; derived from routes.py, so a re-enabled route is checked too."""
    assert ACTIVE == ["redmond-stevens-eb", "stevens-redmond-wb"]


def test_all_fresh_is_green(box):
    r, body = box.all_fresh().get()
    assert r.status_code == 200, body
    assert body["status"] == "ok"
    assert body["failing"] == []
    assert OK_MARKER in r.text
    assert set(body["traffic_age_min"]) == set(ACTIVE)
    assert all(age == 5 for age in body["traffic_age_min"].values())
    assert body["weather_age_min"] == 5
    assert body["disk_pct"] == 23
    assert body["backup_age_h"] == pytest.approx(2, abs=0.1)
    assert body["backup_check"] == "ok"
    assert body["offbox_age_h"] == pytest.approx(2, abs=0.1)


def test_public_health_is_terse_when_green(box):
    r, _ = box.all_fresh().get()
    assert (r.public.status_code, r.public.content) == (200, b'{"status":"ok"}')
    assert OK_MARKER.encode() in r.public.content
    assert r.public.headers["content-type"] == "application/json"


def test_public_health_is_terse_when_red(box):
    """Forced stale: weather 2 h old and the DB error text present in the detail,
    while the public body stays exactly the verdict."""
    box.all_fresh()
    with sqlite3.connect(box.db) as conn:
        conn.execute("DELETE FROM weather_data")
    box.weather(naive_ago(hours=2))
    r, body = box.get()
    assert_red(r, body, "weather")
    box.db.unlink()
    r, body = box.get()
    assert "Database not found" in body["db_error"]
    assert (r.public.status_code, r.public.content) == (503, b'{"status":"fail"}')


def test_stale_traffic_is_per_route(box):
    box.all_fresh()
    # stevens-redmond-wb's newest row is 2 h old; the other route stays fresh,
    # so an overall MAX(recorded_at) would wrongly call this healthy
    with sqlite3.connect(box.db) as conn:
        conn.execute("DELETE FROM travel_times WHERE route_id = 'stevens-redmond-wb'")
    box.traffic("stevens-redmond-wb", naive_ago(minutes=120))
    r, body = box.get()
    assert_red(r, body, "traffic:stevens-redmond-wb")
    assert body["traffic_age_min"] == {"redmond-stevens-eb": 5, "stevens-redmond-wb": 120}


def test_active_route_with_no_rows_is_red(box):
    box.all_fresh()
    with sqlite3.connect(box.db) as conn:
        conn.execute("DELETE FROM travel_times WHERE route_id = 'redmond-stevens-eb'")
    r, body = box.get()
    assert_red(r, body, "traffic:redmond-stevens-eb")
    assert body["traffic_age_min"]["redmond-stevens-eb"] is None


def test_archived_route_staleness_is_ignored(box):
    box.all_fresh()
    box.traffic(ARCHIVED_ROUTES[0], naive_ago(days=200))
    r, body = box.get()
    assert r.status_code == 200, body
    assert ARCHIVED_ROUTES[0] not in body["traffic_age_min"]


@pytest.mark.parametrize("minutes, healthy", [(55, True), (75, False)])
def test_stale_weather(box, minutes, healthy):
    box.all_fresh()
    with sqlite3.connect(box.db) as conn:
        conn.execute("DELETE FROM weather_data")
    box.weather(naive_ago(minutes=minutes))
    r, body = box.get()
    assert body["weather_age_min"] == minutes
    if healthy:
        assert r.status_code == 200, body
    else:
        assert_red(r, body, "weather")


def test_no_weather_rows_is_red(box):
    box.all_fresh()
    with sqlite3.connect(box.db) as conn:
        conn.execute("DELETE FROM weather_data")
    r, body = box.get()
    assert_red(r, body, "weather")
    assert body["weather_age_min"] is None


@pytest.mark.parametrize("pct, healthy", [(79, True), (85, False)])
def test_disk(box, pct, healthy):
    box.all_fresh().disk_pct = pct
    r, body = box.get()
    assert body["disk_pct"] == pct
    if healthy:
        assert r.status_code == 200, body
    else:
        assert_red(r, body, "disk")


@pytest.mark.parametrize("hours, healthy", [(20, True), (30, False)])
def test_backup_age(box, hours, healthy):
    box.all_fresh().snapshot(utc_stamp_ago(hours=hours))
    r, body = box.get()
    assert body["backup_age_h"] == pytest.approx(hours, abs=0.1)
    if healthy:
        assert r.status_code == 200, body
    else:
        assert_red(r, body, "backup_age")


def test_backup_integrity_not_ok_is_red(box):
    box.all_fresh().snapshot(utc_stamp_ago(hours=2), check="error: database disk image is malformed")
    r, body = box.get()
    assert_red(r, body, "backup_check")
    assert body["backup_check"] == "error: database disk image is malformed"


@pytest.mark.parametrize("text, why", [
    (None, "stamp-snapshot.json missing"),
    ("{not json", "stamp-snapshot.json unreadable: JSONDecodeError"),
    ('{"integrity_check": "ok"}', "stamp-snapshot.json unreadable: KeyError"),
    ('{"at": "yesterday", "integrity_check": "ok"}', "stamp-snapshot.json unreadable: ValueError"),
    ('{"at": "2026-11-07T02:10:01", "integrity_check": "ok"}',
     "stamp-snapshot.json unreadable: at has no timezone"),
])
def test_bad_backup_stamp_is_red(box, text, why):
    box.all_fresh()
    if text is None:
        (box.backups / "stamp-snapshot.json").unlink()
    else:
        box.stamp("stamp-snapshot.json", text)
    r, body = box.get()
    assert_red(r, body, "backup_stamp")
    assert body["backup_check"] == why
    assert body["backup_age_h"] is None


@pytest.mark.parametrize("hours, healthy", [(30, True), (40, False)])
def test_offbox_age(box, hours, healthy):
    box.all_fresh().offbox(utc_stamp_ago(hours=hours))
    r, body = box.get()
    assert body["offbox_age_h"] == pytest.approx(hours, abs=0.1)
    if healthy:
        assert r.status_code == 200, body
    else:
        assert_red(r, body, "offbox_age")


def test_missing_offbox_stamp_is_red(box):
    box.all_fresh()
    (box.backups / "stamp-offbox.json").unlink()
    r, body = box.get()
    assert_red(r, body, "offbox_stamp")
    assert body["offbox_age_h"] is None
    assert body["offbox_error"] == "stamp-offbox.json missing"


def test_unreadable_db_is_a_named_failure_not_a_500(box):
    """A read-only open that fails (hot journal, missing table) is reported as `db`."""
    box.all_fresh()
    with sqlite3.connect(box.db) as conn:
        conn.execute("DROP TABLE weather_data")
    r, body = box.get()
    assert_red(r, body, "db")
    assert "weather_data" in body["db_error"]


def test_missing_db_is_a_named_failure(box):
    box.all_fresh()
    box.db.unlink()
    r, body = box.get()
    assert_red(r, body, "db")
    assert "Database not found" in body["db_error"]


def test_every_failure_at_once_lists_every_row(box):
    """Nothing written at all, disk full: every row is named, none masks another."""
    box.disk_pct = 95
    r, body = box.get()
    assert_red(r, body, *[f"traffic:{rid}" for rid in ACTIVE],
               "weather", "disk", "backup_stamp", "offbox_stamp")
