"""Poll SNOTEL weather station data and store in SQLite."""
import json
import math
import os
import re
import requests
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from config import DB_PATH, AWDB_API_URL, WEATHER_STATIONS

# Written on every run, next to traffic.db; the API's /health reads it (0644, through "other").
# The name must never match the nightly backup sweep's traffic*.db*.
STAMP_PATH = Path(DB_PATH).parent / "stamp-weather.json"

# The snow source failing on its side: no answer at all (timeout, refused or dropped
# connection, TLS), a server error, or a 404, which SNOTEL also gives while it is down
# (8.5 h of them on 2026-01-26 with no change on our side). Anything else that leaves no
# row (another 4xx, a body we cannot use, our own exception) is ours to fix.
UNREACHABLE = (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
               requests.exceptions.ChunkedEncodingError)


def upstream_is_down(status):
    return status is not None and (status >= 500 or status == 404)


def fetch_snotel_data(station):
    """Fetch current weather data from SNOTEL station.

    Returns (reading or None, upstream): upstream is {"status": the HTTP status, if one came
    back, "error": the exception class name, if one was raised, "down": whether the snow
    source failed on its side}. Never the response body."""
    upstream = {"status": None, "error": None, "down": False}
    try:
        params = {
            "stationTriplets": station["triplet"],
            "elements": "TOBS,PREC,SNWD",  # Temperature, Precipitation, Snow Depth
            "ordinal": 1,
            "duration": "HOURLY",
            "getFlags": "false"
        }

        response = requests.get(AWDB_API_URL, params=params, timeout=30)
        upstream["status"] = response.status_code
        upstream["down"] = upstream_is_down(response.status_code)

        if response.status_code != 200:
            print(f"ERROR: SNOTEL API returned status {response.status_code}")
            return None, upstream

        data = response.json()

        if not data or len(data) == 0:
            print(f"ERROR: No data returned from SNOTEL API")
            return None, upstream

        station_data = data[0]

        # Extract elements
        result = {
            "station_id": station["id"],
            "station_name": station["name"],
            "station_elevation": station["elevation"],
            "station_type": station["type"],
            "temperature_f": None,
            "snow_depth_inches": None,
            "total_precip_inches": None,
            "measured_at": None
        }

        for element in station_data.get("data", []):
            element_code = element["stationElement"]["elementCode"]
            values = element.get("values", [])

            if len(values) == 0:
                continue

            # Get most recent non-null value
            latest = None
            for v in reversed(values):
                if v.get("value") is not None:
                    latest = v
                    break

            if not latest:
                continue

            if element_code == "TOBS":
                result["temperature_f"] = latest["value"]
                result["measured_at"] = latest["date"]
            elif element_code == "PREC":
                result["total_precip_inches"] = latest["value"]
                if not result["measured_at"]:
                    result["measured_at"] = latest["date"]
            elif element_code == "SNWD":
                result["snow_depth_inches"] = latest["value"]
                if not result["measured_at"]:
                    result["measured_at"] = latest["date"]

        return result, upstream

    except requests.exceptions.RequestException as e:
        upstream["error"] = type(e).__name__
        upstream["down"] = upstream["status"] is None and isinstance(e, UNREACHABLE)
        print(f"ERROR fetching SNOTEL data: {e}")
        return None, upstream
    except Exception as e:
        upstream["error"] = type(e).__name__
        print(f"ERROR processing SNOTEL data: {e}")
        return None, upstream


def write_stamp(upstream, saved):
    """The run's heartbeat for /health. A failure here is printed, never raised: the
    reading matters more than the stamp, and a stamp that stops changing turns /health red."""
    stamp = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "status": upstream["status"], "error": upstream["error"],
             "upstream_down": upstream["down"], "saved": saved}
    tmp = STAMP_PATH.with_name(f".{STAMP_PATH.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(stamp) + "\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, STAMP_PATH)
    except OSError as e:
        print(f"ERROR writing {STAMP_PATH.name}: {e}")
        try:
            tmp.unlink()
        except OSError:
            pass


VALUE_FIELDS = ("temperature_f", "snow_depth_inches", "total_precip_inches")
# SNOTEL's shape: a date, then optionally a space or T and HH:MM (seconds optional).
# fromisoformat alone also takes the compact 20261110, which SQLite stores as an integer.
MEASURED_AT_SHAPE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}([ T][0-9]{2}:[0-9]{2}(:[0-9]{2})?)?")


def reading_problem(weather_data):
    """Why a reading must not be saved, or None. The API parses measured_at with
    datetime.fromisoformat and does arithmetic on the values, so one bad row used to
    make /weather/* return 500 until the DB was edited. A single missing value is
    fine (live rows lack temperature and precip); text, bools, NaN/inf are not."""
    measured_at = weather_data.get("measured_at")
    if not isinstance(measured_at, str):
        return f"measured_at is {measured_at!r}"
    if not MEASURED_AT_SHAPE.fullmatch(measured_at):
        return f"measured_at {measured_at!r} is not YYYY-MM-DD[ HH:MM[:SS]]"
    try:
        datetime.fromisoformat(measured_at)
    except ValueError:
        return f"measured_at {measured_at!r} does not parse"
    values = [weather_data.get(f) for f in VALUE_FIELDS]
    for field, value in zip(VALUE_FIELDS, values):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return f"{field} is {value!r}, not a number"
    if all(v is None for v in values):
        return "no values"
    return None


def save_to_database(weather_data):
    """Save raw weather data to SQLite database."""
    if not weather_data:
        print("No weather data to save")
        return

    problem = reading_problem(weather_data)
    if problem:
        print(f"WARNING: skipped a malformed reading for {weather_data.get('station_id')}: {problem}")
        return False

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Save only raw SNOTEL data - no pre-calculated accumulations
    cursor.execute("""
        INSERT INTO weather_data
        (station_id, station_name, station_elevation, station_type,
         temperature_f, snow_depth_inches, total_precip_inches, measured_at, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        weather_data["station_id"],
        weather_data["station_name"],
        weather_data["station_elevation"],
        weather_data["station_type"],
        weather_data["temperature_f"],
        weather_data["snow_depth_inches"],
        weather_data["total_precip_inches"],
        weather_data["measured_at"],
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    print(f"✓ Saved weather data for {weather_data['station_name']}")
    return True


def main():
    """Main weather polling function."""
    print(f"[{datetime.now().isoformat()}] Starting weather data poll...")

    records_saved = 0
    # Stays "nothing fetched" if no station is polled: /health reads that as our failure
    upstream = {"status": None, "error": None, "down": False}

    try:
        # Fetch data for all configured weather stations (one today; the stamp keeps the last)
        for station in WEATHER_STATIONS:
            weather_data, upstream = fetch_snotel_data(station)

            if not weather_data:
                print(f"WARNING: Failed to fetch data for {station['name']}")
                continue

            # Display current data
            print(f"\n{weather_data['station_name']} ({weather_data['station_type'].upper()}):")
            print(f"  Temperature: {weather_data['temperature_f']}°F")
            print(f"  Snow Depth: {weather_data['snow_depth_inches']} inches")
            print(f"  Total Precipitation: {weather_data['total_precip_inches']} inches")
            print(f"  Measured at: {weather_data['measured_at']}")

            # Save raw data to database (accumulation calculated by API on-demand)
            if save_to_database(weather_data):
                records_saved += 1
    finally:
        # Every run, even one that raised: a DB write that fails leaves "answered, 0 saved"
        write_stamp(upstream, records_saved)

    print(f"\n✓ Saved {records_saved} weather station records")
    print(f"[{datetime.now().isoformat()}] Weather poll complete\n")


if __name__ == "__main__":
    main()
