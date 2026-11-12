"""A seeded 31-day database shaped like the live one, for the golden and
statement-budget tests.

Schema and indexes are poller/init_db.py's. The old /weather/history picks its 4 pm
baseline row with ORDER BY ... LIMIT 1, and SQLite breaks ties in index order, so the
index has to be here for the fixture to pin the real tie rule.

Shapes copied from the live DB (2026-11-11, read-only): segment rows every 30 min with
26-char isoformat recorded_at; SNOTEL measured_at as 'YYYY-MM-DD HH:MM' polled 4 times
an hour, a few date-only rows, rows with NULL temperature and precip, duplicate
measured_at rows whose values differ. Added on purpose: hours with no row, days whose
16:00 row is missing (15:00 and 17:00 tie), days with no baseline row at all, segments
inserted out of segment_order, a second active route and an archived one interleaved,
and some measured_at with seconds, which land exactly on the baseline window bounds.
"""
import random
import sqlite3
from datetime import datetime, timedelta

SCHEMA = """
CREATE TABLE travel_times (
    id INTEGER PRIMARY KEY AUTOINCREMENT, route_id TEXT NOT NULL, route_name TEXT,
    current_min INTEGER, average_min INTEGER,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP, wsdot_updated_at DATETIME);
CREATE INDEX idx_travel_times_route_recorded ON travel_times(route_id, recorded_at);
CREATE TABLE route_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, route_id TEXT NOT NULL,
    segment_order INTEGER NOT NULL, segment_from TEXT NOT NULL, segment_to TEXT NOT NULL,
    duration_min INTEGER, recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX idx_route_segments_route_recorded ON route_segments(route_id, recorded_at);
CREATE TABLE weather_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT, station_id TEXT NOT NULL, station_name TEXT,
    station_elevation INTEGER, station_type TEXT, temperature_f REAL,
    snow_depth_inches REAL, snow_accum_inches REAL, rain_accum_inches REAL,
    snow_density REAL, total_precip_inches REAL, accumulation_period TEXT,
    measured_at DATETIME, recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX idx_weather_station_measured ON weather_data(station_id, measured_at);
"""

ROUTE_SEGMENTS = {
    "redmond-stevens-eb": ["Redmond", "Monroe", "Sultan", "Skykomish", "Stevens Pass"],
    "stevens-redmond-wb": ["Stevens Pass", "Skykomish", "Sultan", "Monroe", "Redmond"],
    "redmond-mtbaker-eb": ["Redmond", "Everett", "Burlington", "Glacier", "Mt Baker"],  # archived
}
STATION = ("snotel-791", "SNOTEL 791 - Stevens Pass", 3940, "base")


def build(path, now: datetime, seed: int = 1, days: int = 31):
    """Write the fixture to `path`. `now` is the naive local time the API will see."""
    rng = random.Random(seed)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    # Segments and travel times: one poll every 30 min, routes interleaved in one stream
    rows, travel = [], []
    t = now - timedelta(days=days)
    while t <= now:
        stamp = (t + timedelta(microseconds=rng.randrange(1, 10**6))).isoformat()
        for route_id, stops in ROUTE_SEGMENTS.items():
            if route_id == "redmond-mtbaker-eb" and t > now - timedelta(days=20):
                continue  # archived: history only
            if rng.random() < 0.02:
                continue  # a missed poll for this route
            travel.append((route_id, route_id, rng.randrange(80, 200), 95, stamp))
            segs = [(route_id, i, stops[i], stops[i + 1],
                     None if rng.random() < 0.03 else rng.randrange(5, 60), stamp)
                    for i in range(len(stops) - 1)]
            if rng.random() < 0.3:
                rng.shuffle(segs)  # inserted out of segment_order
            rows.extend(segs)
        t += timedelta(minutes=30)
    conn.executemany("INSERT INTO route_segments (route_id, segment_order, segment_from,"
                     " segment_to, duration_min, recorded_at) VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.executemany("INSERT INTO travel_times (route_id, route_name, current_min, average_min,"
                     " recorded_at) VALUES (?, ?, ?, ?, ?)", travel)

    # Weather: SNOTEL hours (station local time, 8 h behind the box), each polled 4 times
    no_baseline_days = {rng.randrange(days) for _ in range(3)}
    no_four_pm_days = {rng.randrange(days) for _ in range(4)}
    depth, precip = 40.0, 20.0
    wx = []
    start = (now - timedelta(days=days, hours=8)).replace(minute=0, second=0, microsecond=0)
    for h in range(days * 24):
        m = start + timedelta(hours=h)
        day = (m - start).days
        if m.hour in (15, 16, 17) and day in no_baseline_days:
            continue
        if m.hour == 16 and day in no_four_pm_days:
            continue
        if rng.random() < 0.04:
            continue  # SNOTEL skipped the hour
        depth = max(0.0, depth + rng.choice([0, 0, 0, 0.5, 1.0, 2.0, -0.5]))
        precip += rng.choice([0, 0, 0.1, 0.2])
        measured = m.strftime("%Y-%m-%d %H:%M")
        if rng.random() < 0.15:
            # with seconds: '... 17:00:00' sits exactly on a baseline window's end
            # (included) and '... 15:00:00' on its start, where '... 15:00' falls outside
            measured = m.strftime("%Y-%m-%d %H:%M:%S")
        elif rng.random() < 0.01:
            measured = m.strftime("%Y-%m-%d")  # date-only, as 3 live rows are
        temp = None if rng.random() < 0.01 else round(rng.uniform(10, 40), 1)
        pr = None if temp is None else round(precip, 1)
        sd = None if rng.random() < 0.01 else depth
        for poll in range(4):
            if poll and rng.random() < 0.05:
                sd = None if sd is None else sd + 0.5  # a revised value on a later poll
            rec = m + timedelta(hours=8, minutes=15 * poll + rng.randrange(0, 3),
                                microseconds=rng.randrange(1, 10**6))
            if rec > now:
                break
            wx.append((*STATION, temp, sd, pr, measured, rec.isoformat()))
    head = wx[: len(wx) // 10]
    rng.shuffle(head)
    wx[: len(head)] = head  # the oldest tenth inserted out of order
    conn.executemany("INSERT INTO weather_data (station_id, station_name, station_elevation,"
                     " station_type, temperature_f, snow_depth_inches, total_precip_inches,"
                     " measured_at, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", wx)
    conn.commit()
    conn.close()
