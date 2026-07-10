import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["ADMIN_INIT_PASSWORD"] = "test-admin-pw"

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


@pytest.fixture(scope="module")
def client():
    """每个测试模块独立建库，杜绝跨模块数据干扰。"""
    Base.metadata.drop_all(bind=engine)
    with TestClient(app) as c:  # with 触发 lifespan：建表 + seed
        yield c


@pytest.fixture(scope="module")
def admin_headers(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-pw"})
    token = resp.json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}
