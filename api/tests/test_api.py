"""Integration tests for the Snow Traffic API."""
import pytest


class TestRootEndpoint:
    """Tests for the root endpoint."""

    def test_root_returns_welcome_message(self, client):
        """Test that root endpoint returns API information."""
        response = client.get("/")
        assert response.status_code == 200

        data = response.json()
        assert "message" in data
        assert "endpoints" in data
        assert data["message"] == "Snow Traffic API"

    def test_root_lists_available_endpoints(self, client):
        """Test that root endpoint lists available endpoints."""
        response = client.get("/")
        data = response.json()

        endpoints = data["endpoints"]
        assert "/routes" in endpoints
        assert "/current" in endpoints
        assert "/history/{route_id}" in endpoints


class TestRoutesEndpoint:
    """Tests for the /routes endpoint."""

    def test_get_routes_returns_list(self, client):
        """Test that /routes returns a list of routes."""
        response = client.get("/routes")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_route_contains_required_fields(self, client):
        """Test that each route has required fields."""
        response = client.get("/routes")
        data = response.json()

        for route in data:
            assert "route_id" in route
            assert "route_name" in route
            assert "record_count" in route
            assert "first_recorded" in route
            assert "last_recorded" in route

    def test_routes_sorted_by_name(self, client):
        """Test that routes are returned sorted by name."""
        response = client.get("/routes")
        data = response.json()

        if len(data) > 1:
            route_names = [r["route_name"] for r in data]
            assert route_names == sorted(route_names)


class TestCurrentStatusEndpoint:
    """Tests for the /current endpoint."""

    def test_get_current_status_returns_list(self, client):
        """Test that /current returns a list of current statuses."""
        response = client.get("/current")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_current_status_contains_required_fields(self, client):
        """Test that each status has required fields."""
        response = client.get("/current")
        data = response.json()

        for status in data:
            assert "route_id" in status
            assert "route_name" in status
            assert "current_min" in status
            assert "average_min" in status
            assert "last_updated" in status

    def test_current_status_calculates_delta(self, client):
        """Test that delta is calculated when current and average exist."""
        response = client.get("/current")
        data = response.json()

        # Find a status with both current and average
        for status in data:
            if status["current_min"] and status["average_min"]:
                assert "delta_min" in status
                assert "delta_percent" in status

                # Verify calculation
                expected_delta = status["current_min"] - status["average_min"]
                assert status["delta_min"] == expected_delta

                if status["average_min"] > 0:
                    expected_percent = round(
                        (expected_delta / status["average_min"]) * 100, 1
                    )
                    assert status["delta_percent"] == expected_percent


class TestCurrentStatusByRouteEndpoint:
    """Tests for the /current/{route_id} endpoint."""

    def test_get_current_status_for_existing_route(self, client):
        """Test fetching current status for a specific route."""
        # First get all routes to find a valid route_id
        routes_response = client.get("/routes")
        routes = routes_response.json()
        assert len(routes) > 0

        route_id = routes[0]["route_id"]

        # Fetch status for this route
        response = client.get(f"/current/{route_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["route_id"] == route_id
        assert "route_name" in data
        assert "current_min" in data
        assert "average_min" in data

    def test_get_current_status_for_nonexistent_route(self, client):
        """Test that requesting a non-existent route returns 404."""
        response = client.get("/current/nonexistent_route_999")
        assert response.status_code == 404

        data = response.json()
        assert "detail" in data
        assert data["detail"] == "Route not found"


class TestHistoryEndpoint:
    """Tests for the /history/{route_id} endpoint."""

    def test_get_history_for_existing_route(self, client):
        """Test fetching historical data for a route."""
        # Get a valid route_id
        routes_response = client.get("/routes")
        routes = routes_response.json()
        route_id = routes[0]["route_id"]

        # Fetch history
        response = client.get(f"/history/{route_id}")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_history_record_contains_required_fields(self, client):
        """Test that each history record has required fields."""
        routes_response = client.get("/routes")
        routes = routes_response.json()
        route_id = routes[0]["route_id"]

        response = client.get(f"/history/{route_id}")
        data = response.json()

        for record in data:
            assert "id" in record
            assert "route_id" in record
            assert "route_name" in record
            assert "current_min" in record
            assert "average_min" in record
            assert "recorded_at" in record

    def test_history_with_hours_parameter(self, client):
        """Test that hours parameter filters results correctly."""
        routes_response = client.get("/routes")
        routes = routes_response.json()
        route_id = routes[0]["route_id"]

        # Fetch 1 hour of data
        response_1h = client.get(f"/history/{route_id}?hours=1")
        data_1h = response_1h.json()

        # Fetch 24 hours of data
        response_24h = client.get(f"/history/{route_id}?hours=24")
        data_24h = response_24h.json()

        # 24h should return more or equal records than 1h
        assert len(data_24h) >= len(data_1h)

    def test_history_with_limit_parameter(self, client):
        """Test that limit parameter restricts number of results."""
        routes_response = client.get("/routes")
        routes = routes_response.json()
        route_id = routes[0]["route_id"]

        # Fetch with limit
        limit = 5
        response = client.get(f"/history/{route_id}?limit={limit}")
        data = response.json()

        assert len(data) <= limit

    def test_history_returns_empty_for_nonexistent_route(self, client):
        """Test that non-existent route returns empty list."""
        response = client.get("/history/nonexistent_route_999")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0


class TestCORS:
    """Tests for CORS configuration."""

    def test_cors_headers_present(self, client):
        """Test that CORS headers are present in responses."""
        # CORS headers are only added when there's an Origin header
        response = client.get("/", headers={"Origin": "http://localhost:3000"})

        # Check for CORS headers (configured for specific origins, not wildcard)
        assert "access-control-allow-origin" in response.headers
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


class TestErrorHandling:
    """Tests for error handling."""

    def test_404_for_invalid_endpoint(self, client):
        """Test that invalid endpoints return 404."""
        response = client.get("/invalid/endpoint/path")
        assert response.status_code == 404

    def test_405_for_wrong_method(self, client):
        """Test that wrong HTTP methods return 405."""
        # Try POST on GET-only endpoint
        response = client.post("/routes")
        assert response.status_code == 405
