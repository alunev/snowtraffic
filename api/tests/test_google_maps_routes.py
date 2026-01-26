"""Tests to verify Google Maps route data structure."""
import pytest


class TestGoogleMapsRoutes:
    """Tests specific to Google Maps API route structure."""

    def test_routes_use_google_maps_ids(self, client):
        """Test that routes use Google Maps route ID format."""
        response = client.get("/routes")
        data = response.json()

        # Verify we have routes
        assert len(data) > 0

        # Print actual routes for verification
        print("\nActual routes in test database:")
        for route in data:
            print(f"  ID: {route['route_id']} - {route['route_name']}")

        # Check that we have the expected Google Maps routes
        route_ids = [r["route_id"] for r in data]
        expected_ids = ["redmond-stevens-eb", "stevens-redmond-wb"]

        for expected_id in expected_ids:
            assert expected_id in route_ids, f"Expected route ID '{expected_id}' not found"

    def test_route_names_match_google_maps_format(self, client):
        """Test that route names follow Google Maps origin-destination format."""
        response = client.get("/routes")
        data = response.json()

        # Verify route names contain expected locations
        route_names = [r["route_name"] for r in data]

        # Should have routes with these location names
        assert any("Redmond" in name or "Duvall" in name for name in route_names)
        assert any("Stevens Pass" in name for name in route_names)

    def test_current_status_returns_google_maps_routes(self, client):
        """Test that current status includes Google Maps routes."""
        response = client.get("/current")
        data = response.json()

        assert len(data) > 0

        # Print current status for verification
        print("\nCurrent status data:")
        for status in data:
            print(f"  {status['route_id']}: {status['route_name']}")
            print(f"    Current: {status['current_min']}min, Average: {status['average_min']}min")

        # Verify we have at least one route with our expected IDs
        route_ids = [s["route_id"] for s in data]
        assert any(rid in ["redmond-stevens-eb", "stevens-redmond-wb"]
                  for rid in route_ids)
