"""Poll SNOTEL weather station data and store in SQLite."""
import requests
import sqlite3
from datetime import datetime, timedelta
from config import DB_PATH, AWDB_API_URL, WEATHER_STATIONS


def fetch_snotel_data(station):
    """Fetch current weather data from SNOTEL station."""
    try:
        params = {
            "stationTriplets": station["triplet"],
            "elements": "TOBS,PREC,SNWD",  # Temperature, Precipitation, Snow Depth
            "ordinal": 1,
            "duration": "HOURLY",
            "getFlags": "false"
        }

        response = requests.get(AWDB_API_URL, params=params, timeout=30)

        if response.status_code != 200:
            print(f"ERROR: SNOTEL API returned status {response.status_code}")
            return None

        data = response.json()

        if not data or len(data) == 0:
            print(f"ERROR: No data returned from SNOTEL API")
            return None

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

        return result

    except requests.exceptions.RequestException as e:
        print(f"ERROR fetching SNOTEL data: {e}")
        return None
    except Exception as e:
        print(f"ERROR processing SNOTEL data: {e}")
        return None


def save_to_database(weather_data):
    """Save raw weather data to SQLite database."""
    if not weather_data:
        print("No weather data to save")
        return

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


def main():
    """Main weather polling function."""
    print(f"[{datetime.now().isoformat()}] Starting weather data poll...")

    records_saved = 0

    # Fetch data for all configured weather stations
    for station in WEATHER_STATIONS:
        weather_data = fetch_snotel_data(station)

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
        save_to_database(weather_data)
        records_saved += 1

    print(f"\n✓ Saved {records_saved} weather station records")
    print(f"[{datetime.now().isoformat()}] Weather poll complete\n")


if __name__ == "__main__":
    main()
