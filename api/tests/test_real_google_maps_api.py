"""Real integration tests that call actual Google Maps API.

These tests require:
- GOOGLE_MAPS_API_KEY environment variable set
- Routes API enabled in Google Cloud Console
- Billing enabled on the Google Cloud project

Run with: pytest -v -s tests/test_real_google_maps_api.py
Skip in CI with: pytest -v --ignore=tests/test_real_google_maps_api.py
"""
import os
import pytest
import requests
import sys

# Mark all tests in this module as integration tests (skip in CI by default)
pytestmark = pytest.mark.integration

# Add poller to path to access config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../poller'))


@pytest.fixture
def google_api_key():
    """Get Google Maps API key from environment."""
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not api_key or api_key == "your_google_maps_api_key_here":
        pytest.skip("GOOGLE_MAPS_API_KEY not configured")
    return api_key


class TestRealGoogleMapsAPI:
    """Integration tests using real Google Maps Routes API."""

    def test_routes_api_basic_request(self, google_api_key):
        """Test basic Routes API request with simple route."""
        api_url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": google_api_key,
            "X-Goog-FieldMask": "routes.duration,routes.distanceMeters"
        }

        payload = {
            "origin": {"address": "Seattle, WA"},
            "destination": {"address": "Spokane, WA"},
            "travelMode": "DRIVE"
        }

        print(f"\n--- Testing Routes API ---")
        print(f"API URL: {api_url}")
        print(f"Origin: Seattle, WA")
        print(f"Destination: Spokane, WA")

        response = requests.post(api_url, json=payload, headers=headers, timeout=30)

        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        print(f"Response Body: {response.text[:1000]}")

        # Basic assertions
        assert response.status_code in [200, 400, 403], \
            f"Unexpected status code: {response.status_code}"

        if response.status_code == 200:
            data = response.json()
            print(f"\nParsed JSON keys: {list(data.keys())}")

            if "routes" in data:
                print(f"Number of routes: {len(data['routes'])}")
                if len(data['routes']) > 0:
                    route = data['routes'][0]
                    print(f"Route keys: {list(route.keys())}")
                    assert "duration" in route or "distanceMeters" in route
            else:
                print(f"WARNING: No 'routes' key in response")
                print(f"Full response: {data}")

        elif response.status_code == 403:
            pytest.fail("Routes API returned 403 - Check API key permissions and billing")

        elif response.status_code == 400:
            data = response.json()
            print(f"Error response: {data}")
            pytest.fail(f"Routes API returned 400 - Bad request: {data}")

    def test_routes_api_with_stevens_pass(self, google_api_key):
        """Test Routes API with Stevens Pass destination."""
        api_url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": google_api_key,
            "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.staticDuration"
        }

        payload = {
            "origin": {"address": "Duvall, WA 98019"},
            "destination": {"address": "Stevens Pass Ski Area, WA"},
            "travelMode": "DRIVE"
        }

        print(f"\n--- Testing Stevens Pass Route ---")
        print(f"Origin: Duvall, WA")
        print(f"Destination: Stevens Pass Ski Area, WA")

        response = requests.post(api_url, json=payload, headers=headers, timeout=30)

        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Body: {response.text[:1000]}")

        if response.status_code == 200:
            data = response.json()

            if not data or "routes" not in data or len(data.get("routes", [])) == 0:
                print("\n!!! WARNING: API returned empty response or no routes !!!")
                print("This could mean:")
                print("1. Stevens Pass is currently closed/inaccessible")
                print("2. Address geocoding failed")
                print("3. No valid route exists")
                print(f"\nFull response: {data}")
            else:
                print(f"\n✓ Route found!")
                route = data['routes'][0]
                if 'duration' in route:
                    duration_sec = int(route['duration'].rstrip('s'))
                    print(f"Duration: {duration_sec // 60} minutes")
                if 'distanceMeters' in route:
                    distance_miles = route['distanceMeters'] * 0.000621371
                    print(f"Distance: {distance_miles:.1f} miles")

        assert response.status_code == 200, f"API call failed with status {response.status_code}"

    def test_routes_api_different_field_masks(self, google_api_key):
        """Test different field mask combinations to find what works."""
        api_url = "https://routes.googleapis.com/directions/v2:computeRoutes"

        field_masks = [
            "routes.duration,routes.distanceMeters",
            "routes.duration,routes.distanceMeters,routes.staticDuration",
            "routes.legs.duration,routes.legs.distanceMeters",
            "*",  # Request all fields
        ]

        payload = {
            "origin": {"address": "Seattle, WA"},
            "destination": {"address": "Bellevue, WA"},
            "travelMode": "DRIVE"
        }

        for mask in field_masks:
            print(f"\n--- Testing field mask: {mask} ---")

            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": google_api_key,
                "X-Goog-FieldMask": mask
            }

            response = requests.post(api_url, json=payload, headers=headers, timeout=30)
            print(f"Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                if data and "routes" in data and len(data["routes"]) > 0:
                    print(f"✓ Success! Keys returned: {list(data['routes'][0].keys())}")
                else:
                    print(f"✗ Empty response: {data}")
            else:
                print(f"✗ Failed: {response.text[:200]}")
