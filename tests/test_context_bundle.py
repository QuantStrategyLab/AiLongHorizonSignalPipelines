from __future__ import annotations

import datetime as dt

from ai_long_horizon_signal_pipelines.context_bundle import (
    build_context_bundle,
    build_error_context_bundle,
    build_context_from_source,
    normalize_yahoo_chart_payload,
)
from ai_long_horizon_signal_pipelines.price_history import PriceRow


def test_build_context_bundle_classifies_trend_and_preserves_shadow_boundary() -> None:
    rows = [
        PriceRow(date=dt.date(2025, 1, 1) + dt.timedelta(days=idx), symbol="QQQ", close=100 + idx)
        for idx in range(260)
    ]

    bundle = build_context_bundle(rows, symbols=["QQQ"], generated_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))

    assert bundle["as_of"] == "2025-09-17"
    assert bundle["existing_strategy_context"]["ai_may_place_orders"] is False
    assert bundle["data_quality"]["synthetic"] is False
    assert bundle["price_context"]["QQQ"]["trend"] == "above_200d"
    assert bundle["price_context"]["QQQ"]["returns"]["21d"] is not None


def test_normalize_yahoo_chart_payload_uses_adjusted_close() -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1767312000],
                    "indicators": {
                        "quote": [{"close": [100.0]}],
                        "adjclose": [{"adjclose": [50.0]}],
                    },
                }
            ],
            "error": None,
        }
    }

    rows = normalize_yahoo_chart_payload(payload, symbol="QQQ")

    assert rows == [PriceRow(date=dt.date(2026, 1, 2), symbol="QQQ", close=50.0)]


def test_build_context_from_source_accepts_fake_downloader() -> None:
    def fake_fetch(symbol, *, start, end=None):
        return {
            "chart": {
                "result": [
                    {
                        "timestamp": [1767312000, 1767571200],
                        "indicators": {"adjclose": [{"adjclose": [100.0, 101.0]}]},
                    }
                ],
                "error": None,
            }
        }

    bundle = build_context_from_source(
        symbols=["QQQ"],
        start_date="2026-01-01",
        end_date="2026-01-06",
        fetch_fn=fake_fetch,
    )

    assert bundle["as_of"] == "2026-01-05"
    assert bundle["price_context"]["QQQ"]["latest_close"] == 101.0


def test_build_error_context_bundle_keeps_shadow_boundary() -> None:
    bundle = build_error_context_bundle(
        symbols=["QQQ"],
        error="RuntimeError: data source unavailable",
        as_of_date=dt.date(2026, 1, 2),
        generated_at=dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc),
    )

    assert bundle["as_of"] == "2026-01-02"
    assert bundle["price_context"] == {}
    assert bundle["data_quality"]["errors"] == ["RuntimeError: data source unavailable"]
    assert bundle["existing_strategy_context"]["ai_may_place_orders"] is False
