from __future__ import annotations

from ict_trader.execution.risk import RiskEngine, position_size


def test_position_size_basic():
    # NQ point value $20, stop 10 points -> $200 risk/contract; budget $250 -> 1 contract
    assert position_size(per_trade_usd=250, stop_distance_points=10,
                         point_value=20, max_contracts=5) == 1
    # budget $650 -> 3 contracts
    assert position_size(per_trade_usd=650, stop_distance_points=10,
                         point_value=20, max_contracts=5) == 3


def test_position_size_capped_and_zero():
    assert position_size(per_trade_usd=10000, stop_distance_points=10,
                         point_value=20, max_contracts=2) == 2
    assert position_size(per_trade_usd=50, stop_distance_points=10,
                         point_value=20, max_contracts=5) == 0  # can't afford one
    assert position_size(per_trade_usd=250, stop_distance_points=0,
                         point_value=20, max_contracts=5) == 0


def test_daily_loss_limit_halts():
    r = RiskEngine(per_trade_usd=250, daily_loss_limit_usd=500, max_concurrent_positions=1)
    ok, _ = r.can_enter()
    assert ok
    r.on_open()
    r.on_close(-300)
    assert r.halted is False  # 300 < 500
    r.on_open()
    r.on_close(-250)  # cumulative 550 >= 500
    assert r.halted is True
    ok, reason = r.can_enter()
    assert ok is False and "halt" in reason


def test_max_concurrent():
    r = RiskEngine(max_concurrent_positions=1)
    r.on_open()
    ok, reason = r.can_enter()
    assert ok is False and "concurrent" in reason
