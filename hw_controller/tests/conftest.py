"""Shared test fixtures."""

import pytest
from pathlib import Path
from hw_controller.db.database import Database


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory for test data."""
    return tmp_path


@pytest.fixture
def db(tmp_path):
    """Provide an in-memory SQLite database with tables created."""
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    database.create_tables()
    return database
