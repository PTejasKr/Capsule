import sys
import os

os.environ["TESTING"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/test_capsule.db"

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pytest
import asyncio

@pytest.fixture(scope="session", autouse=True)
def setup_database():
    from backend.database import init_db
    asyncio.run(init_db())

