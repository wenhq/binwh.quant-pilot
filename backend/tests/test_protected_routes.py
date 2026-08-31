"""Router-level auth protection: /data, /indicators, /market_regime all require login.

App DB isolation comes from the global conftest (in-memory SQLite + `client`).
"""
import pytest
from sqlalchemy import delete

from app.database import AsyncSessionLocal
from app.models.user import User

USERNAME = "guarduser"
PASSWORD = "guardpass"


@pytest.fixture(autouse=True)
async def _clean_users():
    yield
    async with AsyncSessionLocal() as session:
        await session.execute(delete(User))
        await session.commit()


async def _register_and_login(client):
    resp = await client.post(
        "/api/auth/register", json={"username": USERNAME, "password": PASSWORD}
    )
    assert resp.status_code == 201
    login = await client.post(
        "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
    )
    assert login.status_code == 200
    # login set the auth cookies in the client jar -> subsequent requests authenticated


async def test_data_etfs_requires_auth(client):
    resp = await client.get("/api/data/etfs")
    assert resp.status_code == 401


async def test_data_sync_requires_auth(client):
    resp = await client.post("/api/data/sync/510300")
    assert resp.status_code == 401


async def test_market_regime_train_requires_auth(client):
    resp = await client.post("/api/market_regime/train/A")
    assert resp.status_code == 401


async def test_indicators_requires_auth(client):
    resp = await client.get("/api/indicators/etf/510300/macd")
    assert resp.status_code == 401


async def test_authenticated_data_etfs_ok(client):
    await _register_and_login(client)
    # cookies persisted in the client jar after login
    resp = await client.get("/api/data/etfs")
    assert resp.status_code == 200
    assert resp.json() == {"etfs": []}


async def test_health_is_public(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
