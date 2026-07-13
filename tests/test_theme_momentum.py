from __future__ import annotations

import datetime as dt

from research_signal_context_pipelines.price_history import PriceRow
from research_signal_context_pipelines.theme_momentum import (
    build_theme_momentum_snapshot,
    validate_theme_momentum_snapshot,
)
from research_signal_context_pipelines.theme_universe import SymbolThemeExposure, ThemeDefinition


def _trend_rows(symbol: str, *, start_close: float, daily_step: float, days: int = 280) -> list[PriceRow]:
    start = dt.date(2025, 1, 1)
    return [
        PriceRow(date=start + dt.timedelta(days=idx), symbol=symbol, close=start_close + daily_step * idx)
        for idx in range(days)
    ]


def test_theme_momentum_ranks_strong_broad_theme_first() -> None:
    themes = {
        "hbm_memory": ThemeDefinition(
            taxonomy_version="test-v1",
            theme_id="hbm_memory",
            theme_name="HBM and memory",
            sector="technology",
            horizon="6-24 months",
            description="memory theme",
            source_policy="primary evidence required",
        ),
        "energy_security": ThemeDefinition(
            taxonomy_version="test-v1",
            theme_id="energy_security",
            theme_name="Energy security",
            sector="energy",
            horizon="6-24 months",
            description="energy theme",
            source_policy="primary evidence required",
        ),
    }
    exposures = {
        "MU": SymbolThemeExposure("MU", ("hbm_memory",), "high", "memory exposure"),
        "HBM2": SymbolThemeExposure("HBM2", ("hbm_memory",), "medium", "memory exposure"),
        "XOM": SymbolThemeExposure("XOM", ("energy_security",), "high", "energy exposure"),
        "CVX": SymbolThemeExposure("CVX", ("energy_security",), "high", "energy exposure"),
    }
    rows = (
        _trend_rows("MU", start_close=50, daily_step=0.22)
        + _trend_rows("HBM2", start_close=40, daily_step=0.10)
        + _trend_rows("XOM", start_close=100, daily_step=-0.02)
        + _trend_rows("CVX", start_close=90, daily_step=0.00)
    )

    snapshot = build_theme_momentum_snapshot(
        rows,
        themes=themes,
        exposures=exposures,
        generated_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    )

    ranked = snapshot["theme_ranks"]
    assert snapshot["artifact_type"] == "medium_horizon_theme_context"
    assert snapshot["horizon"] == "medium"
    assert snapshot["horizon_window"] == "2-12 weeks"
    assert snapshot["horizon_window_label"] == "2-12周"
    assert ranked[0]["theme_id"] == "hbm_memory"
    assert ranked[0]["rank"] == 1
    assert ranked[0]["breadth_3m"] == 1.0
    assert [item["symbol"] for item in ranked[0]["top_symbols"]] == ["MU", "HBM2"]
    assert ranked[0]["momentum_score"] > ranked[1]["momentum_score"]
    assert snapshot["policy"]["execution_allowed"] is False
    assert snapshot["data_quality"]["coverage"]["price_coverage_ratio"] == 1.0


def test_theme_momentum_records_missing_price_coverage() -> None:
    themes = {
        "ai_server_infrastructure": ThemeDefinition(
            taxonomy_version="test-v1",
            theme_id="ai_server_infrastructure",
            theme_name="AI server",
            sector="technology",
            horizon="6-24 months",
            description="server theme",
            source_policy="primary evidence required",
        )
    }
    exposures = {
        "DELL": SymbolThemeExposure("DELL", ("ai_server_infrastructure",), "high", "server exposure"),
        "SMCI": SymbolThemeExposure("SMCI", ("ai_server_infrastructure",), "high", "server exposure"),
    }
    rows = _trend_rows("DELL", start_close=80, daily_step=0.1)

    snapshot = build_theme_momentum_snapshot(rows, themes=themes, exposures=exposures)

    assert snapshot["data_quality"]["missing_price_symbols"] == ["SMCI"]
    assert snapshot["data_quality"]["coverage"]["configured_symbol_count"] == 2
    assert snapshot["data_quality"]["coverage"]["priced_symbol_count"] == 1
    assert snapshot["data_quality"]["coverage"]["price_coverage_ratio"] == 0.5
    assert snapshot["theme_ranks"][0]["component_count"] == 2
    assert snapshot["theme_ranks"][0]["priced_symbol_count"] == 1
    assert snapshot["data_quality"]["gate"]["allow_downstream_recommendation"] is False
    assert any("missing price symbols" in warning for warning in snapshot["data_quality"]["warnings"])


def test_theme_momentum_emits_freshness_versions_and_data_quality_gate() -> None:
    themes = {
        "ai_compute": ThemeDefinition("test-v1", "ai_compute", "AI", "technology", "6-24 months", "AI", "primary")
    }
    exposures = {"MU": SymbolThemeExposure("MU", ("ai_compute",), "high", "memory")}
    rows = _trend_rows("MU", start_close=10, daily_step=0.5, days=280)

    snapshot = build_theme_momentum_snapshot(
        rows,
        themes=themes,
        exposures=exposures,
        generated_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    )

    assert snapshot["schema_version"]
    assert snapshot["model_version"]
    assert snapshot["scoring_version"]
    assert snapshot["expires_at"] == "2025-12-30"
    assert snapshot["data_quality"]["gate"]["allow_downstream_recommendation"] is False
    assert any("extreme" in warning for warning in snapshot["data_quality"]["warnings"])


def test_historical_as_of_uses_point_in_time_price_coverage_not_wall_clock() -> None:
    themes = {
        "ai_compute": ThemeDefinition("test-v1", "ai_compute", "AI", "technology", "6-24 months", "AI", "primary")
    }
    exposures = {"MU": SymbolThemeExposure("MU", ("ai_compute",), "high", "memory")}
    rows = _trend_rows("MU", start_close=100, daily_step=0.1, days=280)
    as_of = rows[-1].date

    snapshot = build_theme_momentum_snapshot(
        rows,
        themes=themes,
        exposures=exposures,
        as_of=as_of,
        generated_at=dt.datetime(2026, 7, 13, tzinfo=dt.timezone.utc),
    )

    assert not any("stale" in warning for warning in snapshot["data_quality"]["warnings"])


def test_as_of_after_latest_price_uses_lag_gate_instead_of_raising() -> None:
    themes = {
        "ai_compute": ThemeDefinition("test-v1", "ai_compute", "AI", "technology", "6-24 months", "AI", "primary")
    }
    exposures = {"MU": SymbolThemeExposure("MU", ("ai_compute",), "high", "memory")}
    rows = _trend_rows("MU", start_close=100, daily_step=0.1, days=280)
    requested_as_of = rows[-1].date + dt.timedelta(days=2)

    snapshot = build_theme_momentum_snapshot(
        rows,
        themes=themes,
        exposures=exposures,
        as_of=requested_as_of,
    )

    assert snapshot["as_of"] == requested_as_of.isoformat()
    assert not any("stale" in warning for warning in snapshot["data_quality"]["warnings"])


def test_theme_schema_one_requires_explicit_compatibility() -> None:
    snapshot = {
        "schema_version": "1",
        "as_of": "2026-01-01",
        "generated_at": "2026-01-02T00:00:00Z",
        "mode": "theme_momentum_snapshot",
        "artifact_type": "medium_horizon_theme_context",
        "horizon": "medium",
        "theme_ranks": [],
        "data_quality": {},
        "policy": {},
    }

    try:
        validate_theme_momentum_snapshot(snapshot)
    except ValueError as exc:
        assert "compatibility" in str(exc)
    else:
        raise AssertionError("schema 1 must be rejected without compatibility")

    validate_theme_momentum_snapshot(snapshot, compatibility=True)
