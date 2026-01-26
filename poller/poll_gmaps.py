"""Poll Google Maps Routes API and store data in SQLite."""
import requests
import sqlite3
from datetime import datetime
from config import GOOGLE_MAPS_API_KEY, DB_PATH, ROUTES, ARCHIVED_ROUTES


def fetch_travel_times():
    """Fetch current travel times from Google Maps Routes API."""
    if not GOOGLE_MAPS_API_KEY:
        print("ERROR: GOOGLE_MAPS_API_KEY environment variable not set!")
        print("Get your API key from: https://console.cloud.google.com/apis/credentials")
        return None

    api_url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.staticDuration,routes.polyline,routes.legs"
    }

    results = []

    try:
        for route in ROUTES:
            # Skip archived routes
            if route["id"] in ARCHIVED_ROUTES:
                continue
            # Request route with traffic data
            payload = {
                "origin": {
                    "address": route["origin"]
                },
                "destination": {
                    "address": route["destination"]
                },
                "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE",
                "computeAlternativeRoutes": False,
                "routeModifiers": {
                    "avoidTolls": False,
                    "avoidHighways": False,
                    "avoidFerries": False
                },
                "languageCode": "en-US",
                "units": "IMPERIAL"
            }

            # Add waypoints if route has them (for segment tracking)
            if "waypoints" in route and route["waypoints"]:
                payload["intermediates"] = [
                    {"address": wp["location"]} for wp in route["waypoints"]
                ]

            response = requests.post(api_url, json=payload, headers=headers, timeout=30)

            if response.status_code == 200:
                data = response.json()

                if "routes" in data and len(data["routes"]) > 0:
                    route_data = data["routes"][0]

                    # Extract duration (with traffic)
                    duration_seconds = int(route_data.get("duration", "0s").rstrip("s"))
                    current_min = duration_seconds // 60

                    # Extract static duration (without traffic - baseline)
                    static_duration_seconds = int(route_data.get("staticDuration", "0s").rstrip("s"))
                    average_min = static_duration_seconds // 60

                    # Extract distance
                    distance_meters = route_data.get("distanceMeters", 0)
                    distance_miles = distance_meters * 0.000621371

                    # Extract segment data - all routes have at least one segment
                    segments = []

                    # Extract simple names from origin/destination
                    origin_name = route["origin"].split(",")[0].replace("Ski Area", "").strip()
                    dest_name = route["destination"].split(",")[0].replace("Ski Area", "").strip()

                    if "legs" in route_data and "waypoints" in route and route["waypoints"]:
                        # Multi-segment route with waypoints
                        legs = route_data["legs"]
                        waypoint_names = [origin_name] + [wp["name"] for wp in route["waypoints"]] + [dest_name]

                        for i, leg in enumerate(legs):
                            leg_duration_sec = int(leg.get("duration", "0s").rstrip("s"))
                            leg_duration_min = leg_duration_sec // 60

                            segment_from = waypoint_names[i] if i < len(waypoint_names) else f"Waypoint {i}"
                            segment_to = waypoint_names[i+1] if i+1 < len(waypoint_names) else f"Waypoint {i+1}"

                            segments.append({
                                "from": segment_from,
                                "to": segment_to,
                                "duration_min": leg_duration_min
                            })

                    else:
                        # Single-segment route (no waypoints)
                        segments.append({
                            "from": origin_name,
                            "to": dest_name,
                            "duration_min": current_min
                        })

                    results.append({
                        "route_id": route["id"],
                        "route_name": route["name"],
                        "current_min": current_min,
                        "average_min": average_min,
                        "distance_miles": distance_miles,
                        "origin": route["origin"],
                        "destination": route["destination"],
                        "status": "open",
                        "segments": segments  # Add segments to result
                    })
                else:
                    # Route unavailable (closed road, etc.) - save with null data
                    print(f"WARNING: No routes returned for {route['name']} - marking as CLOSED")
                    results.append({
                        "route_id": route["id"],
                        "route_name": route["name"],
                        "current_min": None,
                        "average_min": None,
                        "distance_miles": None,
                        "origin": route["origin"],
                        "destination": route["destination"],
                        "status": "closed"
                    })
            else:
                print(f"ERROR: API request failed with status {response.status_code}")
                print(f"Response: {response.text}")

    except requests.exceptions.RequestException as e:
        print(f"ERROR fetching travel times: {e}")
        return None
    except Exception as e:
        print(f"ERROR: {e}")
        return None

    return results


def save_to_database(routes):
    """Save travel time data to SQLite database."""
    if not routes:
        print("No routes to save")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    records_added = 0
    segments_added = 0
    current_time = datetime.now()

    for route in routes:
        cursor.execute("""
            INSERT INTO travel_times
            (route_id, route_name, current_min, average_min, recorded_at, wsdot_updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            route["route_id"],
            route["route_name"],
            route["current_min"],
            route["average_min"],
            current_time.isoformat(),
            current_time.isoformat()  # Using recorded_at for consistency
        ))

        records_added += 1

        # Save segment data if available
        if "segments" in route and route["segments"]:
            for i, segment in enumerate(route["segments"]):
                cursor.execute("""
                    INSERT INTO route_segments
                    (route_id, segment_order, segment_from, segment_to, duration_min, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    route["route_id"],
                    i,
                    segment["from"],
                    segment["to"],
                    segment["duration_min"],
                    current_time.isoformat()
                ))
                segments_added += 1

    conn.commit()
    conn.close()

    if segments_added > 0:
        print(f"✓ Saved {records_added} travel time records and {segments_added} segment records to database")
    else:
        print(f"✓ Saved {records_added} travel time records to database")


def main():
    """Main polling function."""
    print(f"[{datetime.now().isoformat()}] Starting Google Maps Routes API poll...")

    # Fetch all routes
    routes = fetch_travel_times()
    if not routes:
        return

    # Display current data
    for route in routes:
        status = route.get("status", "unknown")
        current = route.get("current_min")
        average = route.get("average_min")

        print(f"  {route['route_name']}:")

        if status == "closed" or current is None:
            print(f"    Status: CLOSED (route unavailable)")
        else:
            delta = None
            if current and average and isinstance(current, (int, float)) and isinstance(average, (int, float)):
                delta = current - average

            print(f"    Current: {current} min | Baseline: {average} min", end="")
            if delta is not None:
                print(f" | Delta: {delta:+d} min ({route.get('distance_miles', 0):.1f} miles)")
            else:
                print()

    # Save to database
    save_to_database(routes)

    print(f"[{datetime.now().isoformat()}] Poll complete\n")


if __name__ == "__main__":
    main()
