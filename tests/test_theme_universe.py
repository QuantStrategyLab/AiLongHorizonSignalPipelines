from __future__ import annotations

from pathlib import Path

from research_signal_context_pipelines.theme_universe import (
    build_theme_context,
    load_symbol_theme_exposure,
    load_theme_taxonomy,
)


ROOT = Path(__file__).resolve().parents[1]


def test_theme_config_covers_core_cross_sector_symbols() -> None:
    themes = load_theme_taxonomy(ROOT / "config" / "theme_taxonomy.csv")
    exposures = load_symbol_theme_exposure(
        ROOT / "config" / "symbol_theme_exposure.csv",
        known_theme_ids=themes,
    )

    context = build_theme_context(symbols=["MU", "INTC", "DELL", "UNH", "XOM"], themes=themes, exposures=exposures)

    assert context["taxonomy_version"] == "2026-05-31-core-themes-v1"
    assert context["symbol_theme_exposure"]["MU"] == ["hbm_memory", "ai_compute"]
    assert context["symbol_theme_exposure"]["DELL"] == ["ai_server_infrastructure", "ai_compute"]
    assert context["symbol_theme_exposure"]["UNH"] == ["healthcare_policy"]
    assert context["coverage"]["covered_symbol_count"] == 5
    assert context["anti_overfit_policy"]["recent_heat_does_not_change_membership"] is True
