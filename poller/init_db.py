"""Initialize the SQLite database schema."""
import sqlite3
from pathlib import Path
from config import DB_DIR, DB_PATH


def init_database():
    """Create the database and tables if they don't exist."""
    # Ensure data directory exists
    DB_DIR.mkdir(parents=True, exist_ok=True)

    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create travel_times table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS travel_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id TEXT NOT NULL,
            route_name TEXT,
            current_min INTEGER,
            average_min INTEGER,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            wsdot_updated_at DATETIME
        )
    """)

    # Create index for efficient queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_travel_times_route_recorded
        ON travel_times(route_id, recorded_at)
    """)

    # Create route_segments table for segment-by-segment tracking
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS route_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id TEXT NOT NULL,
            segment_order INTEGER NOT NULL,
            segment_from TEXT NOT NULL,
            segment_to TEXT NOT NULL,
            duration_min INTEGER,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create index for segment queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_route_segments_route_recorded
        ON route_segments(route_id, recorded_at)
    """)

    # Create weather_data table for SNOTEL and other weather stations
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS weather_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT NOT NULL,
            station_name TEXT,
            station_elevation INTEGER,
            station_type TEXT,
            temperature_f REAL,
            snow_depth_inches REAL,
            snow_accum_inches REAL,
            rain_accum_inches REAL,
            snow_density REAL,
            total_precip_inches REAL,
            accumulation_period TEXT,
            measured_at DATETIME,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create index for weather queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_weather_station_measured
        ON weather_data(station_id, measured_at)
    """)

    conn.commit()
    conn.close()

    print(f"✓ Database initialized at {DB_PATH}")


if __name__ == "__main__":
    init_database()
