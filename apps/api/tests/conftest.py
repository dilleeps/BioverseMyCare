import os

# Configure before any bioverse import: settings are cached on first read.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://bioverse:bioverse@localhost:5432/bioverse_test"
)
os.environ["BIOVERSE_AI"] = "off"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from bioverse.db import close_pool  # noqa: E402
from bioverse.db.migrate import migrate  # noqa: E402
from bioverse.db.seed import P_MAYA, P_PARK, U_MAYA, U_OKAFOR, U_PARK, seed  # noqa: E402
from bioverse.main import app  # noqa: E402

DB = os.environ["DATABASE_URL"]


@pytest.fixture
def client():
    """A fresh, seeded database for every test."""
    close_pool()
    migrate(DB, reset=True)
    seed(DB)
    with TestClient(app) as c:
        yield c
    close_pool()


def as_user(user_id: str) -> dict:
    return {"X-Bioverse-User": user_id}


MAYA = as_user(U_MAYA)
PARK = as_user(U_PARK)
OKAFOR = as_user(U_OKAFOR)

__all__ = ["MAYA", "PARK", "OKAFOR", "P_MAYA", "P_PARK", "DB"]
