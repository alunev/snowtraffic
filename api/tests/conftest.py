"""Pytest configuration and fixtures for API tests."""
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="function")
def test_db():
    """Create a temporary test database with sample data."""
    # Create temporary database file
    db_fd, db_path = tempfile.mkstemp(suffix=".db")

    # Initialize database schema
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE travel_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id TEXT NOT NULL,
            route_name TEXT,
            current_min INTEGER,
            average_min INTEGER,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            wsdot_updated_at DATETIME
        )
    """)

    cursor.execute("""
        CREATE INDEX idx_travel_times_route_recorded
        ON travel_times(route_id, recorded_at)
    """)

    # Insert sample data (using Google Maps route structure)
    base_time = datetime.now()
    sample_data = [
        # Route 1 - Redmond to Stevens Pass (Eastbound)
        ("redmond-stevens-eb", "Redmond to Stevens Pass", 90, 85,
         base_time.isoformat(), base_time.isoformat()),
        ("redmond-stevens-eb", "Redmond to Stevens Pass", 92, 85,
         (base_time - timedelta(hours=1)).isoformat(),
         (base_time - timedelta(hours=1)).isoformat()),
        ("redmond-stevens-eb", "Redmond to Stevens Pass", 95, 85,
         (base_time - timedelta(hours=2)).isoformat(),
         (base_time - timedelta(hours=2)).isoformat()),

        # Route 2 - Westbound (return trip)
        ("stevens-redmond-wb", "Stevens Pass to Redmond", 86, 85,
         base_time.isoformat(), base_time.isoformat()),

        # Older data for history testing
        *[
            ("redmond-stevens-eb", "Redmond to Stevens Pass", 85 + i, 85,
             (base_time - timedelta(hours=3+i)).isoformat(),
             (base_time - timedelta(hours=3+i)).isoformat())
            for i in range(10)
        ],
    ]

    cursor.executemany("""
        INSERT INTO travel_times
        (route_id, route_name, current_min, average_min, recorded_at, wsdot_updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, sample_data)

    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    import os
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture(scope="function")
def client(test_db, monkeypatch):
    """Create a test client with mocked database path."""
    # Mock the DB_PATH in the main module
    monkeypatch.setattr("main.DB_PATH", Path(test_db))

    from main import app
    return TestClient(app)


@pytest.fixture
def empty_db():
    """Create an empty test database (for testing when no data exists)."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE travel_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id TEXT NOT NULL,
            route_name TEXT,
            current_min INTEGER,
            average_min INTEGER,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            wsdot_updated_at DATETIME
        )
    """)

    cursor.execute("""
        CREATE INDEX idx_travel_times_route_recorded
        ON travel_times(route_id, recorded_at)
    """)

    conn.commit()
    conn.close()

    yield db_path

    import os
    os.close(db_fd)
    os.unlink(db_path)
