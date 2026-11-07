import json

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import app, get_db
from app.seed import seed


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "test.db"
    seed(path)
    return path


@pytest.fixture
def conn(db_path):
    c = db.connect(db_path, read_only=True)
    yield c
    c.close()


@pytest.fixture(scope="session")
def client(db_path):
    def _test_db():
        c = db.connect(db_path, read_only=True)
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_db] = _test_db
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def raw():
    def load(name):
        return json.loads((config.DATA_DIR / name).read_text(encoding="utf-8"))

    return {
        "topics": load("topics.json"),
        "users": load("users.json"),
        "circles": load("circles.json"),
        "memberships": load("memberships.json"),
        "activity": load("activity.json"),
    }
