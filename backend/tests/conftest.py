import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["ADMIN_INIT_PASSWORD"] = "test-admin-pw"

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:  # with 触发 lifespan：建表 + seed
        yield c


@pytest.fixture(scope="session")
def admin_headers(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-pw"})
    token = resp.json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}
