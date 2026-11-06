"""Route definitions. No dotenv here: api/main.py imports this, and the API
process must not load .env (it holds the Google Maps key)."""

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
    "redmond-snoqualmie-eb",
    "snoqualmie-redmond-wb",
    "redmond-mtbaker-eb",
    "mtbaker-redmond-wb",
]
