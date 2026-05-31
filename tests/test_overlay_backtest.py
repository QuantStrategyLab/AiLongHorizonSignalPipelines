from __future__ import annotations

import datetime as dt
from pathlib import Path

from research_signal_context_pipelines.overlay_backtest import (
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


def test_load_price_history_accepts_quant_strategy_as_of_schema(tmp_path) -> None:
    prices_path = tmp_path / "prices.csv"
    prices_path.write_text(
        "\n".join(
            [
                "symbol,as_of,close,volume",
                "QQQ,2026-01-02,100,1000",
                "SPY,2026-01-02,90,1000",
                "QQQ,2026-01-05,101,1000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    prices = load_price_history(prices_path, symbol="QQQ")

    assert [price.date.isoformat() for price in prices] == ["2026-01-02", "2026-01-05"]
    assert [price.close for price in prices] == [100.0, 101.0]
