from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from research_signal_context_pipelines.overlay_backtest import (
    OverlayPolicy,
    PricePoint,
    backtest_overlay,
    exposure_for_signal,
    load_price_history,
    load_signals,
    signal_active_on,
    signal_available_at,
    signal_for_date,
)
from research_signal_context_pipelines.schema import SignalValidationError, validate_signal


ROOT = Path(__file__).resolve().parents[1]


def _example_signal(**overrides: object) -> dict:
    payload = json.loads((ROOT / "examples" / "signal_history" / "2026-02-06.json").read_text(encoding="utf-8"))
    payload.update(overrides)
    return payload


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


def test_signal_active_on_requires_generated_at_not_after_decision_time() -> None:
    signal = _example_signal(
        as_of="2026-02-06",
        generated_at="2026-02-06T22:00:00Z",
        expires_at="2026-03-19",
    )
    morning = dt.datetime(2026, 2, 6, 15, 0, tzinfo=dt.timezone.utc)
    after_hours = dt.datetime(2026, 2, 6, 22, 0, tzinfo=dt.timezone.utc)

    assert signal_active_on(signal, dt.date(2026, 2, 6), decision_time=morning) is False
    assert signal_active_on(signal, dt.date(2026, 2, 6), decision_time=after_hours) is True
    assert signal_active_on(signal, dt.date(2026, 2, 6)) is False
    assert signal_for_date([signal], dt.date(2026, 2, 9))["regime"] == "risk_off"


def test_signal_active_on_uses_available_at_when_present() -> None:
    signal = _example_signal(
        as_of="2026-02-06",
        generated_at="2026-02-05T12:00:00Z",
        available_at="2026-02-06T22:00:00Z",
        expires_at="2026-03-19",
    )
    morning = dt.datetime(2026, 2, 6, 15, 0, tzinfo=dt.timezone.utc)

    assert signal_active_on(signal, dt.date(2026, 2, 6), decision_time=morning) is False
    assert signal_for_date([signal], dt.date(2026, 2, 9)) is not None


def test_signal_available_at_clamps_early_available_at_to_generated_at() -> None:
    signal = _example_signal(
        generated_at="2026-02-20T22:00:00Z",
        available_at="2026-02-06T00:00:00Z",
    )

    assert signal_available_at(signal) == dt.datetime(2026, 2, 20, 22, 0, tzinfo=dt.timezone.utc)


def test_early_available_at_does_not_rewrite_earlier_overlay_path() -> None:
    prices = [
        PricePoint(date=dt.date(2026, 2, 6), close=100.0),
        PricePoint(date=dt.date(2026, 2, 13), close=90.0),
        PricePoint(date=dt.date(2026, 2, 20), close=80.0),
        PricePoint(date=dt.date(2026, 2, 27), close=70.0),
    ]
    late = _example_signal(
        as_of="2026-02-06",
        generated_at="2026-02-20T22:00:00Z",
        expires_at="2026-03-19",
        regime="risk_off",
        confidence=0.9,
        risk_flags=["liquidity_stress"],
    )
    early_available = copy.deepcopy(late)
    early_available["available_at"] = "2026-02-06T00:00:00Z"

    without_signal = backtest_overlay(prices, [])
    with_late = backtest_overlay(prices, [late])
    with_early = backtest_overlay(prices, [early_available])

    # Defense in depth: early available_at must not rewrite pre-generation history.
    assert with_early["overlay"]["final_equity"] == with_late["overlay"]["final_equity"]
    assert with_early["overlay"]["final_equity"] == without_signal["overlay"]["final_equity"]
    assert with_early["overlay"]["avg_exposure"] == without_signal["overlay"]["avg_exposure"]

    with pytest.raises(SignalValidationError, match="available_at must be >= generated_at"):
        validate_signal(early_available)


def test_future_generated_at_does_not_rewrite_earlier_overlay_path() -> None:
    prices = [
        PricePoint(date=dt.date(2026, 2, 6), close=100.0),
        PricePoint(date=dt.date(2026, 2, 13), close=90.0),
        PricePoint(date=dt.date(2026, 2, 20), close=80.0),
        PricePoint(date=dt.date(2026, 2, 27), close=70.0),
    ]
    known = _example_signal(
        as_of="2026-02-06",
        generated_at="2026-02-06T22:00:00Z",
        expires_at="2026-03-19",
        regime="risk_off",
        confidence=0.9,
        risk_flags=["liquidity_stress"],
    )
    future = copy.deepcopy(known)
    future["generated_at"] = "2026-02-20T22:00:00Z"

    without_signal = backtest_overlay(prices, [])
    with_future = backtest_overlay(prices, [future])
    with_known = backtest_overlay(prices, [known])

    # Periods before the future generated_at must match the no-signal path.
    assert with_future["overlay"]["final_equity"] == without_signal["overlay"]["final_equity"]
    assert with_future["overlay"]["total_return"] == without_signal["overlay"]["total_return"]
    assert with_future["overlay"]["avg_exposure"] == without_signal["overlay"]["avg_exposure"]
    # Once available, an unexpired risk-off signal still reduces exposure vs baseline.
    assert with_known["overlay"]["avg_exposure"] < without_signal["overlay"]["avg_exposure"]
    assert with_known["overlay"]["final_equity"] > without_signal["overlay"]["final_equity"]


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
