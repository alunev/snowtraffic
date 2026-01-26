# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Weather system architecture documentation (`WEATHER_SYSTEM.md`)
- Unit tests for weather accumulation calculations

### Changed
- Refactored weather data storage to store only raw SNOTEL measurements
- Weather accumulation now calculated on-demand by API instead of pre-calculated
- Improved timestamp handling for database queries

### Fixed
- Weather accumulation calculation displaying incorrect values after 4pm

## [1.0.0] - 2026-01-08

### Added
- SNOTEL weather station integration (Stevens Pass Base - 3940ft)
- Weather visualization with time range selector (24h/7d/30d)
- Snow accumulation tracking with 4pm daily baseline
- Temperature overlay on weather charts
- Historical weather data backfill capability
- Segment-by-segment traffic tracking for Stevens Pass
- Compact UI layout for route segments
- Route archiving system
- Snoqualmie return route tracking

### Changed
- Switched to TRAFFIC_AWARE routing for real-time traffic data
- Weather polling interval: every 15 minutes
- Traffic polling optimized for Google Maps API free tier

### Infrastructure
- Google Maps Directions API integration
- Weather polling via cron
- Database schema extensions for weather data
- API endpoints: `/weather/current`, `/weather/history`, `/weather/{station_id}`
- Testing framework with pytest

## [0.1.0] - 2026-01-03

### Added
- Initial MVP release
- Real-time traffic tracking for Stevens Pass (US-2)
- Historical traffic data collection and visualization
- FastAPI backend with SQLite database
- React frontend with Recharts
- WSDOT Travel Times API integration
- Google Maps Directions API integration
- Automated polling via cron (traffic: every 5 min)

### Infrastructure
- Database schema for travel times and route segments
- RESTful API endpoints for routes, current status, and history
- Responsive web UI with status cards and charts

---

## Notes

- See git commit history for detailed bug reports and technical changes
- Future feature tracking will use issue/ticket system
- For deployment details, see `DEPLOYMENT.md`
