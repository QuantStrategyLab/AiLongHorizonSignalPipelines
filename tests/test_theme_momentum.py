from __future__ import annotations

import datetime as dt

from research_signal_context_pipelines.price_history import PriceRow
from research_signal_context_pipelines.theme_momentum import build_theme_momentum_snapshot
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
