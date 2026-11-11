"""FastAPI backend for serving travel time data."""
from bisect import bisect_left, bisect_right
import calendar
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from pydantic import BaseModel

# Add poller to path to import the route lists. Import routes, never config:
# config loads .env, and the API process must not hold the Google Maps key.
sys.path.insert(0, str(Path(__file__).parent.parent / "poller"))
from routes import ROUTES, ARCHIVED_ROUTES

# Database path
DB_PATH = Path(__file__).parent.parent / "data" / "traffic.db"

# /health inputs. The stamps are written by /opt/backup-snowtraffic.sh (0644, readable by the API user).
BACKUPS_DIR = DB_PATH.parent / "backups"
DISK_PATH = "/"

# /health thresholds
TRAFFIC_MAX_AGE_MIN = 90   # two missed polls at */30
WEATHER_MAX_AGE_MIN = 60   # SNOTEL misses write no row, so 45 would fail on two hiccups
DISK_MAX_PCT = 80
BACKUP_MAX_AGE_H = 26      # nightly at 02:10 UTC
OFFBOX_MAX_AGE_H = 36      # the off-box stamp is only rewritten after a verified upload

# Query caps: 30 days (the UI's largest view) and 5000 rows per request
MAX_HOURS = 720
MAX_LIMIT = 5000

# Per-route endpoints answer only for these; archived and unknown ids are a 404
ACTIVE_ROUTE_IDS = {r["id"] for r in ROUTES if r["id"] not in ARCHIVED_ROUTES}

# No docs or schema in production, and no redirect built from the Host header
app = FastAPI(title="Snow Traffic API", version="1.0.0", docs_url=None, redoc_url=None,
              openapi_url=None, redirect_slashes=False)

# CORS Configuration
# For production, set CORS_ORIGINS environment variable to comma-separated list of allowed origins
# Example: CORS_ORIGINS=https://myapp.com,https://www.myapp.com
import os
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,  # no cookies or auth to share
    allow_methods=["GET"],  # Read-only API
    allow_headers=["*"],
)


# Models
class TravelTimeRecord(BaseModel):
    """Single travel time record."""
    id: int
    route_id: str
    route_name: str
    current_min: Optional[int]
    average_min: Optional[int]
    recorded_at: str
    wsdot_updated_at: Optional[str]


class CurrentStatus(BaseModel):
    """Current status for a route."""
    route_id: str
    route_name: str
    current_min: Optional[int]
    average_min: Optional[int]
    delta_min: Optional[int]
    delta_percent: Optional[float]
    last_updated: str
    status: str  # "open" or "closed"


class RouteInfo(BaseModel):
    """Information about a tracked route."""
    route_id: str
    route_name: str
    record_count: int
    first_recorded: str
    last_recorded: str


class SegmentRecord(BaseModel):
    """Single segment record."""
    segment_from: str
    segment_to: str
    duration_min: Optional[int]
    recorded_at: str


# Helper functions
def get_db_connection():
    """Get database connection."""
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail="Database not found. Run poller/init_db.py first."
        )
    # Read-only: the API never writes; the pollers own the database
    return sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True)


def require_active_route(route_id: str):
    """404 for an archived or unknown route id, before any query runs."""
    if route_id not in ACTIVE_ROUTE_IDS:
        raise HTTPException(status_code=404, detail="Route not found")


def row_to_dict(cursor, row):
    """Convert SQLite row to dictionary."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


# API Endpoints
@app.get("/")
def read_root():
    """Root endpoint."""
    return {
        "message": "Snow Traffic API",
        "endpoints": {
            "/routes": "List all tracked routes",
            "/current": "Get current status for all routes",
            "/current/{route_id}": "Get current status for specific route",
            "/history/{route_id}": "Get historical data for a route",
            "/segments/{route_id}": "Get segment-by-segment historical data for a route",
            "/health": "200 when pollers, disk and backups are fresh, else 503",
        }
    }


def _age_min(newest: Optional[str]) -> Optional[int]:
    """Minutes since a poller timestamp (naive datetime.now(), as the pollers write)."""
    if newest is None:
        return None
    return int((datetime.now() - datetime.fromisoformat(newest)).total_seconds() // 60)


def _read_stamp(name: str) -> dict:
    """A backup stamp as a dict with an aware `at`; raises ValueError on a bad stamp."""
    path = BACKUPS_DIR / name
    try:
        stamp = json.loads(path.read_text())
        at = datetime.fromisoformat(stamp["at"])
    except FileNotFoundError:
        raise ValueError(f"{name} missing")
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"{name} unreadable: {type(e).__name__}")
    if at.tzinfo is None:
        raise ValueError(f"{name} unreadable: at has no timezone")
    stamp["at"] = at
    return stamp


def _age_h(at: datetime) -> float:
    return round((datetime.now(timezone.utc) - at).total_seconds() / 3600, 1)


def check_health():
    """Freshness of every moving part: (failing rows, detail body)."""
    failing = []
    body = {}

    active_routes = [r["id"] for r in ROUTES if r["id"] not in ARCHIVED_ROUTES]
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            traffic = {}
            for route_id in active_routes:
                cursor.execute(
                    "SELECT MAX(recorded_at) FROM travel_times WHERE route_id = ?", (route_id,))
                age = _age_min(cursor.fetchone()[0])
                traffic[route_id] = age
                if age is None or age > TRAFFIC_MAX_AGE_MIN:
                    failing.append(f"traffic:{route_id}")
            body["traffic_age_min"] = traffic

            cursor.execute("SELECT MAX(recorded_at) FROM weather_data")
            weather_age = _age_min(cursor.fetchone()[0])
            body["weather_age_min"] = weather_age
            if weather_age is None or weather_age > WEATHER_MAX_AGE_MIN:
                failing.append("weather")
        finally:
            conn.close()
    except (sqlite3.Error, HTTPException, ValueError) as e:
        # e.g. a hot journal left by a crashed poller makes a read-only open fail
        body["db_error"] = str(getattr(e, "detail", e))
        failing.append("db")

    usage = shutil.disk_usage(DISK_PATH)
    disk_pct = round(100 * usage.used / (usage.used + usage.free), 1)  # df's Use%
    body["disk_pct"] = disk_pct
    if disk_pct > DISK_MAX_PCT:
        failing.append("disk")

    try:
        snapshot = _read_stamp("stamp-snapshot.json")
        body["backup_age_h"] = _age_h(snapshot["at"])
        body["backup_check"] = snapshot.get("integrity_check")
        if body["backup_age_h"] > BACKUP_MAX_AGE_H:
            failing.append("backup_age")
        if body["backup_check"] != "ok":
            failing.append("backup_check")
    except ValueError as e:
        body["backup_age_h"] = None
        body["backup_check"] = str(e)
        failing.append("backup_stamp")

    try:
        body["offbox_age_h"] = _age_h(_read_stamp("stamp-offbox.json")["at"])
        if body["offbox_age_h"] > OFFBOX_MAX_AGE_H:
            failing.append("offbox_age")
    except ValueError as e:
        body["offbox_age_h"] = None
        body["offbox_error"] = str(e)
        failing.append("offbox_stamp")

    return failing, body


@app.get("/health")
def get_health():
    """Public: exactly {"status":"ok"} (200) or {"status":"fail"} (503), no detail.
    His GCP uptime check matches the bytes "status":"ok"."""
    failing, _ = check_health()
    return JSONResponse(status_code=503 if failing else 200,
                        content={"status": "fail" if failing else "ok"})


@app.get("/internal/health")
def get_internal_health():
    """The same check with the detail: failing rows, ages, disk, db_error.
    Meant for 127.0.0.1 only; nginx refuses /api/internal/ (S3)."""
    failing, body = check_health()
    return JSONResponse(
        status_code=503 if failing else 200,
        content={"status": "fail" if failing else "ok", "failing": failing, **body},
    )


@app.get("/routes", response_model=List[RouteInfo])
def get_routes():
    """Get list of all tracked routes with basic stats (excluding archived)."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            route_id,
            route_name,
            COUNT(*) as record_count,
            MIN(recorded_at) as first_recorded,
            MAX(recorded_at) as last_recorded
        FROM travel_times
        GROUP BY route_id, route_name
        ORDER BY route_name
    """)

    routes = []
    for row in cursor.fetchall():
        # Skip archived routes
        if row[0] in ARCHIVED_ROUTES:
            continue
        routes.append(RouteInfo(
            route_id=row[0],
            route_name=row[1],
            record_count=row[2],
            first_recorded=row[3],
            last_recorded=row[4]
        ))

    conn.close()
    return routes


@app.get("/current", response_model=List[CurrentStatus])
def get_current_status():
    """Get current status for all routes (excluding archived)."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get most recent record for each route
    cursor.execute("""
        SELECT
            route_id,
            route_name,
            current_min,
            average_min,
            recorded_at,
            wsdot_updated_at
        FROM travel_times
        WHERE (route_id, recorded_at) IN (
            SELECT route_id, MAX(recorded_at)
            FROM travel_times
            GROUP BY route_id
        )
        ORDER BY route_name
    """)

    statuses = []
    for row in cursor.fetchall():
        # Skip archived routes
        if row[0] in ARCHIVED_ROUTES:
            continue

        current = row[2]
        average = row[3]

        # Determine if route is open or closed
        status = "open" if current is not None else "closed"

        delta_min = None
        delta_percent = None
        if current is not None and average is not None and average > 0:
            delta_min = current - average
            delta_percent = round((delta_min / average) * 100, 1)

        statuses.append(CurrentStatus(
            route_id=row[0],
            route_name=row[1],
            current_min=current,
            average_min=average,
            delta_min=delta_min,
            delta_percent=delta_percent,
            last_updated=row[4],
            status=status
        ))

    conn.close()
    return statuses


@app.get("/current/{route_id}", response_model=CurrentStatus)
def get_current_status_by_route(route_id: str):
    """Get current status for a specific route."""
    require_active_route(route_id)
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            route_id,
            route_name,
            current_min,
            average_min,
            recorded_at,
            wsdot_updated_at
        FROM travel_times
        WHERE route_id = ?
        ORDER BY recorded_at DESC
        LIMIT 1
    """, (route_id,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Route not found")

    current = row[2]
    average = row[3]

    # Determine if route is open or closed
    status = "open" if current is not None else "closed"

    delta_min = None
    delta_percent = None
    if current is not None and average is not None and average > 0:
        delta_min = current - average
        delta_percent = round((delta_min / average) * 100, 1)

    return CurrentStatus(
        route_id=row[0],
        route_name=row[1],
        current_min=current,
        average_min=average,
        delta_min=delta_min,
        delta_percent=delta_percent,
        last_updated=row[4],
        status=status
    )


@app.get("/history/{route_id}", response_model=List[TravelTimeRecord])
def get_history(
    route_id: str,
    hours: int = Query(24, ge=1, le=MAX_HOURS),
    limit: int = Query(1000, ge=1, le=MAX_LIMIT)
):
    """
    Get historical data for a route.

    Args:
        route_id: Route ID to query
        hours: Number of hours to look back (default: 24)
        limit: Maximum number of records to return (default: 1000)
    """
    require_active_route(route_id)
    conn = get_db_connection()
    cursor = conn.cursor()

    # Calculate cutoff time
    cutoff = datetime.now() - timedelta(hours=hours)

    cursor.execute("""
        SELECT
            id,
            route_id,
            route_name,
            current_min,
            average_min,
            recorded_at,
            wsdot_updated_at
        FROM travel_times
        WHERE route_id = ? AND recorded_at >= ?
        ORDER BY recorded_at DESC
        LIMIT ?
    """, (route_id, cutoff.isoformat(), limit))

    records = []
    for row in cursor.fetchall():
        records.append(TravelTimeRecord(
            id=row[0],
            route_id=row[1],
            route_name=row[2],
            current_min=row[3],
            average_min=row[4],
            recorded_at=row[5],
            wsdot_updated_at=row[6]
        ))

    conn.close()
    return records


@app.get("/segments/{route_id}")
def get_segments(
    route_id: str,
    hours: int = Query(24, ge=1, le=MAX_HOURS),
    limit: int = Query(MAX_LIMIT, ge=1, le=MAX_LIMIT)
):
    """
    Get segment-by-segment historical data for a route.

    Args:
        route_id: Route ID to query
        hours: Number of hours to look back (default: 24)
        limit: Maximum number of timestamps to return (default: 5000). The default is the cap,
            so the UI's 30-day view (1440 polls at */30) is whole; MAX_HOURS bounds the answer.

    Returns:
        List of records grouped by timestamp, each containing segments
    """
    require_active_route(route_id)
    conn = get_db_connection()
    cursor = conn.cursor()

    # Calculate cutoff time
    cutoff = datetime.now() - timedelta(hours=hours)

    # One query: every segment row at or after the oldest of the `limit` newest
    # timestamps (each such row belongs to one of them), grouped below.
    # Ties on segment_order keep insertion order, as the old per-timestamp loop did.
    cursor.execute("""
        SELECT recorded_at, segment_from, segment_to, duration_min
        FROM route_segments
        WHERE route_id = ? AND recorded_at >= (
            SELECT MIN(recorded_at) FROM (
                SELECT DISTINCT recorded_at
                FROM route_segments
                WHERE route_id = ? AND recorded_at >= ?
                ORDER BY recorded_at DESC
                LIMIT ?
            )
        )
        ORDER BY recorded_at DESC, segment_order, id
    """, (route_id, route_id, cutoff.isoformat(), limit))

    result = []
    for recorded_at, segment_from, segment_to, duration_min in cursor.fetchall():
        if not result or result[-1]["recorded_at"] != recorded_at:
            result.append({"recorded_at": recorded_at, "segments": []})
        result[-1]["segments"].append({
            "from": segment_from,
            "to": segment_to,
            "duration_min": duration_min
        })

    conn.close()
    return result


@app.get("/weather/current")
def get_current_weather():
    """
    Get latest weather data from all configured stations with on-the-fly accumulation calculation.

    Returns:
        List of weather records with current conditions and accumulation since 4pm
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get most recent weather record for each station (by measured_at to dedupe)
    cursor.execute("""
        SELECT
            station_id,
            station_name,
            station_elevation,
            station_type,
            temperature_f,
            snow_depth_inches,
            total_precip_inches,
            measured_at,
            MAX(recorded_at) as recorded_at
        FROM weather_data
        WHERE measured_at IS NOT NULL
        AND (station_id, measured_at) IN (
            SELECT station_id, MAX(measured_at)
            FROM weather_data
            GROUP BY station_id
        )
        GROUP BY station_id, measured_at
        ORDER BY station_type, station_elevation
    """)

    weather = []
    for row in cursor.fetchall():
        station_id = row[0]
        measured_at_str = row[7]
        snow_depth = row[5]
        total_precip = row[6]

        # Calculate 4pm baseline
        measured_at = datetime.fromisoformat(measured_at_str)
        if measured_at.hour < 16:
            baseline_time = measured_at.replace(hour=16, minute=0, second=0, microsecond=0) - timedelta(days=1)
        else:
            baseline_time = measured_at.replace(hour=16, minute=0, second=0, microsecond=0)

        baseline_start = (baseline_time - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        baseline_end = (baseline_time + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute("""
            SELECT snow_depth_inches, total_precip_inches
            FROM weather_data
            WHERE station_id = ?
            AND measured_at >= ?
            AND measured_at <= ?
            ORDER BY ABS(strftime('%s', measured_at) - strftime('%s', ?))
            LIMIT 1
        """, (station_id, baseline_start, baseline_end, baseline_time.strftime('%Y-%m-%d %H:%M:%S')))

        baseline = cursor.fetchone()

        # Calculate accumulations
        snow_accum = None
        rain_accum = None
        snow_density = None

        if baseline and snow_depth is not None and baseline[0] is not None:
            snow_accum = max(0, snow_depth - baseline[0])

            if total_precip is not None and baseline[1] is not None:
                total_precip_increase = max(0, total_precip - baseline[1])

                if snow_accum > 0:
                    snow_water_equiv = snow_accum / 10.0
                    rain_accum = max(0, total_precip_increase - snow_water_equiv)
                    snow_water_only = total_precip_increase - rain_accum
                    if snow_water_only > 0:
                        snow_density = snow_water_only / snow_accum
                else:
                    rain_accum = total_precip_increase

        weather.append({
            "station_id": row[0],
            "station_name": row[1],
            "station_elevation": row[2],
            "station_type": row[3],
            "temperature_f": row[4],
            "snow_depth_inches": row[5],
            "snow_accum_inches": snow_accum,
            "rain_accum_inches": rain_accum,
            "snow_density": snow_density,
            "total_precip_inches": row[6],
            "measured_at": row[7],
            "last_updated": row[8]
        })

    conn.close()
    return weather


@app.get("/weather/history")
def get_weather_history(
    station_id: str = "snotel-791",
    hours: int = Query(24, ge=1, le=MAX_HOURS),
    limit: int = Query(MAX_LIMIT, ge=1, le=MAX_LIMIT)
):
    """
    Get hourly weather history for charting with on-the-fly accumulation calculation.

    Args:
        station_id: Station ID to query (default: snotel-791)
        hours: Number of hours to look back (default: 24)
        limit: Maximum number of hourly records to return (default: 5000)

    Returns:
        List of hourly weather records with calculated accumulations since 4pm
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # The cutoff is built in Python in the pollers' format (datetime.now().isoformat(), with a
    # 'T'), as /segments does. SQLite's datetime('now') has a space, which sorts before 'T', so
    # comparing against it let in every row of the cutoff's date: up to 48 h for hours=24.
    cutoff = datetime.now() - timedelta(hours=hours)

    # Get raw weather data for the requested time period, grouped by measured_at to dedupe
    cursor.execute("""
        SELECT
            station_id,
            station_name,
            station_type,
            temperature_f,
            snow_depth_inches,
            total_precip_inches,
            measured_at,
            MAX(recorded_at) as recorded_at
        FROM weather_data
        WHERE station_id = ?
        AND measured_at IS NOT NULL
        AND recorded_at >= ?
        GROUP BY station_id, measured_at
        ORDER BY measured_at ASC
        LIMIT ?
    """, (station_id, cutoff.isoformat(), limit))

    raw_data = cursor.fetchall()

    # Each row's 4pm baseline window, then ONE query for every candidate row in them
    windows = []
    for row in raw_data:
        measured_at_str = row[6]

        # Parse measured_at to determine 4pm baseline time
        measured_at = datetime.fromisoformat(measured_at_str)

        # Determine cutoff time (4pm on the day before measured_at if measured_at is before 4pm,
        # otherwise 4pm on the same day as measured_at)
        if measured_at.hour < 16:
            # Before 4pm: use 4pm yesterday as baseline
            baseline_time = measured_at.replace(hour=16, minute=0, second=0, microsecond=0) - timedelta(days=1)
        else:
            # After 4pm: use 4pm today as baseline
            baseline_time = measured_at.replace(hour=16, minute=0, second=0, microsecond=0)

        # Baseline measurement at 4pm (±1 hour window)
        baseline_start = (baseline_time - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        baseline_end = (baseline_time + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        windows.append((baseline_start, baseline_end, calendar.timegm(baseline_time.timetuple())))

    # Raw rows (duplicates kept, no recorded_at filter), in the index order (measured_at, id)
    # the old per-row lookup scanned. SQLite computes the epoch, as it did for the old ORDER BY.
    candidates = []
    if windows:
        cursor.execute("""
            SELECT measured_at, strftime('%s', measured_at), snow_depth_inches, total_precip_inches
            FROM weather_data
            WHERE station_id = ?
            AND measured_at >= ?
            AND measured_at <= ?
            ORDER BY measured_at, id
        """, (station_id, min(w[0] for w in windows), max(w[1] for w in windows)))
        candidates = cursor.fetchall()
    candidate_keys = [c[0] for c in candidates]

    history = []
    for row, (baseline_start, baseline_end, baseline_epoch) in zip(raw_data, windows):
        snow_depth = row[4]
        total_precip = row[5]

        # The old lookup: the window compared as text, nearest by epoch, ties to the first
        # row, an unparseable measured_at (NULL distance) sorting first
        baseline = None
        best = None
        for c in candidates[bisect_left(candidate_keys, baseline_start):
                            bisect_right(candidate_keys, baseline_end)]:
            distance = -1 if c[1] is None else abs(int(c[1]) - baseline_epoch)
            if best is None or distance < best:
                best, baseline = distance, (c[2], c[3])

        # Calculate accumulations
        snow_accum = None
        rain_accum = None
        snow_density = None

        if baseline and snow_depth is not None and baseline[0] is not None:
            # Snow accumulation = current depth - baseline depth
            snow_accum = max(0, snow_depth - baseline[0])

            # Precipitation accumulation
            if total_precip is not None and baseline[1] is not None:
                total_precip_increase = max(0, total_precip - baseline[1])

                # Calculate rain vs snow from precipitation increase
                if snow_accum > 0:
                    # Assume 10:1 snow:water ratio as baseline
                    snow_water_equiv = snow_accum / 10.0
                    rain_accum = max(0, total_precip_increase - snow_water_equiv)

                    # Calculate actual snow density
                    snow_water_only = total_precip_increase - rain_accum
                    if snow_water_only > 0:
                        snow_density = snow_water_only / snow_accum
                else:
                    # No snow accumulation, all precip is rain
                    rain_accum = total_precip_increase

        history.append({
            "station_id": row[0],
            "station_name": row[1],
            "station_type": row[2],
            "temperature_f": row[3],
            "snow_depth_inches": row[4],
            "snow_accum_inches": snow_accum,
            "rain_accum_inches": rain_accum,
            "snow_density": snow_density,
            "measured_at": row[6],
            "recorded_at": row[7]
        })

    conn.close()
    return history


@app.get("/weather/{station_id}")
def get_station_weather(station_id: str):
    """
    Get latest weather data for a specific station with on-the-fly accumulation calculation.

    Args:
        station_id: Station ID to query

    Returns:
        Weather record with current conditions and accumulation since 4pm
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get most recent measurement for this station
    cursor.execute("""
        SELECT
            station_id,
            station_name,
            station_elevation,
            station_type,
            temperature_f,
            snow_depth_inches,
            total_precip_inches,
            measured_at,
            MAX(recorded_at) as recorded_at
        FROM weather_data
        WHERE station_id = ?
        AND measured_at IS NOT NULL
        GROUP BY station_id, measured_at
        ORDER BY measured_at DESC
        LIMIT 1
    """, (station_id,))

    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Station not found")

    measured_at_str = row[7]
    snow_depth = row[5]
    total_precip = row[6]

    # Calculate 4pm baseline
    measured_at = datetime.fromisoformat(measured_at_str)
    if measured_at.hour < 16:
        baseline_time = measured_at.replace(hour=16, minute=0, second=0, microsecond=0) - timedelta(days=1)
    else:
        baseline_time = measured_at.replace(hour=16, minute=0, second=0, microsecond=0)

    baseline_start = (baseline_time - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    baseline_end = (baseline_time + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute("""
        SELECT snow_depth_inches, total_precip_inches
        FROM weather_data
        WHERE station_id = ?
        AND measured_at >= ?
        AND measured_at <= ?
        ORDER BY ABS(strftime('%s', measured_at) - strftime('%s', ?))
        LIMIT 1
    """, (station_id, baseline_start, baseline_end, baseline_time.strftime('%Y-%m-%d %H:%M:%S')))

    baseline = cursor.fetchone()
    conn.close()

    # Calculate accumulations
    snow_accum = None
    rain_accum = None
    snow_density = None

    if baseline and snow_depth is not None and baseline[0] is not None:
        snow_accum = max(0, snow_depth - baseline[0])

        if total_precip is not None and baseline[1] is not None:
            total_precip_increase = max(0, total_precip - baseline[1])

            if snow_accum > 0:
                snow_water_equiv = snow_accum / 10.0
                rain_accum = max(0, total_precip_increase - snow_water_equiv)
                snow_water_only = total_precip_increase - rain_accum
                if snow_water_only > 0:
                    snow_density = snow_water_only / snow_accum
            else:
                rain_accum = total_precip_increase

    return {
        "station_id": row[0],
        "station_name": row[1],
        "station_elevation": row[2],
        "station_type": row[3],
        "temperature_f": row[4],
        "snow_depth_inches": row[5],
        "snow_accum_inches": snow_accum,
        "rain_accum_inches": rain_accum,
        "snow_density": snow_density,
        "total_precip_inches": row[6],
        "measured_at": row[7],
        "last_updated": row[8]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
