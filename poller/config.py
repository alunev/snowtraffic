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
# 30 minutes with 2 routes (Stevens only) = ~2,880 requests/month = $0 (under 5k free tier)
POLL_INTERVAL_MINUTES = 30

# Route lists live in routes.py (dotenv-free, so the API can import them)
from routes import ROUTES, ARCHIVED_ROUTES  # noqa: F401 (re-export)

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
