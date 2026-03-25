import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock

from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.anyio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] == "ok"


@pytest.mark.anyio
async def test_bot_status(client):
    resp = await client.get("/api/bot/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "running" in data
    assert "trading_pairs" in data


@pytest.mark.anyio
async def test_trades_empty(client):
    resp = await client.get("/api/trades")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.anyio
async def test_trades_status_filter(client):
    resp = await client.get("/api/trades?status=open")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_ohlcv_unknown_symbol(client):
    resp = await client.get("/api/ohlcv/UNKNOWNUSDT")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_bot_stop(client):
    resp = await client.post("/api/bot/stop")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is False


@pytest.mark.anyio
async def test_config_update(client):
    resp = await client.patch("/api/bot/config", json={"stop_loss_pct": 1.5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["config"]["stop_loss_pct"] == 1.5
