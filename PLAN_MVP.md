# Snow Traffic - MVP Plan (Stevens Pass / US-2)

## Scope

**Single route**: Seattle ↔ Stevens Pass via US-2
**Goal**: Accumulate historical travel time data, display in simple UI

## Architecture

```
┌──────────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Poller (Python)     │────▶│  SQLite          │◀────│  UI (React SPA)  │
│  - WSDOT Travel Time │     │  - travel_times  │     │  - Current status│
│  - 5 min interval    │     │                  │     │  - History chart │
│  - cron / systemd    │     │                  │     │                  │
└──────────────────────┘     └──────────────────┘     └──────────────────┘
                                      ▲
                                      │
                             ┌────────┴─────────┐
                             │  FastAPI         │
                             │  - REST endpoints│
                             └──────────────────┘
```

## Data Source

**WSDOT Travel Times API**
- Endpoint: `https://wsdot.wa.gov/Traffic/api/TravelTimes/TravelTimesREST.svc/GetTravelTimesAsJson?AccessCode={key}`
- Returns all defined routes; filter for US-2 relevant ones
- Fields needed: `TravelTimeID`, `Name`, `CurrentTime`, `AverageTime`, `TimeUpdated`

**First task**: Hit the API, dump all routes, find the US-2 / Stevens route IDs.

## Database Schema

```sql
CREATE TABLE travel_times (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id TEXT NOT NULL,
    route_name TEXT,
    current_min INTEGER,
    average_min INTEGER,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    wsdot_updated_at DATETIME
);

CREATE INDEX idx_travel_times_route_recorded
ON travel_times(route_id, recorded_at);
```

## Poller Script

```
poll_wsdot.py
├── fetch travel times JSON
├── filter for US-2 route(s)
├── insert into SQLite
└── run via cron every 5 min
```

## UI - MVP Features

1. **Current status card**
   - Current travel time
   - Average travel time
   - Delta (% above/below average)
   - Last updated timestamp

2. **History chart**
   - Line chart: last 24h / 7d / 30d toggle
   - X-axis: time, Y-axis: travel time (min)
   - Overlay average as reference line

3. **FastAPI backend** — simple REST API for serving data to UI

## File Structure

```
snow-traffic/
├── poller/
│   ├── poll_wsdot.py          ✓
│   ├── discover_routes.py     ✓
│   ├── init_db.py             ✓
│   ├── config.py              ✓
│   └── requirements.txt       ✓
├── data/
│   └── traffic.db             (generated)
├── api/
│   ├── main.py                ✓
│   └── requirements.txt       ✓
├── ui/
│   ├── src/
│   │   ├── App.jsx            ✓
│   │   ├── components/
│   │   │   ├── StatusCard.jsx ✓
│   │   │   └── HistoryChart.jsx ✓
│   │   └── main.jsx           ✓
│   ├── package.json           ✓
│   └── vite.config.js         ✓
├── .gitignore                 ✓
├── README.md                  ✓
└── PLAN_MVP.md                ✓
```

## Implementation Status

### ✓ Step 1: Project Setup
- [x] Project structure created
- [x] .gitignore configured
- [x] README.md with setup instructions

### ✓ Step 2: Database & Schema
- [x] Database schema designed
- [x] init_db.py script created

### ✓ Step 3: Poller
- [x] Configuration management (config.py)
- [x] Route discovery script (discover_routes.py)
- [x] Main polling script (poll_wsdot.py)
- [x] Requirements.txt for dependencies

### ✓ Step 4: API Backend
- [x] FastAPI application (main.py)
- [x] REST endpoints for routes, current status, and history
- [x] CORS configuration for local development

### ✓ Step 5: UI
- [x] React + Vite setup
- [x] StatusCard component with color-coded status levels
- [x] HistoryChart component with Recharts
- [x] Responsive design
- [x] Time range selector (24h / 7d / 30d)

## Next Steps (After MVP)

### 1. Get WSDOT API Key
- Visit https://wsdot.wa.gov/traffic/api/
- Request API access code
- Set as environment variable: `export WSDOT_API_KEY="your_key"`

### 2. Discover Routes
```bash
cd poller
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python discover_routes.py
```

### 3. Update Configuration
- Copy route IDs from discover_routes.py output
- Update `US2_ROUTE_IDS` in config.py

### 4. Initialize Database
```bash
python init_db.py
```

### 5. Test Poller
```bash
python poll_wsdot.py
```

### 6. Set Up Cron
```bash
crontab -e
# Add: */5 * * * * cd /path/to/snowtraffic/poller && ./venv/bin/python poll_wsdot.py >> /tmp/wsdot_poller.log 2>&1
```

### 7. Run API
```bash
cd api
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### 8. Run UI
```bash
cd ui
npm install
npm run dev
```

## Deployment Options

### Option 1: Single VPS (Recommended for MVP)
**Hetzner CX22** — €4.51/mo (~$5)
- 2 vCPU, 4GB RAM
- Everything on one box:
  - Poller (cron)
  - SQLite database
  - FastAPI (systemd service)
  - nginx (reverse proxy + static UI)

### Option 2: Separate Components
- **Backend**: VPS for poller + API + DB
- **Frontend**: Cloudflare Pages (free) or Vercel (free)

### Option 3: Edge-Native (Future)
- Cloudflare Workers + D1 (SQLite at the edge)
- Zero server maintenance
- Global distribution

## Scaling Path

If this gets traction:

1. **First**: Add Cloudflare CDN in front
   - Cache API responses with 5-min TTL
   - Handles 10k+ users for free

2. **Later**: Optimize database queries
   - Add materialized views for common queries
   - Implement data retention policy (keep 90 days)

3. **Much Later**: Consider PostgreSQL
   - Only if SQLite becomes a bottleneck
   - Unlikely for read-heavy workload with periodic writes

## Timeline Estimate

| Phase | Effort | Notes |
|-------|--------|-------|
| ✓ Code Development | 6-8 hr | **COMPLETE** |
| Get API key | 30 min | One-time setup |
| Route discovery | 15 min | One-time |
| Data accumulation | 3-7 days | Let it run |
| Deployment | 1-2 hr | Depends on infra choice |

**MVP ready for deployment**: All code complete, waiting for API key + data accumulation

## Open Questions

1. **WSDOT API Key**: Need to request from WSDOT
2. **Exact route IDs**: Will be determined by discover_routes.py
3. **Deployment target**: VPS vs Cloudflare vs local server?
4. **Data retention**: How long to keep historical data?

## Success Metrics

- ✓ Clean, maintainable codebase
- ✓ Responsive UI that works on mobile
- ✓ Real-time updates every 5 minutes
- Historical data visualization
- Low maintenance overhead
- Under $10/month operating cost
