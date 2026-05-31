from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ThemeDefinition:
    taxonomy_version: str
    theme_id: str
    theme_name: str
    sector: str
    horizon: str
    description: str
    source_policy: str


@dataclass(frozen=True)
class SymbolThemeExposure:
    symbol: str
    theme_ids: tuple[str, ...]
    exposure_confidence: str
    rationale: str


def _split_theme_ids(value: str) -> tuple[str, ...]:
    theme_ids: list[str] = []
    for raw in str(value or "").replace(",", ";").split(";"):
        theme_id = raw.strip()
        if theme_id and theme_id not in theme_ids:
            theme_ids.append(theme_id)
    if not theme_ids:
        raise ValueError("theme_ids must not be empty")
    return tuple(theme_ids)


def load_theme_taxonomy(path: str | Path) -> dict[str, ThemeDefinition]:
    themes: dict[str, ThemeDefinition] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            theme_id = row.get("theme_id", "").strip()
            if not theme_id:
                raise ValueError("theme taxonomy row is missing theme_id")
            if theme_id in themes:
                raise ValueError(f"duplicate theme_id: {theme_id}")
            themes[theme_id] = ThemeDefinition(
                taxonomy_version=row.get("taxonomy_version", "").strip(),
                theme_id=theme_id,
                theme_name=row.get("theme_name", "").strip(),
                sector=row.get("sector", "").strip(),
                horizon=row.get("horizon", "").strip(),
                description=row.get("description", "").strip(),
                source_policy=row.get("source_policy", "").strip(),
            )
    if not themes:
        raise ValueError("theme taxonomy must contain at least one theme")
    versions = {theme.taxonomy_version for theme in themes.values() if theme.taxonomy_version}
    if len(versions) > 1:
        raise ValueError(f"theme taxonomy has multiple versions: {', '.join(sorted(versions))}")
    return themes


def load_symbol_theme_exposure(
    path: str | Path,
    *,
    known_theme_ids: Iterable[str] | None = None,
) -> dict[str, SymbolThemeExposure]:
    known = set(known_theme_ids or [])
    exposures: dict[str, SymbolThemeExposure] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            symbol = row.get("symbol", "").strip().upper()
            if not symbol:
                raise ValueError("symbol theme exposure row is missing symbol")
            theme_ids = _split_theme_ids(row.get("theme_ids", ""))
            unknown = sorted(theme_id for theme_id in theme_ids if known and theme_id not in known)
            if unknown:
                raise ValueError(f"{symbol} references unknown theme ids: {', '.join(unknown)}")
            exposures[symbol] = SymbolThemeExposure(
                symbol=symbol,
                theme_ids=theme_ids,
                exposure_confidence=row.get("exposure_confidence", "").strip() or "unknown",
                rationale=row.get("rationale", "").strip(),
            )
    if not exposures:
        raise ValueError("symbol theme exposure must contain at least one symbol")
    return exposures


def build_theme_context(
    *,
    symbols: Iterable[str],
    themes: Mapping[str, ThemeDefinition],
    exposures: Mapping[str, SymbolThemeExposure],
) -> dict[str, Any]:
    normalized_symbols = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
    requested = list(dict.fromkeys(normalized_symbols))
    covered = {symbol: exposures[symbol] for symbol in requested if symbol in exposures}
    missing = [symbol for symbol in requested if symbol not in covered]
    taxonomy_versions = sorted({theme.taxonomy_version for theme in themes.values() if theme.taxonomy_version})
    return {
        "taxonomy_version": taxonomy_versions[0] if taxonomy_versions else "unknown",
        "themes": {
            theme_id: {
                "name": theme.theme_name,
                "sector": theme.sector,
                "horizon": theme.horizon,
                "description": theme.description,
                "source_policy": theme.source_policy,
            }
            for theme_id, theme in sorted(themes.items())
        },
        "symbol_theme_exposure": {
            symbol: list(exposure.theme_ids) for symbol, exposure in sorted(covered.items())
        },
        "symbol_theme_metadata": {
            symbol: {
                "exposure_confidence": exposure.exposure_confidence,
                "rationale": exposure.rationale,
            }
            for symbol, exposure in sorted(covered.items())
        },
        "coverage": {
            "requested_symbol_count": len(requested),
            "covered_symbol_count": len(covered),
            "missing_symbols": missing,
        },
        "anti_overfit_policy": {
            "theme_membership_is_static_research_context": True,
            "recent_heat_does_not_change_membership": True,
            "theme_bias_requires_point_in_time_artifact": True,
            "ai_output_remains_shadow_only": True,
        },
    }
