"""FastAPI backend for serving travel time data."""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional
from pydantic import BaseModel

# Add poller to path to import config
sys.path.insert(0, str(Path(__file__).parent.parent / "poller"))
from config import ARCHIVED_ROUTES

# Database path
DB_PATH = Path(__file__).parent.parent / "data" / "traffic.db"

app = FastAPI(title="Snow Traffic API", version="1.0.0")

# CORS Configuration
# For production, set CORS_ORIGINS environment variable to comma-separated list of allowed origins
# Example: CORS_ORIGINS=https://myapp.com,https://www.myapp.com
import os
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
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
    return sqlite3.connect(DB_PATH)


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
        }
    }


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
    hours: int = 24,
    limit: int = 1000
):
    """
    Get historical data for a route.

    Args:
        route_id: Route ID to query
        hours: Number of hours to look back (default: 24)
        limit: Maximum number of records to return (default: 1000)
    """
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
    hours: int = 24,
    limit: int = 1000
):
    """
    Get segment-by-segment historical data for a route.

    Args:
        route_id: Route ID to query
        hours: Number of hours to look back (default: 24)
        limit: Maximum number of timestamps to return (default: 1000)

    Returns:
        List of records grouped by timestamp, each containing segments
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Calculate cutoff time
    cutoff = datetime.now() - timedelta(hours=hours)

    # Get distinct timestamps for this route
    cursor.execute("""
        SELECT DISTINCT recorded_at
        FROM route_segments
        WHERE route_id = ? AND recorded_at >= ?
        ORDER BY recorded_at DESC
        LIMIT ?
    """, (route_id, cutoff.isoformat(), limit))

    timestamps = [row[0] for row in cursor.fetchall()]

    # For each timestamp, get all segments
    result = []
    for timestamp in timestamps:
        cursor.execute("""
            SELECT segment_from, segment_to, duration_min, segment_order
            FROM route_segments
            WHERE route_id = ? AND recorded_at = ?
            ORDER BY segment_order
        """, (route_id, timestamp))

        segments = []
        for row in cursor.fetchall():
            segments.append({
                "from": row[0],
                "to": row[1],
                "duration_min": row[2]
            })

        result.append({
            "recorded_at": timestamp,
            "segments": segments
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
        WHERE (station_id, measured_at) IN (
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
def get_weather_history(station_id: str = "snotel-791", hours: int = 24):
    """
    Get hourly weather history for charting with on-the-fly accumulation calculation.

    Args:
        station_id: Station ID to query (default: snotel-791)
        hours: Number of hours to look back (default: 24)

    Returns:
        List of hourly weather records with calculated accumulations since 4pm
    """
    conn = get_db_connection()
    cursor = conn.cursor()

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
        AND recorded_at >= datetime('now', '-' || ? || ' hours')
        GROUP BY station_id, measured_at
        ORDER BY measured_at ASC
    """, (station_id, hours))

    raw_data = cursor.fetchall()

    history = []
    for row in raw_data:
        station_id_val = row[0]
        measured_at_str = row[6]
        snow_depth = row[4]
        total_precip = row[5]

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

        # Query for baseline measurement at 4pm (±1 hour window)
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
        """, (station_id_val, baseline_start, baseline_end, baseline_time.strftime('%Y-%m-%d %H:%M:%S')))

        baseline = cursor.fetchone()

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
