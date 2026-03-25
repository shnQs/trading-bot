import pytest
import math

from app.services.risk_manager import RiskManager


@pytest.fixture
def rm():
    r = RiskManager()
    r.set_symbol_filters("BTCUSDT", step_size=0.00001, min_notional=10.0)
    return r


def test_position_size_1_pct(rm):
    params = rm.calculate_position("BTCUSDT", current_price=50000.0, available_balance=10000.0)
    assert params is not None
    expected_size = 10000.0 * 0.01  # 1% = 100 USDT
    assert abs(params.position_size_usdt - expected_size) < 1.0


def test_stop_loss_below_entry(rm):
    params = rm.calculate_position("BTCUSDT", current_price=50000.0, available_balance=10000.0)
    assert params.stop_loss < params.entry_price
    assert abs(params.stop_loss - params.entry_price * 0.98) < 1.0


def test_take_profit_above_entry(rm):
    params = rm.calculate_position("BTCUSDT", current_price=50000.0, available_balance=10000.0)
    assert params.take_profit > params.entry_price
    assert abs(params.take_profit - params.entry_price * 1.04) < 1.0


def test_rr_ratio(rm):
    params = rm.calculate_position("BTCUSDT", current_price=50000.0, available_balance=10000.0)
    risk = params.entry_price - params.stop_loss
    reward = params.take_profit - params.entry_price
    ratio = reward / risk
    assert abs(ratio - 2.0) < 0.1  # 2:1 R/R


def test_returns_none_when_below_min_notional(rm):
    # Very small balance -> position too small
    params = rm.calculate_position("BTCUSDT", current_price=50000.0, available_balance=5.0)
    assert params is None


def test_step_size_rounding():
    rm = RiskManager()
    rm.set_symbol_filters("BTCUSDT", step_size=0.001, min_notional=10.0)
    params = rm.calculate_position("BTCUSDT", current_price=50000.0, available_balance=10000.0)
    # Quantity should be a multiple of 0.001
    qty = params.quantity
    remainder = qty % 0.001
    assert remainder < 1e-9


def test_daily_loss_limit_triggered():
    rm = RiskManager()
    assert rm.check_daily_loss_limit(realized_pnl_today=-350.0, total_balance=10000.0) is True


def test_daily_loss_limit_not_triggered():
    rm = RiskManager()
    assert rm.check_daily_loss_limit(realized_pnl_today=-100.0, total_balance=10000.0) is False


def test_daily_loss_limit_positive_pnl():
    rm = RiskManager()
    assert rm.check_daily_loss_limit(realized_pnl_today=200.0, total_balance=10000.0) is False


def test_unknown_symbol_uses_defaults():
    rm = RiskManager()
    params = rm.calculate_position("XYZUSDT", current_price=100.0, available_balance=5000.0)
    assert params is not None
    assert params.quantity > 0
