"""The pre-S2 /segments and /weather/history, kept as the reference the new
single-query versions must match byte for byte (test_s2_queries.py) and as the
positive control for the statement-budget test: this is the per-timestamp loop.

The two blocks between the markers are verbatim copies of api/main.py at commit
2905495 (lines 418-476 and 580-697); test_reference_is_verbatim pins their hashes.
Do not edit them. Everything outside the markers is the glue they need."""
from datetime import datetime, timedelta

from fastapi import FastAPI, Query

import main

app = FastAPI()

# The caps as they were at 2905495
MAX_HOURS = 2160
MAX_LIMIT = 5000


def get_db_connection():
    # Resolved at call time, so a test's monkeypatched main.DB_PATH applies
    return main.get_db_connection()


# --- BEGIN VERBATIM 2905495:api/main.py:418-476 ---
@app.get("/segments/{route_id}")
def get_segments(
    route_id: str,
    hours: int = Query(24, ge=1, le=MAX_HOURS),
    limit: int = Query(1000, ge=1, le=MAX_LIMIT)
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
# --- END VERBATIM ---


# --- BEGIN VERBATIM 2905495:api/main.py:580-697 ---
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
        LIMIT ?
    """, (station_id, hours, limit))

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
# --- END VERBATIM ---
