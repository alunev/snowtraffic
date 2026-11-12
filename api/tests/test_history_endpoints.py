"""/segments and /weather/history: same JSON as the old per-timestamp loop, in a
bounded number of SQL statements.

The reference is tests/old_impl.py, a verbatim copy of the old per-timestamp endpoints.
Both apps read the same seeded database. Two behaviour changes since,
so the golden comparison asks the old loop for what the new code should now return:
- /segments defaults to limit=5000 (was 1000), so the old loop is asked with limit=5000.
- /weather/history's window is honest: hours=24 is the last 24 h of recorded_at, where the
  old text comparison let in every row of the cutoff's date. The old loop is asked for a
  wider window and its rows are cut at the honest cutoff, then the limit applied."""
import hashlib
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

import main
from tests import old_impl
from tests import seeded

NOW = datetime.now().replace(microsecond=0)
STATEMENT_BUDGET = 3


class Frozen(datetime):
    """datetime with now() pinned, so the old and new cutoffs are the same instant."""

    @classmethod
    def now(cls, tz=None):
        return NOW


@pytest.fixture(params=[1, 2, 3], ids=lambda s: f"seed{s}")
def seeded_db(request, tmp_path, monkeypatch):
    path = tmp_path / "traffic.db"
    seeded.build(path, NOW, seed=request.param)
    monkeypatch.setattr(main, "DB_PATH", path)
    monkeypatch.setattr(main, "datetime", Frozen)
    monkeypatch.setattr(old_impl, "datetime", Frozen)
    return path


@pytest.fixture
def new():
    return TestClient(main.app)


@pytest.fixture
def old():
    return TestClient(old_impl.app)


def test_reference_is_verbatim():
    """old_impl.py's two blocks hash to api/main.py lines 418-476 and 580-697 at 2905495."""
    text = (Path(__file__).parent / "old_impl.py").read_text()
    blocks = re.findall(r"# --- BEGIN VERBATIM [^\n]*\n(.*?)# --- END VERBATIM ---", text, re.S)
    assert [hashlib.sha256(b.encode()).hexdigest() for b in blocks] == [
        "94a4105cc14f02d59e218b413f3c8893cd3ed3c3653651b59e7030ed2cac7ff3",
        "ba7514604c092d70024e88111363ebe8cca9aa1ab08df6cdcf90370d2415fc17",
    ]


SEGMENT_QUERIES = [
    f"/segments/{route}?{q}"
    for route in ["redmond-stevens-eb", "stevens-redmond-wb"]
    for q in ["", "hours=1", "hours=24", "hours=168", "hours=720",
              "hours=720&limit=5000", "hours=720&limit=1000", "hours=720&limit=7",
              "hours=168&limit=1", "limit=3"]
]

WEATHER_QUERIES = [
    f"/weather/history?{q}"
    for q in ["", "hours=1", "hours=24", "hours=168", "hours=720", "hours=720&limit=5000",
              "hours=720&limit=50", "hours=24&limit=1", "station_id=snotel-791&hours=720",
              "station_id=nope&hours=720"]
]


@pytest.mark.parametrize("url", SEGMENT_QUERIES)
def test_segments_same_bytes_as_the_old_loop(seeded_db, new, old, url):
    """Byte-equal to the old loop, which is asked with limit=5000 where the URL has none."""
    url_old = url if "limit=" in url else url + ("" if url.endswith("?") else "&") + "limit=5000"
    want = old.get(url_old)
    got = new.get(url)
    assert want.status_code == 200, want.text
    assert got.status_code == 200, got.text
    assert got.content == want.content


def honest_from_old(old, url):
    """What /weather/history should answer for `url`: the old loop's rows over a window 48 h
    wider (a superset whatever the box's timezone), cut at the honest cutoff on recorded_at,
    then the limit. Each row is a measured_at group, and MAX(recorded_at) decides whether the
    group has a row inside the window, so the cut is exact."""
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    hours, limit = int(q.pop("hours", 24)), int(q.pop("limit", 5000))
    q.update(hours=str(hours + 48), limit="5000")
    want = old.get("/weather/history?" + "&".join(f"{k}={v}" for k, v in q.items()))
    assert want.status_code == 200, want.text
    rows = want.json()
    assert len(rows) < 5000  # the wide ask was not itself truncated
    cutoff = NOW - timedelta(hours=hours)
    return [r for r in rows if datetime.fromisoformat(r["recorded_at"]) >= cutoff][:limit]


@pytest.mark.parametrize("url", WEATHER_QUERIES)
def test_weather_same_rows_as_the_old_loop_in_the_honest_window(seeded_db, new, old, url):
    got = new.get(url)
    assert got.status_code == 200, got.text
    assert got.json() == honest_from_old(old, url)


def test_segments_default_is_the_whole_30_day_window(seeded_db, new):
    """The UI asks /segments/<route>?hours=720 with no limit (App.jsx): every poll in the 30
    days must come back. Red on the old default limit=1000 (1440 polls at */30)."""
    cutoff = (NOW - timedelta(hours=720)).isoformat()
    conn = sqlite3.connect(seeded_db)
    polls = [r[0] for r in conn.execute(
        "SELECT DISTINCT recorded_at FROM route_segments WHERE route_id = ? ORDER BY 1 DESC",
        ("redmond-stevens-eb",)) if r[0] >= cutoff]
    conn.close()
    assert len(polls) > 1000  # the fixture is past the old default
    got = [r["recorded_at"] for r in new.get("/segments/redmond-stevens-eb?hours=720").json()]
    assert got == polls


def window_errors(client, db_path, hours):
    """Compare /weather/history?hours=N with the rows whose recorded_at, read as a datetime,
    is within N hours of NOW. Returns what differs (empty when the window is honest)."""
    cutoff = NOW - timedelta(hours=hours)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT measured_at, recorded_at FROM weather_data"
                        " WHERE station_id = 'snotel-791' AND measured_at IS NOT NULL").fetchall()
    conn.close()
    want = {m for m, rec in rows if datetime.fromisoformat(rec) >= cutoff}
    got = client.get(f"/weather/history?hours={hours}").json()
    errors = [f"{r['measured_at']} recorded {r['recorded_at']} is before the cutoff {cutoff}"
              for r in got if datetime.fromisoformat(r["recorded_at"]) < cutoff]
    missing = want - {r["measured_at"] for r in got}
    if missing:
        errors.append(f"{len(missing)} groups inside the window are missing")
    return errors


@pytest.fixture
def leak_row(seeded_db):
    """A row recorded one second before the 24 h cutoff, on the cutoff's own date: the old
    'T' vs ' ' text comparison lets it in, an honest window never does."""
    cutoff = NOW - timedelta(hours=24)
    rec = cutoff - timedelta(seconds=1)
    assert rec.date() == cutoff.date()  # else this fixture cannot plant the case
    conn = sqlite3.connect(seeded_db)
    conn.execute("INSERT INTO weather_data (station_id, station_name, station_elevation,"
                 " station_type, temperature_f, snow_depth_inches, total_precip_inches,"
                 " measured_at, recorded_at) VALUES (?, ?, ?, ?, 30.0, 40.0, 20.0, ?, ?)",
                 (*seeded.STATION, (rec - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:07"),
                  rec.isoformat()))
    conn.commit()
    conn.close()
    return seeded_db


@pytest.mark.parametrize("hours", [1, 24, 168, 720])
def test_weather_history_window_is_honest(leak_row, new, hours):
    assert window_errors(new, leak_row, hours) == []


def test_window_check_sees_the_old_comparison(leak_row, old):
    """Positive control: the same check on the old loop finds its window wrong. The old loop
    compares local recorded_at text with SQLite's UTC datetime('now', '-24 hours'). When that
    falls on or before the local cutoff's date, the 'T' vs ' ' comparison lets in the planted
    row from before the cutoff. When UTC is already on a later date (a box behind UTC, in the
    evening) it drops rows inside the window instead: a row planted one second after the
    cutoff shows that at any hour."""
    cutoff = NOW - timedelta(hours=24)
    inside = cutoff + timedelta(seconds=1)
    conn = sqlite3.connect(leak_row)
    conn.execute("INSERT INTO weather_data (station_id, station_name, station_elevation,"
                 " station_type, temperature_f, snow_depth_inches, total_precip_inches,"
                 " measured_at, recorded_at) VALUES (?, ?, ?, ?, 30.0, 40.0, 20.0, ?, ?)",
                 (*seeded.STATION, (inside - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:09"),
                  inside.isoformat()))
    conn.commit()
    utc_cutoff_date = conn.execute("SELECT date('now', '-24 hours')").fetchone()[0]
    conn.close()
    errors = window_errors(old, leak_row, 24)
    if utc_cutoff_date > cutoff.date().isoformat():
        assert any("inside the window are missing" in e for e in errors), errors
    else:
        assert any("before the cutoff" in e for e in errors), errors


def test_fixture_exercises_the_edges(seeded_db, new):
    """The golden comparison is only as good as the data: check the fixture reaches the
    cases where a regrouped query could drift from the old one."""
    segs = new.get("/segments/redmond-stevens-eb?hours=720").json()
    assert len(segs) > 1000  # past the old default limit
    assert any(s["duration_min"] is None for r in segs for s in r["segments"])
    hist = new.get("/weather/history?hours=720").json()
    accum = [r["snow_accum_inches"] for r in hist]
    assert None in accum and any(a for a in accum)  # some hours lack a baseline, most have one
    assert any(len(r["measured_at"]) == 10 for r in hist)  # a date-only row


# --- statement budget --------------------------------------------------------

def count_statements(client, url, monkeypatch):
    statements = []
    real = main.get_db_connection

    def traced():
        conn = real()
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(main, "get_db_connection", traced)
    r = client.get(url)
    assert r.status_code == 200, r.text
    assert len(r.json()) > 500  # a real max-size answer, not an empty one
    return statements


MAX_CAP = ["/segments/redmond-stevens-eb?hours=720&limit=5000",
           "/weather/history?hours=720&limit=5000"]


@pytest.mark.parametrize("url", MAX_CAP)
def test_max_cap_request_runs_at_most_three_statements(seeded_db, new, url, monkeypatch):
    statements = count_statements(new, url, monkeypatch)
    assert len(statements) <= STATEMENT_BUDGET, statements


@pytest.mark.parametrize("url", MAX_CAP)
def test_budget_counter_sees_the_old_loop(seeded_db, old, url, monkeypatch):
    """Positive control: the same counter on the old per-timestamp loop is far over budget."""
    statements = count_statements(old, url, monkeypatch)
    assert len(statements) > 500
