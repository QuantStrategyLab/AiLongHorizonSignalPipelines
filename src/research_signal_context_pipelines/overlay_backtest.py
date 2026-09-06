from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .price_history import parse_price_date, read_price_rows
from .schema import validate_signal


@dataclass(frozen=True)
class PricePoint:
    date: dt.date
    close: float


@dataclass(frozen=True)
class OverlayPolicy:
    min_confidence: float = 0.55
    risk_on_exposure: float = 1.0
    mixed_exposure: float = 0.8
    risk_off_exposure: float = 0.5
    severe_flag_exposure: float = 0.6
    severe_flags: tuple[str, ...] = (
        "credit_stress",
        "liquidity_stress",
        "macro_shock",
        "market_structure_stress",
        "earnings_concentration",
    )


def parse_date(value: str) -> dt.date:
    return parse_price_date(value)


def parse_datetime(value: str) -> dt.datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def decision_datetime_for_date(date: dt.date) -> dt.datetime:
    # Date-only replay decisions are treated as start-of-day UTC so same-day
    # after-hours generation cannot affect earlier same-day decisions.
    return dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc)


def signal_available_at(signal: dict[str, Any]) -> dt.datetime:
    raw = signal.get("available_at", signal["generated_at"])
    return parse_datetime(str(raw))


def load_price_history(path: Path, *, symbol: str) -> list[PricePoint]:
    rows = [
        PricePoint(date=row.date, close=row.close)
        for row in read_price_rows(path, symbols=[symbol])
    ]
    if len(rows) < 2:
        raise ValueError(f"price history for {symbol} requires at least two rows")
    return rows


def load_signals(path: Path) -> list[dict[str, Any]]:
    signal_paths = sorted(path.glob("*.json")) if path.is_dir() else [path]
    signals: list[dict[str, Any]] = []
    for signal_path in signal_paths:
        payload = json.loads(signal_path.read_text(encoding="utf-8"))
        validate_signal(payload)
        signals.append(payload)
    signals.sort(key=lambda item: parse_date(str(item["as_of"])))
    return signals


def signal_active_on(
    signal: dict[str, Any],
    date: dt.date,
    *,
    decision_time: dt.datetime | None = None,
) -> bool:
    as_of = parse_date(str(signal["as_of"]))
    expires_at = parse_date(str(signal["expires_at"]))
    if not (as_of <= date <= expires_at):
        return False
    decision = decision_time if decision_time is not None else decision_datetime_for_date(date)
    if decision.tzinfo is None:
        decision = decision.replace(tzinfo=dt.timezone.utc)
    else:
        decision = decision.astimezone(dt.timezone.utc)
    return signal_available_at(signal) <= decision


def signal_for_date(
    signals: list[dict[str, Any]],
    date: dt.date,
    *,
    decision_time: dt.datetime | None = None,
) -> dict[str, Any] | None:
    active = [
        signal
        for signal in signals
        if signal_active_on(signal, date, decision_time=decision_time)
    ]
    return active[-1] if active else None


def exposure_for_signal(signal: dict[str, Any] | None, policy: OverlayPolicy) -> float:
    if signal is None:
        return policy.risk_on_exposure
    confidence = float(signal["confidence"])
    if confidence < policy.min_confidence:
        return policy.risk_on_exposure

    regime = str(signal["regime"])
    if regime == "risk_off":
        exposure = policy.risk_off_exposure
    elif regime == "mixed":
        exposure = policy.mixed_exposure
    else:
        exposure = policy.risk_on_exposure

    risk_flags = {str(flag) for flag in signal.get("risk_flags", [])}
    if risk_flags.intersection(policy.severe_flags):
        exposure = min(exposure, policy.severe_flag_exposure)

    # This overlay is risk-reducing only. It can never increase baseline exposure.
    return max(0.0, min(policy.risk_on_exposure, exposure))


def max_drawdown(equity_curve: list[float]) -> float:
    peak = equity_curve[0]
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def backtest_overlay(
    prices: list[PricePoint],
    signals: list[dict[str, Any]],
    *,
    policy: OverlayPolicy | None = None,
) -> dict[str, Any]:
    policy = policy or OverlayPolicy()
    baseline_equity = 1.0
    overlay_equity = 1.0
    baseline_curve = [baseline_equity]
    overlay_curve = [overlay_equity]
    exposures: list[float] = []
    turnover = 0.0
    previous_exposure = policy.risk_on_exposure

    for previous, current in zip(prices, prices[1:]):
        exposure = exposure_for_signal(signal_for_date(signals, previous.date), policy)
        daily_return = current.close / previous.close - 1.0
        baseline_equity *= 1.0 + daily_return
        overlay_equity *= 1.0 + exposure * daily_return
        baseline_curve.append(baseline_equity)
        overlay_curve.append(overlay_equity)
        exposures.append(exposure)
        turnover += abs(exposure - previous_exposure)
        previous_exposure = exposure

    avg_exposure = sum(exposures) / len(exposures) if exposures else policy.risk_on_exposure
    return {
        "periods": len(prices) - 1,
        "start_date": prices[0].date.isoformat(),
        "end_date": prices[-1].date.isoformat(),
        "baseline": {
            "final_equity": baseline_equity,
            "total_return": baseline_equity - 1.0,
            "max_drawdown": max_drawdown(baseline_curve),
        },
        "overlay": {
            "final_equity": overlay_equity,
            "total_return": overlay_equity - 1.0,
            "max_drawdown": max_drawdown(overlay_curve),
            "avg_exposure": avg_exposure,
            "turnover": turnover,
        },
        "policy": {
            "min_confidence": policy.min_confidence,
            "risk_on_exposure": policy.risk_on_exposure,
            "mixed_exposure": policy.mixed_exposure,
            "risk_off_exposure": policy.risk_off_exposure,
            "severe_flag_exposure": policy.severe_flag_exposure,
            "severe_flags": list(policy.severe_flags),
        },
    }
