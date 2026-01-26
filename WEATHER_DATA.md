# Weather Data Integration

Documentation for weather station monitoring and data sources used in the Snow Traffic.

## Overview

The application integrates real-time weather data from SNOTEL weather stations to provide skiers with current conditions and accumulation information since lifts closed (4pm daily).

## Data Sources

### SNOTEL 791 - Stevens Pass (Base Station)

**Location:** Stevens Pass, Washington
**Elevation:** 3,940 feet
**Station Type:** Base
**Coordinates:** 47.75°N, 121.09°W
**Operational Since:** October 1979

#### Station Capabilities
- Temperature observations (hourly)
- Snow depth (hourly)
- Precipitation accumulation (hourly)
- Snow water equivalent
- Relative humidity
- Solar radiation

### API Access

**SNOTEL AWDB REST API**
- Base URL: `https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data`
- No API key required (public access)
- Rate Limits: None documented (reasonable use expected)

#### API Request Format

```
GET /awdbRestApi/services/v1/data
Parameters:
  - stationTriplets: 791:WA:SNTL
  - elements: TOBS,PREC,SNWD
  - ordinal: 1
  - duration: HOURLY
  - getFlags: false
```

#### Data Elements

| Element Code | Description | Unit | Update Frequency |
|--------------|-------------|------|------------------|
| TOBS | Temperature Observed | °F | Hourly |
| PREC | Precipitation Accumulation | inches | Hourly |
| SNWD | Snow Depth | inches | Hourly |
| WTEQ | Snow Water Equivalent | inches | Hourly |

#### Example Response

```json
[
  {
    "stationTriplet": "791:WA:SNTL",
    "data": [
      {
        "stationElement": {
          "elementCode": "TOBS",
          "ordinal": 1,
          "durationName": "HOURLY",
          "storedUnitCode": "degF"
        },
        "values": [
          {
            "date": "2026-01-05 22:00",
            "value": 26.4
          }
        ]
      }
    ]
  }
]
```

### Future Data Sources (Planned)

#### Skyline STS52 - Stevens Pass (Summit Station)

**Location:** Stevens Pass Skyline Chair
**Elevation:** 5,248 feet
**Station Type:** Summit
**Status:** Pending - API access challenges

**Potential Data Sources:**
1. **National Weather Service API**
   - Endpoint: `https://api.weather.gov/stations/STS52/observations`
   - Status: Station ID verification needed
   - Free, no API key required

2. **NWAC (Northwest Avalanche Center)**
   - URL: `https://nwac.us/api/v1/`
   - Stations: Skyline (18), Tye Mill (17), Schmidt Haus (13)
   - Status: API structure needs investigation

#### Alternative Stations

- **Schmidt Haus (NWAC 13):** 4,111 ft - Highway level
- **Tye Mill (NWAC 17):** Similar to Skyline
- **Grace Lakes (STS48):** Elevation unknown

## Implementation Details

### Data Collection

**Polling Schedule:** Every 15 minutes (configurable via `WEATHER_POLL_INTERVAL_MINUTES`)

**Poller Module:** `/poller/poll_weather.py`
- Fetches current conditions from configured stations
- Calculates accumulation since 4pm (lifts closure time) **using database baselines**
- Separates snow vs rain accumulation
- Calculates snow density (water content ratio)
- Stores raw and calculated data in SQLite database

**Key Improvement:** The poller queries the database (not the SNOTEL API) for the 4pm baseline. This allows accumulation calculation to work all day, even after SNOTEL's API retention window expires (~12 hours).

### Accumulation Calculation

The system calculates three values since 4pm:

1. **Snow Accumulation**
   - Measured as increase in snow depth (SNWD)
   - Direct reading from SNOTEL sensor
   - Accounts for settling and compaction
   - Formula: `current_snow_depth - snow_depth_at_4pm`

2. **Rain Accumulation**
   - Calculated as: Total Precip - Snow Water Equivalent
   - Uses 10:1 initial ratio approximation for separation
   - Less accurate in mixed precipitation
   - Formula: `total_precip_increase - (snow_accum / 10)`

3. **Snow Density (Water Content Ratio)**
   - Actual measured ratio of water to snow
   - Formula: `(precip_from_snow) / snow_accum`
   - Displayed as inverse ratio (e.g., 0.06 = 17:1 powder)
   - Only calculated when snow accumulation > 0
   - **Example:** 1.3" precipitation, 12" snow → 0.11 density → 9:1 ratio (heavy/wet)

**Cutoff Logic:**
- Before 4pm: Uses yesterday at 4pm as baseline
- After 4pm: Uses today at 4pm as baseline
- Database query uses ±1 hour window to find nearest reading

### Database Schema

```sql
CREATE TABLE weather_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    station_name TEXT,
    station_elevation INTEGER,
    station_type TEXT,            -- 'base' or 'summit'
    temperature_f REAL,
    snow_depth_inches REAL,
    snow_accum_inches REAL,       -- Since 4pm
    rain_accum_inches REAL,       -- Since 4pm
    snow_density REAL,            -- Water content ratio (e.g., 0.06 = 17:1)
    total_precip_inches REAL,     -- Cumulative season total
    accumulation_period TEXT,     -- 'since_4pm'
    measured_at DATETIME,         -- When SNOTEL measured
    recorded_at DATETIME          -- When we stored it
)
```

**Storage Strategy:**
- Raw data (temperature, snow_depth, total_precip) is stored from SNOTEL
- Calculated fields (snow_accum, rain_accum, snow_density) are also stored
- This hybrid approach allows for future recalculation via backfill script

### API Endpoints

**Get Current Weather**
```
GET /api/weather/current
Returns: Array of all weather stations with latest data
```

**Get Weather History**
```
GET /api/weather/history?hours=24
Returns: Hourly weather data for charting
Query Parameters:
  - hours: Number of hours to look back (default: 24)
```

**Get Station Weather**
```
GET /api/weather/{station_id}
Returns: Single station's latest data
```

### UI Integration

#### Inline Weather Display
**Location:** Inline with travel time info on Stevens Pass route cards

**Format:**
```
Base: 26°F • 4.0" snow (17:1) / 0.0" rain (since 4pm)
```

The density ratio (e.g., 17:1) indicates powder quality - higher ratios mean lighter, drier snow.

#### Weather Chart
**Component:** `WeatherChart.jsx`
**Location:** Below travel time chart

**Features:**
- **Temperature line** (red) showing hourly temperature with 32°F freezing reference
- **Snow accumulation bars** (blue) showing hourly snow since 4pm
- **Stats summary** showing: Since 4pm (with density), 24h, 3d, 7d, current depth, temperature
- **Time range selector:** 24 Hours, 7 Days, 30 Days
- **Auto-refresh:** Every 15 minutes

**Design inspiration:** LivePow-style chart optimized for morning ski decisions

## Data Quality Notes

### Limitations

1. **Hourly Resolution**
   - SNOTEL reports hourly, not real-time
   - 4pm cutoff may be off by up to 1 hour

2. **Snow vs Rain Separation**
   - Uses 10:1 ratio approximation
   - May be inaccurate during mixed precipitation
   - Actual snow-water ratio varies (5:1 to 15:1)

3. **Sensor Accuracy**
   - Temperature: ±0.5°F
   - Snow depth: ±1 inch
   - Precipitation: ±0.1 inches

### Best Practices

- Weather data is supplementary to traffic data
- Use for general conditions awareness
- Not suitable for avalanche forecasting
- Refer to NWAC for ski-specific forecasts

## Maintenance

### Monitoring

Check poller logs:
```bash
tail -f /var/log/weather_poller.log
```

### Backfilling Historical Data

If accumulation calculations need to be recalculated (e.g., after bug fix):

```bash
cd poller
source venv/bin/activate
python backfill_accumulation.py
```

**What it does:**
- Recalculates snow_accum, rain_accum, and snow_density for all historical records
- Uses database (not SNOTEL API) for 4pm baselines
- Works for old data beyond SNOTEL's API retention
- Safe to run multiple times (idempotent)

### Database Cleanup

**⚠️ IMPORTANT:** Weather data is kept indefinitely for historical analysis. Do NOT delete records.

If cleanup is absolutely necessary (e.g., corrupted data):
```sql
DELETE FROM weather_data
WHERE recorded_at < datetime('now', '-90 days');
```

After deletion, rerun the backfill script to recalculate affected records.

### Troubleshooting

**No weather data showing:**
1. Check if poller is running: `systemctl status weather-poller`
2. Test API manually: `curl "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data?stationTriplets=791:WA:SNTL&elements=TOBS&ordinal=1&duration=HOURLY&getFlags=false"`
3. Check database: `sqlite3 data/traffic.db "SELECT * FROM weather_data ORDER BY id DESC LIMIT 5"`

**Stale data:**
- SNOTEL updates hourly
- Check `measured_at` timestamp
- If >2 hours old, investigate poller cron job

## References

### Official Documentation

- [SNOTEL Network Overview](https://www.wcc.nrcs.usda.gov/snow/)
- [AWDB Web Service Guide](https://www.nrcs.usda.gov/wps/portal/wcc/home/dataAccessHelp/webService/)
- [SNOTEL Station 791 Site Info](https://wcc.sc.egov.usda.gov/nwcc/site?sitenum=791)
- [NWS API Documentation](https://www.weather.gov/documentation/services-web-api)
- [NWAC Stevens Pass Weather](https://nwac.us/weatherdata/stevensskiarea/now/)

### Related Projects

- [ulmo](https://github.com/ulmo-dev/ulmo) - Python library for SNOTEL access
- [RNRCS](https://github.com/rhlee12/RNRCS) - R package for NRCS data
- [metloom](https://github.com/M3Works/metloom) - Python library for mountain weather data

## Completed Features

- ✅ **Snow Density Calculation** - Real-time powder quality indicator (e.g., 17:1)
- ✅ **Historical Weather Chart** - Temperature and accumulation trends with time range selector
- ✅ **Database-based Accumulation** - Works all day, not limited by SNOTEL API retention
- ✅ **Backfill Script** - Recalculate historical data after algorithm changes
- ✅ **15-minute Polling** - Faster updates (every 15 min vs hourly)

## Future Enhancements

1. **Add Summit Station** - Integrate Skyline STS52 or NWAC data
2. **Weather Alerts** - Notify when heavy snow detected (push notifications)
3. **Forecast Integration** - Add NWS forecast data for planning
4. **Multiple Ski Areas** - Expand to Snoqualmie and Mt Baker stations
5. **Avalanche Data** - Integrate NWAC avalanche danger ratings
6. **Snow Quality Alerts** - Notify when density indicates powder (>15:1)

## License & Attribution

Weather data provided by:
- **USDA Natural Resources Conservation Service** (SNOTEL data)
- **National Weather Service** (NWS observations)
- **Northwest Avalanche Center** (NWAC data)

Data is public domain. Attribution appreciated but not required.
