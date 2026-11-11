"""/segments and /weather/history: same JSON as the old per-timestamp loop, in a
bounded number of SQL statements (comb-0xqi.20, roast finding B1).

The reference is tests/old_impl.py, a verbatim copy of the pre-S2 endpoints.
Both apps read the same seeded database, and the response bytes must be equal."""
import hashlib
import re
from datetime import datetime
from pathlib import Path

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


@pytest.mark.parametrize("url", SEGMENT_QUERIES + WEATHER_QUERIES)
def test_same_bytes_as_the_old_loop(seeded_db, new, old, url):
    want = old.get(url)
    got = new.get(url)
    assert want.status_code == 200, want.text
    assert got.status_code == 200, got.text
    assert got.content == want.content


def test_fixture_exercises_the_edges(seeded_db, new):
    """The golden comparison is only as good as the data: check the fixture reaches the
    cases where a regrouped query could drift from the old one."""
    segs = new.get("/segments/redmond-stevens-eb?hours=720").json()
    assert len(segs) == 1000  # the default limit truncates the 30-day view
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
