"""Configuration for traffic data poller."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# Google Maps API Configuration
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

# Database Configuration
DB_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DB_DIR / "traffic.db"

# Polling Configuration
# Only active (non-archived) routes are polled
# 15 minutes = ~17,280 requests/month with 6 routes = $86/month (within $200 free tier)
# 10 minutes = ~25,920 requests/month with 6 routes = $130/month (within $200 free tier)
# 5 minutes = ~51,840 requests/month with 6 routes = $259/month ($59 after credit)
POLL_INTERVAL_MINUTES = 15

# Google Maps Routes Configuration
# Define origin-destination pairs to track
ROUTES = [
    # Stevens Pass routes (with waypoints for segment tracking)
    {
        "id": "redmond-stevens-eb",
        "name": "Redmond to Stevens Pass",
        "origin": "Redmond, WA 98052",
        "destination": "Stevens Pass, WA 98826",
        "waypoints": [
            {"location": "Monroe, WA", "name": "Monroe"},
            {"location": "Sultan, WA", "name": "Sultan"},
            {"location": "Skykomish, WA", "name": "Skykomish"}
        ]
    },
    {
        "id": "stevens-redmond-wb",
        "name": "Stevens Pass to Redmond",
        "origin": "Stevens Pass, WA 98826",
        "destination": "Redmond, WA 98052",
        "waypoints": [
            {"location": "Skykomish, WA", "name": "Skykomish"},
            {"location": "Sultan, WA", "name": "Sultan"},
            {"location": "Monroe, WA", "name": "Monroe"}
        ]
    },
    # Snoqualmie Pass routes
    {
        "id": "redmond-snoqualmie-eb",
        "name": "Redmond to Snoqualmie Pass",
        "origin": "Redmond, WA 98052",
        "destination": "Snoqualmie Pass, WA"
    },
    {
        "id": "snoqualmie-redmond-wb",
        "name": "Snoqualmie Pass to Redmond",
        "origin": "Snoqualmie Pass, WA",
        "destination": "Redmond, WA 98052"
    },
    # Mt Baker routes (with waypoints for segment tracking)
    {
        "id": "redmond-mtbaker-eb",
        "name": "Redmond to Mt Baker",
        "origin": "Redmond, WA 98052",
        "destination": "Mt Baker Ski Area, WA",
        "waypoints": [
            {"location": "Everett, WA", "name": "Everett"},
            {"location": "Burlington, WA", "name": "Burlington"},
            {"location": "Glacier, WA", "name": "Glacier"}
        ]
    },
    {
        "id": "mtbaker-redmond-wb",
        "name": "Mt Baker to Redmond",
        "origin": "Mt Baker Ski Area, WA",
        "destination": "Redmond, WA 98052",
        "waypoints": [
            {"location": "Glacier, WA", "name": "Glacier"},
            {"location": "Burlington, WA", "name": "Burlington"},
            {"location": "Everett, WA", "name": "Everett"}
        ]
    },
    # Duvall routes (archived - kept for historical data)
    {
        "id": "duvall-stevens-eb",
        "name": "Duvall to Stevens Pass",
        "origin": "Duvall, WA 98019",
        "destination": "Stevens Pass Ski Area, WA"
    },
    {
        "id": "stevens-duvall-wb",
        "name": "Stevens Pass to Duvall",
        "origin": "Stevens Pass Ski Area, WA",
        "destination": "Duvall, WA 98019"
    },
    {
        "id": "duvall-snoqualmie-eb",
        "name": "Duvall to Snoqualmie Pass",
        "origin": "Duvall, WA 98019",
        "destination": "Snoqualmie Pass, WA"
    },
]

# Archived Routes (not polled, hidden from UI, but data preserved)
ARCHIVED_ROUTES = [
    "duvall-stevens-eb",
    "stevens-duvall-wb",
    "duvall-snoqualmie-eb",
]

# Weather Station Configuration
# SNOTEL AWDB REST API
AWDB_API_URL = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data"

# Weather polling interval (every 15 minutes to catch updates faster)
WEATHER_POLL_INTERVAL_MINUTES = 15

# Stevens Pass weather stations
WEATHER_STATIONS = [
    {
        "id": "snotel-791",
        "name": "SNOTEL 791 - Stevens Pass",
        "triplet": "791:WA:SNTL",
        "elevation": 3940,
        "type": "base"
    }
    # Note: Summit station (Skyline STS52) not yet implemented
    # Will be added when reliable API access is established
]
