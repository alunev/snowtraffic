"""Backfill snow/rain accumulation for historical weather data."""
import sqlite3
from datetime import datetime, timedelta
from config import DB_PATH


def backfill_accumulation():
    """Recalculate accumulation for all historical weather records."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get all distinct dates in the data
    cursor.execute("""
        SELECT DISTINCT date(measured_at) as measurement_date
        FROM weather_data
        WHERE station_id = 'snotel-791'
        ORDER BY measurement_date
    """)

    dates = [row[0] for row in cursor.fetchall()]
    print(f"Found {len(dates)} unique dates to process")

    records_updated = 0

    for date_str in dates:
        # For each date, determine the 4pm cutoff
        date = datetime.strptime(date_str, "%Y-%m-%d")

        # For measurements taken before 4pm on this date, use previous day's 4pm
        # For measurements taken at/after 4pm on this date, use this day's 4pm

        # Process records for this date
        cursor.execute("""
            SELECT id, measured_at, snow_depth_inches, total_precip_inches
            FROM weather_data
            WHERE station_id = 'snotel-791'
              AND date(measured_at) = ?
            ORDER BY measured_at
        """, (date_str,))

        records = cursor.fetchall()

        for record in records:
            record_id = record[0]
            measured_at_str = record[1]

            # Handle both "YYYY-MM-DD HH:MM" and "YYYY-MM-DD" formats
            if len(measured_at_str) == 10:  # Just date
                measured_at = datetime.strptime(measured_at_str, "%Y-%m-%d")
            else:  # Date and time
                measured_at = datetime.strptime(measured_at_str, "%Y-%m-%d %H:%M")

            snow_current = record[2]
            precip_current = record[3]

            # Determine cutoff time
            if measured_at.hour < 16:
                cutoff_time = measured_at.replace(hour=16, minute=0, second=0, microsecond=0) - timedelta(days=1)
            else:
                cutoff_time = measured_at.replace(hour=16, minute=0, second=0, microsecond=0)

            # Find baseline at 4pm (±1 hour window)
            cutoff_start = (cutoff_time - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            cutoff_end = (cutoff_time + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("""
                SELECT snow_depth_inches, total_precip_inches
                FROM weather_data
                WHERE station_id = 'snotel-791'
                  AND measured_at >= ?
                  AND measured_at <= ?
                ORDER BY ABS(strftime('%s', measured_at) - strftime('%s', ?))
                LIMIT 1
            """, (cutoff_start, cutoff_end, cutoff_time.strftime("%Y-%m-%d %H:%M:%S")))

            baseline = cursor.fetchone()

            if not baseline or snow_current is None or precip_current is None:
                # Can't calculate, leave as NULL
                continue

            snow_at_4pm = baseline[0]
            precip_at_4pm = baseline[1]

            if snow_at_4pm is None or precip_at_4pm is None:
                continue

            # Calculate accumulations
            snow_accum = max(0, snow_current - snow_at_4pm)
            total_precip_increase = max(0, precip_current - precip_at_4pm)

            # Calculate rain and snow density
            rain_accum = None
            snow_density = None

            if snow_accum > 0:
                snow_water_equiv = snow_accum / 10.0
                rain_accum = max(0, total_precip_increase - snow_water_equiv)

                snow_water_only = total_precip_increase - rain_accum
                if snow_water_only > 0:
                    snow_density = snow_water_only / snow_accum
            else:
                rain_accum = total_precip_increase if total_precip_increase > 0 else 0

            # Update the record
            cursor.execute("""
                UPDATE weather_data
                SET snow_accum_inches = ?,
                    rain_accum_inches = ?,
                    snow_density = ?
                WHERE id = ?
            """, (snow_accum, rain_accum, snow_density, record_id))

            records_updated += 1

            if records_updated % 100 == 0:
                print(f"Updated {records_updated} records...")
                conn.commit()

    conn.commit()
    conn.close()

    print(f"\n✓ Backfill complete! Updated {records_updated} weather records")


if __name__ == "__main__":
    print("Starting accumulation backfill...")
    backfill_accumulation()
