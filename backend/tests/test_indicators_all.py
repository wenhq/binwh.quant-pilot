"""GET /indicators/{asset}/{code}/all 的实时回退路径回归测试.

背景缺陷：该端点在 indicator_values 表无缓存时会现场计算全部指标，
但 keltner/atr 曾漏 import 导致 NameError → 500（两个独立代理交叉复核确认）。
本测试锁定：db 无缓存时走 realtime 路径必须正常 200 且字段齐全。
"""
import math
from datetime import date, timedelta

import pytest
from sqlalchemy import delete

from app.database import AsyncSessionLocal
from app.models.etf import Etf, EtfDailyKline
from app.models.user import User

USERNAME = "induser"
PASSWORD = "indpass"
CODE = "159915"
N_KLINES = 40  # > macd(26+9) 暖机期，保证尾段指标非空


@pytest.fixture(autouse=True)
async def _clean():
    yield
    async with AsyncSessionLocal() as session:
        await session.execute(delete(User))
        await session.execute(delete(EtfDailyKline))
        await session.execute(delete(Etf))
        await session.commit()


async def _seed_etf_klines():
    async with AsyncSessionLocal() as session:
        etf = Etf(code=CODE, name="创业板ETF", tracks="创业板指")
        session.add(etf)
        await session.flush()
        base = date(2026, 1, 5)  # 周一开始
        for i in range(N_KLINES):
            close = 2.0 + 0.05 * math.sin(i / 5.0) + 0.01 * i
            session.add(EtfDailyKline(
                etf_id=etf.id,
                trade_date=base + timedelta(days=i),
                open=round(close - 0.02, 4),
                high=round(close + 0.05, 4),
                low=round(close - 0.05, 4),
                close=round(close, 4),
                volume=1_000_000 + 1000 * i,
                amount=None,
                adj_factor=None,
            ))
        await session.commit()


async def test_all_indicators_realtime_fallback_ok(client):
    resp = await client.post(
        "/api/auth/register", json={"username": USERNAME, "password": PASSWORD}
    )
    assert resp.status_code == 201
    login = await client.post(
        "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
    )
    assert login.status_code == 200

    await _seed_etf_klines()

    resp = await client.get(f"/api/indicators/etf/{CODE}/all")
    assert resp.status_code == 200
    body = resp.json()
    # indicator_values 未写入 → 必须走实时计算路径而非报错
    assert body["source"] == "realtime"
    data = body["data"]
    assert len(data) == N_KLINES
    # 缺陷回归点：keltner/atr 字段必须存在（曾经 NameError → 500）
    for key in ("keltner_upper", "keltner_mid", "keltner_lower", "atr"):
        assert key in data[-1]
    # 暖机期已过，末行指标应为数值而非 None
    assert data[-1]["atr"] is not None
    assert data[-1]["keltner_mid"] is not None
    assert data[-1]["close"] is not None
