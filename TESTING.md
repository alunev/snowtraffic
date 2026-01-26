# Testing Guide

This document describes the testing strategy and how to run tests for the Snow Traffic.

## Overview

The project uses **pytest** for integration testing of the API endpoints. Tests are designed to verify that all API endpoints work correctly without requiring actual WSDOT API credentials or a production database.

## Test Structure

```
api/
├── tests/
│   ├── __init__.py
│   ├── conftest.py       # Pytest fixtures and configuration
│   └── test_api.py       # Integration tests for API endpoints
└── pytest.ini            # Pytest configuration
```

## Running Tests

### Quick Start

```bash
cd api
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
pytest
```

### Test Commands

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with output from print statements
pytest -s

# Run specific test file
pytest tests/test_api.py

# Run specific test class
pytest tests/test_api.py::TestCurrentStatusEndpoint

# Run specific test function
pytest tests/test_api.py::TestCurrentStatusEndpoint::test_get_current_status_returns_list

# Run tests matching a pattern
pytest -k "current_status"

# Show coverage report (requires pytest-cov)
pip install pytest-cov
pytest --cov=. --cov-report=html
```

## Test Fixtures

The tests use pytest fixtures to create temporary test databases with sample data:

### `test_db` Fixture

Creates a temporary SQLite database with sample travel time data:
- Two routes (101 and 102)
- Multiple time points for testing history
- Recent and older data for testing time range queries

### `empty_db` Fixture

Creates an empty database for testing edge cases when no data exists.

### `client` Fixture

Provides a FastAPI TestClient with the test database configured.

## Test Coverage

The integration tests cover:

### 1. Root Endpoint (`/`)
- Returns API information
- Lists available endpoints

### 2. Routes Endpoint (`/routes`)
- Returns list of tracked routes
- Each route has required fields
- Routes are sorted by name

### 3. Current Status Endpoint (`/current`)
- Returns current status for all routes
- Calculates delta from average correctly
- Contains all required fields

### 4. Current Status by Route (`/current/{route_id}`)
- Returns status for specific route
- Returns 404 for non-existent routes

### 5. History Endpoint (`/history/{route_id}`)
- Returns historical data
- Respects `hours` parameter for time range
- Respects `limit` parameter for result count
- Returns empty list for non-existent routes

### 6. CORS Configuration
- Verifies CORS headers are present

### 7. Error Handling
- 404 for invalid endpoints
- 405 for wrong HTTP methods

## Writing New Tests

### Test Class Structure

```python
class TestYourFeature:
    """Tests for your feature."""

    def test_something(self, client):
        """Test description."""
        response = client.get("/your/endpoint")
        assert response.status_code == 200
        # Add more assertions
```

### Best Practices

1. **Use descriptive test names** - Test names should describe what is being tested
2. **One assertion concept per test** - Tests should verify one thing
3. **Arrange-Act-Assert pattern** - Structure tests clearly:
   ```python
   def test_example(self, client):
       # Arrange - set up test data
       route_id = "101"

       # Act - perform the action
       response = client.get(f"/current/{route_id}")

       # Assert - verify the result
       assert response.status_code == 200
   ```
4. **Test both success and failure cases**
5. **Use fixtures for common setup**

## Continuous Integration

To run tests in CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run tests
  run: |
    cd api
    python -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    pytest -v
```

## Test Data

The test fixtures create realistic sample data:

```python
# Example test data structure
{
    "route_id": "101",
    "route_name": "Seattle to Stevens Pass via US 2",
    "current_min": 90,
    "average_min": 85,
    "recorded_at": "2025-12-28T10:00:00",
    "wsdot_updated_at": "2025-12-28T10:00:00"
}
```

## Debugging Tests

### Print Debug Information

```bash
# Show print statements during test execution
pytest -s

# Show local variables on failures
pytest -l

# Drop into debugger on failures
pytest --pdb
```

### Inspect Test Database

The test fixtures create temporary databases that are automatically cleaned up. To inspect a test database:

1. Modify the fixture to not delete the database
2. Note the path printed by the fixture
3. Use sqlite3 to inspect:
   ```bash
   sqlite3 /path/to/test.db
   .tables
   SELECT * FROM travel_times;
   ```

## Adding More Tests

Future test areas to consider:

1. **Unit tests for poller functions**
   - Test WSDOT API response parsing
   - Test datetime parsing
   - Test route filtering logic

2. **End-to-end tests**
   - Test complete user workflows
   - Test with real database (non-production)

3. **Performance tests**
   - Test API response times
   - Test with large datasets

4. **Security tests**
   - Test for SQL injection
   - Test for XSS vulnerabilities
   - Test rate limiting

## Mocking External Services

If you need to test the poller without hitting the real WSDOT API:

```python
from unittest.mock import patch

def test_poller_with_mock():
    mock_response = {
        "TravelTimeID": "101",
        "Name": "Test Route",
        "CurrentTime": 90,
        "AverageTime": 85
    }

    with patch('requests.get') as mock_get:
        mock_get.return_value.json.return_value = [mock_response]
        # Test your poller logic
```

## Coverage Goals

Target coverage metrics:
- **API endpoints**: 100% (all endpoints tested)
- **Business logic**: 80%+ (core functionality covered)
- **Edge cases**: Key failure modes covered

## Troubleshooting

### Import Errors

If you get import errors, make sure you're in the `api` directory and have activated the virtual environment:
```bash
cd api
source venv/bin/activate
```

### Database Lock Errors

If you get database lock errors, ensure no other processes are using the test database. The fixtures should handle cleanup automatically.

### Missing Dependencies

```bash
pip install -r requirements.txt
```

Make sure all test dependencies (pytest, httpx, etc.) are installed.
