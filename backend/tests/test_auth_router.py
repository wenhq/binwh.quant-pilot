"""U2 tests: /auth/* endpoints + get_current_user dependency.

Uses a shared in-memory SQLite engine across all tests via module-scoped fixtures,
then resets state per test with a helper.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.user import User
from app.services.auth.security import hash_password
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.database import Base


@pytest.fixture(scope="module")
def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    return engine


@pytest.fixture(scope="module", autouse=True)
async def create_tables(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(scope="module")
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def session(session_factory):
    session = session_factory()
    async with session.begin():
        pass
    yield session
    await session.close()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed_user(session, username="testuser", password="testpass"):
    user = User(username=username, hashed_password=hash_password(password), is_active=True)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def test_register_success(client, session):
    await _seed_user(session, "existing")
    resp = await client.post("/api/auth/register", json={"username": "newuser", "password": "newpass"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "newuser"
    assert "id" in body


async def test_register_duplicate_username(client, session):
    await _seed_user(session, "testuser")
    resp = await client.post("/api/auth/register", json={"username": "testuser", "password": "pass"})
    assert resp.status_code == 400
    assert "用户名已存在" in resp.json()["detail"]


async def test_login_success(client, session):
    await _seed_user(session)
    resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    assert resp.status_code == 200
    assert "access_token" in resp.cookies
    assert "refresh_token" in resp.cookies


async def test_login_wrong_password(client, session):
    await _seed_user(session)
    resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "wrong"})
    assert resp.status_code == 400


async def test_login_nonexistent_user(client, session):
    resp = await client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 400


async def test_me_with_valid_cookie(client, session):
    await _seed_user(session)
    login = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    cookies = login.cookies
    resp = await client.get("/api/auth/me", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["username"] == "testuser"


async def test_me_without_cookie(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_refresh_success(client, session):
    await _seed_user(session)
    login = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    cookies = login.cookies
    resp = await client.post("/api/auth/refresh", cookies=cookies)
    assert resp.status_code == 200
    assert "access_token" in resp.cookies


async def test_refresh_without_cookie(client):
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401


async def test_logout(client, session):
    await _seed_user(session)
    login = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    cookies = login.cookies
    resp = await client.post("/api/auth/logout", cookies=cookies)
    assert resp.status_code == 200
    me = await client.get("/api/auth/me", cookies=cookies)
    assert me.status_code == 401
