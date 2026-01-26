"""Unit test for weather accumulation calculation."""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Test database setup
TEST_DB = Path("/tmp/test_weather.db")

def setup_test_db():
    """Create test database with sample data."""
    if TEST_DB.exists():
        TEST_DB.unlink()

    conn = sqlite3.connect(TEST_DB)
    cursor = conn.cursor()

    # Create weather_data table
    cursor.execute("""
        CREATE TABLE weather_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT NOT NULL,
            station_name TEXT,
            station_elevation INTEGER,
            station_type TEXT,
            temperature_f REAL,
            snow_depth_inches REAL,
            total_precip_inches REAL,
            measured_at DATETIME NOT NULL,
            recorded_at DATETIME NOT NULL
        )
    """)

    # Insert test data matching real SNOTEL pattern
    test_data = [
        # Jan 7 4pm baseline
        ("snotel-791", "SNOTEL 791 - Stevens Pass", 3940, "base",  27.0, 56.0, 60.1, "2026-01-07 16:00", "2026-01-07 16:15:00"),
        # Jan 7 evening
        ("snotel-791", "SNOTEL 791 - Stevens Pass", 3940, "base",  26.2, 56.0, 60.1, "2026-01-07 17:00", "2026-01-07 17:15:00"),
        # Jan 8 morning - should show accumulation
        ("snotel-791", "SNOTEL 791 - Stevens Pass", 3940, "base",  25.5, 60.0, 60.4, "2026-01-08 10:00", "2026-01-08 10:15:00"),
    ]

    for row in test_data:
        cursor.execute("""
            INSERT INTO weather_data
            (station_id, station_name, station_elevation, station_type,
             temperature_f, snow_depth_inches, total_precip_inches, measured_at, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, row)

    conn.commit()
    conn.close()
    print(f"✓ Test database created at {TEST_DB}")


def calculate_accumulation(station_id, measured_at_str, snow_depth, total_precip):
    """Calculate accumulation - same logic as API."""
    conn = sqlite3.connect(TEST_DB)
    cursor = conn.cursor()

    # Parse measured_at to determine 4pm baseline time
    measured_at = datetime.fromisoformat(measured_at_str)

    # Determine cutoff time
    if measured_at.hour < 16:
        # Before 4pm: use 4pm yesterday as baseline
        baseline_time = measured_at.replace(hour=16, minute=0, second=0, microsecond=0) - timedelta(days=1)
    else:
        # After 4pm: use 4pm today as baseline
        baseline_time = measured_at.replace(hour=16, minute=0, second=0, microsecond=0)

    # Query for baseline measurement at 4pm (±1 hour window)
    # Use strftime to match database format (space separator, not 'T')
    baseline_start = (baseline_time - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    baseline_end = (baseline_time + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')

    print(f"\n  Measured at: {measured_at_str}")
    print(f"  Baseline time: {baseline_time}")
    print(f"  Baseline range: {baseline_start} to {baseline_end}")

    cursor.execute("""
        SELECT snow_depth_inches, total_precip_inches, measured_at
        FROM weather_data
        WHERE station_id = ?
        AND measured_at >= ?
        AND measured_at <= ?
        ORDER BY ABS(strftime('%s', measured_at) - strftime('%s', ?))
        LIMIT 1
    """, (station_id, baseline_start, baseline_end, baseline_time.strftime('%Y-%m-%d %H:%M:%S')))

    baseline = cursor.fetchone()
    conn.close()

    if not baseline:
        print(f"  ✗ NO BASELINE FOUND")
        return None, None, None

    print(f"  Baseline found: {baseline[2]} (depth: {baseline[0]}\", precip: {baseline[1]}\")")

    # Calculate accumulations
    snow_accum = None
    rain_accum = None
    snow_density = None

    if baseline and snow_depth is not None and baseline[0] is not None:
        # Snow accumulation = current depth - baseline depth
        snow_accum = max(0, snow_depth - baseline[0])
        print(f"  Snow accum: {snow_depth}\" - {baseline[0]}\" = {snow_accum}\"")

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

    return snow_accum, rain_accum, snow_density


def run_tests():
    """Run accumulation calculation tests."""
    print("\n" + "="*60)
    print("WEATHER ACCUMULATION CALCULATION TESTS")
    print("="*60)

    setup_test_db()

    # Test 1: Jan 8 10am - should show 4" accumulation since Jan 7 4pm
    print("\nTest 1: Jan 8 10:00 (morning - before 4pm)")
    print("-" * 60)
    snow_accum, rain_accum, density = calculate_accumulation(
        "snotel-791",
        "2026-01-08 10:00",
        60.0,  # current snow depth
        60.4   # current total precip
    )

    expected = 4.0  # 60" - 56" = 4"
    if snow_accum == expected:
        print(f"  ✓ PASS: Expected {expected}\", got {snow_accum}\"")
    else:
        print(f"  ✗ FAIL: Expected {expected}\", got {snow_accum}\"")

    # Test 2: Jan 7 17:00 (after 4pm same day) - should use same day 4pm as baseline = 0"
    print("\nTest 2: Jan 7 17:00 (evening - after 4pm)")
    print("-" * 60)
    snow_accum, rain_accum, density = calculate_accumulation(
        "snotel-791",
        "2026-01-07 17:00",
        56.0,  # current snow depth
        60.1   # current total precip
    )

    expected = 0.0  # 56" - 56" = 0"
    if snow_accum == expected:
        print(f"  ✓ PASS: Expected {expected}\", got {snow_accum}\"")
    else:
        print(f"  ✗ FAIL: Expected {expected}\", got {snow_accum}\"")

    print("\n" + "="*60)
    print("TESTS COMPLETE")
    print("="*60 + "\n")

    # Cleanup
    TEST_DB.unlink()


if __name__ == "__main__":
    run_tests()
