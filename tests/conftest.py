"""Pruebas de integración contra un PostgreSQL real (pgserver trae uno embebido: no hace falta instalar nada).

Si prefieres usar tu propio Postgres, define TEST_DATABASE_URL apuntando a una base vacía y desechable
(las pruebas crean datos y no los borran).
"""
import logging
import os
import tempfile

import pytest

logging.raiseExceptions = False  # pgserver escribe en logs ya cerrados al apagar

ADMIN_EMAIL = "admin@test.local"
ADMIN_PASSWORD = "Admin12345"


def _database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    import pgserver

    global _server
    _server = pgserver.get_server(tempfile.mkdtemp(prefix="dh-pg-"), cleanup_mode="stop")
    _server.psql("CREATE DATABASE deploymenthub_test;")
    return _server.get_uri().rsplit("/", 1)[0] + "/deploymenthub_test"


# La configuración se fija ANTES de importar la aplicación (los ajustes se leen una sola vez).
os.environ.update(
    DATABASE_URL=_database_url(),
    JWT_KEY="clave-de-pruebas-de-al-menos-32-bytes-ok!",
    SEED_ADMIN_EMAIL=ADMIN_EMAIL,
    SEED_ADMIN_PASSWORD=ADMIN_PASSWORD,
    ENVIRONMENT="development",
    NOTIFICATIONS_GROUPING_SECONDS="0",
    CORS_ALLOWED_ORIGINS="http://localhost:5173",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.deps import auth_limiter  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    auth_limiter._hits.clear()


def _login(client: TestClient, email: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}


@pytest.fixture(scope="session")
def admin(client):
    return _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)


def _make_user(client, admin, role_code: str, email: str) -> dict:
    roles = client.get("/api/roles", headers=admin).json()
    role_id = next(r["id"] for r in roles if r["name"] == role_code)
    r = client.post(
        "/api/users",
        headers=admin,
        json={"name": role_code.title(), "email": email, "roleId": role_id, "password": "Clave12345"},
    )
    assert r.status_code == 201, r.text
    return _login(client, email, "Clave12345")


@pytest.fixture(scope="session")
def developer(client, admin):
    return _make_user(client, admin, "DEVELOPER", "dev@test.local")


@pytest.fixture(scope="session")
def infra(client, admin):
    return _make_user(client, admin, "INFRA", "infra@test.local")
