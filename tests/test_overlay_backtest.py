from __future__ import annotations

import datetime as dt
from pathlib import Path

from ai_long_horizon_signal_pipelines.overlay_backtest import (
    OverlayPolicy,
    backtest_overlay,
    exposure_for_signal,
    load_price_history,
    load_signals,
    signal_for_date,
)


ROOT = Path(__file__).resolve().parents[1]


def test_exposure_for_signal_is_risk_reducing_only() -> None:
    policy = OverlayPolicy()
    assert exposure_for_signal(None, policy) == 1.0
    assert exposure_for_signal({"confidence": 0.3, "regime": "risk_off", "risk_flags": []}, policy) == 1.0
    assert exposure_for_signal({"confidence": 0.8, "regime": "risk_off", "risk_flags": []}, policy) == 0.5
    assert exposure_for_signal({"confidence": 0.8, "regime": "mixed", "risk_flags": ["liquidity_stress"]}, policy) == 0.6
    assert exposure_for_signal({"confidence": 0.8, "regime": "risk_on", "risk_flags": []}, policy) == 1.0


def test_signal_for_date_uses_latest_active_signal() -> None:
    signals = load_signals(ROOT / "examples" / "signal_history")

    assert signal_for_date(signals, dt.date(2026, 1, 10))["regime"] == "risk_on"
    assert signal_for_date(signals, dt.date(2026, 3, 1))["regime"] == "risk_off"
    assert signal_for_date(signals, dt.date(2026, 4, 1))["regime"] == "mixed"
    assert signal_for_date(signals, dt.date(2026, 6, 1)) is None


def test_backtest_overlay_reduces_drawdown_on_synthetic_path() -> None:
    prices = load_price_history(ROOT / "examples" / "price_history.example.csv", symbol="QQQ")
    signals = load_signals(ROOT / "examples" / "signal_history")

    summary = backtest_overlay(prices, signals)

    assert summary["periods"] == len(prices) - 1
    assert summary["baseline"]["max_drawdown"] < 0
    assert summary["overlay"]["max_drawdown"] > summary["baseline"]["max_drawdown"]
    assert 0 < summary["overlay"]["avg_exposure"] <= 1.0
    assert summary["overlay"]["turnover"] > 0
