# Development Notes

Quick reference for development decisions and architecture.

## Architecture

### Data Flow
```
Google Maps API → poll_gmaps.py → traffic.db → FastAPI → React UI
SNOTEL API → poll_weather.py → traffic.db → FastAPI → React UI
```

### Polling Schedule
```
*/30 * * * *  Traffic data (Google Maps Routes API) - Stevens Pass only
0 * * * *     Weather data (SNOTEL AWDB API)
0 2 * * *     Database backup
```

## API Endpoints

### Traffic
- `GET /routes` - List all active routes
- `GET /current` - Current status for all routes
- `GET /current/{route_id}` - Current status for specific route
- `GET /history/{route_id}?hours=24` - Historical data
- `GET /segments/{route_id}?hours=24` - Segment-by-segment data

### Weather
- `GET /weather/current` - Latest weather from all stations
- `GET /weather/{station_id}` - Latest weather for specific station

## Design Decisions

### Weather Integration (2026-01-06)
- **Data source**: SNOTEL 791 (Stevens Pass base station)
- **Polling**: Hourly via cron
- **Accumulation period**: Since 4pm (daily lifts closure)
- **Display**: Inline with travel time, only on "to Stevens Pass" routes
- **Format**: `Base: 26.4°F • 0.0" snow / 0.00" rain (since 4pm)`

### Route Configuration
- **Stevens Pass**: Segments enabled (Monroe, Sultan, Skykomish)
- **Snoqualmie**: No segments (direct route)
- **Mt Baker**: Segments enabled (Everett, Burlington, Glacier)

### Backup Strategy
- **Retention**: 90 days with compacting
- **Schedule**: Daily at 2 AM
- **Compacting**: Last 30 days daily, days 31-90 every 5 days

## Common Tasks

### Add New Route
1. Update `poller/config.py` ROUTES array
2. Run `poll_gmaps.py` to test
3. Deploy

### Add New Weather Station
1. Update `poller/config.py` WEATHER_STATIONS array
2. Update `poller/init_db.py` if schema changes needed
3. Run `poll_weather.py` to test
4. Deploy

## Tech Stack

- **Backend**: Python 3.12, FastAPI, uvicorn
- **Database**: SQLite3
- **Frontend**: React 18, Vite, Recharts
- **Server**: Nginx (reverse proxy)
- **APIs**: Google Maps Routes API, SNOTEL AWDB REST API

## Future Enhancements

See WEATHER_DATA.md for details:
- Add summit weather station (Skyline STS52)
- Historical weather charts
- Weather alerts for heavy snow
- Forecast integration
- Avalanche danger ratings (NWAC)
