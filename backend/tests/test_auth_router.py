"""U2 tests: /auth/* endpoints + get_current_user dependency.

DB isolation comes from the global conftest: app.database binds to a shared
in-memory SQLite database, `client` guarantees the tables exist, and the autouse
cleanup below empties the users table after every test so each case starts clean.
"""
import pytest
from sqlalchemy import delete

from app.database import AsyncSessionLocal
from app.models.user import User
from app.services.auth.security import hash_password


@pytest.fixture(autouse=True)
async def _clean_users():
    yield
    async with AsyncSessionLocal() as session:
        await session.execute(delete(User))
        await session.commit()


async def _seed_user(username="testuser", password="testpass"):
    async with AsyncSessionLocal() as session:
        user = User(username=username, hashed_password=hash_password(password), is_active=True)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def test_register_success(client):
    await _seed_user("existing")
    resp = await client.post("/api/auth/register", json={"username": "newuser", "password": "newpass"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "newuser"
    assert "id" in body


async def test_register_duplicate_username(client):
    await _seed_user("testuser")
    resp = await client.post("/api/auth/register", json={"username": "testuser", "password": "testpass"})
    assert resp.status_code == 400
    assert "用户名已存在" in resp.json()["detail"]


async def test_login_success(client):
    await _seed_user()
    resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    assert resp.status_code == 200
    assert "access_token" in resp.cookies
    assert "refresh_token" in resp.cookies


async def test_login_wrong_password(client):
    await _seed_user()
    resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "wrongpass"})
    assert resp.status_code == 400


async def test_login_nonexistent_user(client):
    resp = await client.post("/api/auth/login", json={"username": "nobody", "password": "nopasswd"})
    assert resp.status_code == 400


async def test_me_with_valid_cookie(client):
    await _seed_user()
    login = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    cookies = login.cookies
    resp = await client.get("/api/auth/me", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["username"] == "testuser"


async def test_me_without_cookie(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_refresh_success(client):
    await _seed_user()
    login = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    cookies = login.cookies
    resp = await client.post("/api/auth/refresh", cookies=cookies)
    assert resp.status_code == 200
    assert "access_token" in resp.cookies


async def test_refresh_without_cookie(client):
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401


async def test_logout(client):
    await _seed_user()
    login = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200
    resp = await client.post("/api/auth/logout")
    assert resp.status_code == 200
    # Logout only clears the client-side cookies (stateless JWTs cannot be revoked
    # server-side), so the browser-like flow is: jar emptied -> /me unauthenticated.
    assert "access_token" not in client.cookies
    assert "refresh_token" not in client.cookies
    me = await client.get("/api/auth/me")
    assert me.status_code == 401
