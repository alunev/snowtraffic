# Weather Data System Architecture

## Overview

The weather system fetches hourly data from SNOTEL stations and calculates snow accumulation since 4pm daily. This document describes the architecture decision to store raw data and calculate accumulations on-demand.

## Data Flow

```
SNOTEL API (AWDB)
      ↓
poll_weather.py (every 15 min)
      ↓
SQLite (RAW DATA ONLY)
      ↓
API endpoints (calculate on-demand)
      ↓
UI (displays accumulations)
```

## Architecture Decision: Raw Data Storage

### Why Store Only Raw Data?

**Database contains:**
- `temperature_f` (raw)
- `snow_depth_inches` (raw)
- `total_precip_inches` (raw)
- `measured_at` (timestamp from SNOTEL)
- `recorded_at` (when we saved it)

**Database does NOT contain:**
- ❌ `snow_accum_inches` (calculated)
- ❌ `rain_accum_inches` (calculated)
- ❌ `snow_density` (calculated)

### Benefits

1. **Single source of truth**: Raw SNOTEL measurements are the only stored data
2. **No stale calculations**: Accumulation logic can be updated without database migration
3. **Flexible time windows**: Can calculate accumulation for any baseline (4pm, midnight, etc.)
4. **Deduplication friendly**: Same measurement stored multiple times doesn't affect calculations

### Trade-offs

- **More API computation**: Each request recalculates accumulations
- **Acceptable because**: Read-heavy workload, calculations are simple arithmetic
- **Optimization if needed**: Add caching layer (5-15 min TTL)

## Accumulation Calculation Logic

### Algorithm

```python
def calculate_accumulation(measured_at, current_depth, baseline_depth):
    """
    Calculate snow accumulation since 4pm baseline.

    Baseline logic:
    - If measured before 4pm today: use 4pm yesterday
    - If measured after 4pm today: use 4pm today
    """
    if measured_at.hour < 16:
        baseline_time = measured_at.replace(hour=16, minute=0) - timedelta(days=1)
    else:
        baseline_time = measured_at.replace(hour=16, minute=0)

    # Find closest measurement to baseline_time (±1 hour window)
    baseline = find_closest_measurement(baseline_time)

    # Calculate accumulation
    snow_accum = max(0, current_depth - baseline.snow_depth)

    return snow_accum
```

### Example Scenario

**Given:**
- Jan 7 16:00 (4pm): 56" snow depth
- Jan 8 10:00 (10am): 60" snow depth

**Calculation for Jan 8 10:00:**
1. Measured at 10:00 (hour < 16) → use Jan 7 16:00 as baseline
2. Find baseline: 56"
3. Calculate: 60" - 56" = **4" accumulation**

## API Endpoints

### `/weather/history`

**Query parameters:**
- `station_id`: Station to query (default: "snotel-791")
- `hours`: Hours of history (default: 24)

**Response:** Deduplicates by `measured_at`, calculates accumulation for each record

```json
{
  "station_id": "snotel-791",
  "measured_at": "2026-01-08 10:00",
  "snow_depth_inches": 60.0,
  "snow_accum_inches": 4.0,
  "temperature_f": 25.5,
  "rain_accum_inches": 0.3,
  "snow_density": 0.1
}
```

### `/weather/current`

Returns latest measurement with calculated accumulation since 4pm.

### `/weather/{station_id}`

Returns latest measurement for specific station with accumulation.

## Database Schema

```sql
CREATE TABLE weather_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    station_name TEXT,
    station_elevation INTEGER,
    station_type TEXT,  -- 'base' or 'summit'
    temperature_f REAL,
    snow_depth_inches REAL,
    total_precip_inches REAL,
    measured_at DATETIME NOT NULL,  -- When SNOTEL measured
    recorded_at DATETIME NOT NULL   -- When we saved it
);

CREATE INDEX idx_weather_station_measured
ON weather_data(station_id, measured_at);
```

**Note:** `measured_at` uses space-separated format (`2026-01-08 10:00`), not ISO format with 'T'.

## Historical Bug Fix (2026-01-09)

### Problem

Weather charts showed **zeros after 4pm** instead of continuing to show accumulation.

### Root Cause

1. **Pre-calculated accumulations stored in DB** instead of raw data
2. **4pm baseline logic failed** when switching from "yesterday 4pm" to "today 4pm"
3. **Timestamp format mismatch**: API used `.isoformat()` (with 'T'), database used space separator

### Solution

1. Modified `poll_weather.py` to save only raw SNOTEL data
2. Modified API endpoints to calculate accumulation on-the-fly
3. Fixed timestamp format: `.isoformat()` → `.strftime('%Y-%m-%d %H:%M:%S')`

### Test Results

```
Jan 8 10:00 test:
  Snow depth: 60.0 inches
  Accumulation: 4.0 inches (60" - 56" from Jan 7 4pm)
  ✓ SUCCESS
```

## SNOTEL Data Characteristics

### Update Frequency

- **SNOTEL reports**: Hourly measurements
- **API lag**: 1-3 hours typical, sometimes longer
- **Our polling**: Every 15 minutes
- **Deduplication**: Query groups by `measured_at` to handle duplicate polls

### Station Configuration

```python
WEATHER_STATIONS = [
    {
        "id": "snotel-791",
        "name": "SNOTEL 791 - Stevens Pass",
        "triplet": "791:WA:SNTL",
        "elevation": 3940,
        "type": "base"
    }
]
```

## 4pm Reset Rationale

**Why 4pm?**
- Ski industry standard for "overnight accumulation"
- Matches ski resort snow report timing
- Useful for planning next-day ski trips

**Alternative baselines** could be implemented:
- Midnight (calendar day)
- Custom time windows
- Last 24 hours (rolling)

All possible by changing API calculation logic without touching database.

## Monitoring

### Data Quality Checks

```bash
# Check for duplicate measurements
sqlite3 traffic.db "
SELECT measured_at, COUNT(*)
FROM weather_data
WHERE station_id='snotel-791'
GROUP BY measured_at
HAVING COUNT(*) > 1
"

# Check for data gaps
sqlite3 traffic.db "
SELECT
  measured_at,
  LEAD(measured_at) OVER (ORDER BY measured_at) as next_time,
  (strftime('%s', LEAD(measured_at) OVER (ORDER BY measured_at)) -
   strftime('%s', measured_at)) / 3600.0 as hours_gap
FROM weather_data
WHERE station_id='snotel-791'
  AND hours_gap > 2
"
```

### API Performance

Typical accumulation calculation:
- Database query: ~5ms
- Calculation: <1ms
- Total per request: <10ms

Optimization only needed if serving >100 req/sec.

## Future Enhancements

### Potential Additions

1. **Multiple stations**: Summit measurements (when API access established)
2. **Weather trends**: Rising/falling temperature, precipitation rate
3. **Density tracking**: Better rain/snow separation
4. **Data validation**: Flag anomalies (sudden depth decreases, etc.)

### Database Optimizations

If performance becomes an issue:
- Materialized view for daily 4pm baselines
- Caching layer (Redis) for recent calculations
- Pre-calculate for common time windows (24h, 7d)

All possible without changing core architecture of storing raw data.
