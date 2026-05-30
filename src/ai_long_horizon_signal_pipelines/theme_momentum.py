from __future__ import annotations

import datetime as dt
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .price_history import PriceRow, parse_price_date
from .theme_universe import SymbolThemeExposure, ThemeDefinition


MOMENTUM_WINDOWS = {
    "return_12_1m": {"lookback": 252, "skip": 21, "weight": 0.40},
    "return_6_1m": {"lookback": 126, "skip": 21, "weight": 0.35},
    "return_3m": {"lookback": 63, "skip": 0, "weight": 0.25},
}
VOLATILITY_PENALTY_WEIGHT = 0.15
DRAWDOWN_PENALTY_WEIGHT = 0.25
BREADTH_BONUS_WEIGHT = 0.10
DEFAULT_TOP_SYMBOLS = 5


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def interval_return(closes: Sequence[float], *, lookback: int, skip: int = 0) -> float | None:
    end_idx = len(closes) - 1 - skip
    start_idx = end_idx - lookback
    if start_idx < 0 or end_idx <= start_idx:
        return None
    base = closes[start_idx]
    end = closes[end_idx]
    if base <= 0:
        return None
    return end / base - 1.0


def realized_volatility(closes: Sequence[float], periods: int = 63) -> float | None:
    if len(closes) <= periods:
        return None
    window = list(closes[-periods - 1 :])
    returns = [window[idx] / window[idx - 1] - 1.0 for idx in range(1, len(window)) if window[idx - 1] > 0]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252)


def trailing_drawdown(closes: Sequence[float], periods: int = 126) -> float | None:
    if len(closes) < 2:
        return None
    window = list(closes[-periods:]) if len(closes) >= periods else list(closes)
    peak = max(window)
    if peak <= 0:
        return None
    return closes[-1] / peak - 1.0


def weighted_available(values: Mapping[str, float | None]) -> float | None:
    weighted_sum = 0.0
    weight_sum = 0.0
    for name, spec in MOMENTUM_WINDOWS.items():
        value = values.get(name)
        if value is None:
            continue
        weight = float(spec["weight"])
        weighted_sum += value * weight
        weight_sum += weight
    if weight_sum == 0:
        return None
    return weighted_sum / weight_sum


def score_from_metrics(metrics: Mapping[str, float | None]) -> float | None:
    momentum = weighted_available(metrics)
    if momentum is None:
        return None
    volatility = metrics.get("realized_vol_63d") or 0.0
    drawdown = abs(min(metrics.get("drawdown_126d") or 0.0, 0.0))
    return momentum - VOLATILITY_PENALTY_WEIGHT * volatility - DRAWDOWN_PENALTY_WEIGHT * drawdown


def symbol_metrics(rows: Sequence[PriceRow]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda item: item.date)
    closes = [row.close for row in ordered]
    metrics: dict[str, float | None] = {}
    for name, spec in MOMENTUM_WINDOWS.items():
        metrics[name] = interval_return(closes, lookback=int(spec["lookback"]), skip=int(spec["skip"]))
    metrics["realized_vol_63d"] = realized_volatility(closes, 63)
    metrics["drawdown_126d"] = trailing_drawdown(closes, 126)
    return {
        "as_of": ordered[-1].date.isoformat(),
        "observations": len(ordered),
        "metrics": metrics,
        "momentum_score": score_from_metrics(metrics),
    }


def average_optional(values: Sequence[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def round_optional(value: float | None, digits: int = 6) -> float | None:
    return round(value, digits) if value is not None else None


def build_theme_momentum_snapshot(
    rows: Sequence[PriceRow],
    *,
    themes: Mapping[str, ThemeDefinition],
    exposures: Mapping[str, SymbolThemeExposure],
    generated_at: dt.datetime | None = None,
    as_of: str | dt.date | None = None,
    top_symbols_per_theme: int = DEFAULT_TOP_SYMBOLS,
) -> dict[str, Any]:
    rows_by_symbol: dict[str, list[PriceRow]] = defaultdict(list)
    as_of_date = parse_price_date(as_of) if as_of else None
    for row in rows:
        if as_of_date and row.date > as_of_date:
            continue
        rows_by_symbol[row.symbol.upper()].append(row)

    symbol_scores = {
        symbol: symbol_metrics(symbol_rows)
        for symbol, symbol_rows in sorted(rows_by_symbol.items())
        if symbol_rows
    }
    latest_dates = [parse_price_date(item["as_of"]) for item in symbol_scores.values()]
    snapshot_as_of = (as_of_date or max(latest_dates)).isoformat() if latest_dates or as_of_date else dt.date.today().isoformat()

    theme_members: dict[str, list[str]] = defaultdict(list)
    for symbol, exposure in exposures.items():
        for theme_id in exposure.theme_ids:
            if theme_id in themes:
                theme_members[theme_id].append(symbol.upper())

    theme_ranks: list[dict[str, Any]] = []
    missing_price_symbols: set[str] = set()
    unranked_themes: list[str] = []
    for theme_id, theme in sorted(themes.items()):
        members = sorted(set(theme_members.get(theme_id, [])))
        priced_members = [symbol for symbol in members if symbol in symbol_scores]
        missing_price_symbols.update(symbol for symbol in members if symbol not in symbol_scores)
        if not priced_members:
            unranked_themes.append(theme_id)
            continue

        metric_averages = {
            name: average_optional([symbol_scores[symbol]["metrics"].get(name) for symbol in priced_members])
            for name in [*MOMENTUM_WINDOWS, "realized_vol_63d", "drawdown_126d"]
        }
        valid_3m = [symbol_scores[symbol]["metrics"].get("return_3m") for symbol in priced_members]
        usable_3m = [value for value in valid_3m if value is not None]
        breadth_3m = sum(1 for value in usable_3m if value > 0) / len(usable_3m) if usable_3m else None
        base_score = score_from_metrics(metric_averages)
        breadth_bonus = BREADTH_BONUS_WEIGHT * ((breadth_3m or 0.5) - 0.5) if base_score is not None else 0.0
        theme_score = base_score + breadth_bonus if base_score is not None else None

        top_symbols = sorted(
            (
                {
                    "symbol": symbol,
                    "momentum_score": round_optional(symbol_scores[symbol]["momentum_score"]),
                    "return_3m": round_optional(symbol_scores[symbol]["metrics"].get("return_3m")),
                    "return_6_1m": round_optional(symbol_scores[symbol]["metrics"].get("return_6_1m")),
                    "return_12_1m": round_optional(symbol_scores[symbol]["metrics"].get("return_12_1m")),
                }
                for symbol in priced_members
            ),
            key=lambda item: (-(item["momentum_score"] if item["momentum_score"] is not None else -999), item["symbol"]),
        )[:top_symbols_per_theme]

        theme_ranks.append(
            {
                "theme_id": theme_id,
                "theme_name": theme.theme_name,
                "sector": theme.sector,
                "horizon": theme.horizon,
                "rank": 0,
                "momentum_score": round_optional(theme_score),
                "breadth_3m": round_optional(breadth_3m),
                "component_count": len(members),
                "priced_symbol_count": len(priced_members),
                "returns": {
                    "3m": round_optional(metric_averages["return_3m"]),
                    "6_1m": round_optional(metric_averages["return_6_1m"]),
                    "12_1m": round_optional(metric_averages["return_12_1m"]),
                },
                "risk": {
                    "realized_vol_63d": round_optional(metric_averages["realized_vol_63d"]),
                    "drawdown_126d": round_optional(metric_averages["drawdown_126d"]),
                },
                "top_symbols": top_symbols,
                "source_policy": theme.source_policy,
            }
        )

    theme_ranks.sort(key=lambda item: (-(item["momentum_score"] if item["momentum_score"] is not None else -999), item["theme_id"]))
    for idx, item in enumerate(theme_ranks, start=1):
        item["rank"] = idx

    taxonomy_versions = sorted({theme.taxonomy_version for theme in themes.values() if theme.taxonomy_version})
    return {
        "schema_version": "1",
        "as_of": snapshot_as_of,
        "generated_at": (generated_at or dt.datetime.now(dt.UTC)).isoformat().replace("+00:00", "Z"),
        "mode": "theme_momentum_snapshot",
        "taxonomy_version": taxonomy_versions[0] if taxonomy_versions else "unknown",
        "methodology": {
            "windows": {
                name: {"lookback_trading_days": spec["lookback"], "skip_recent_trading_days": spec["skip"], "weight": spec["weight"]}
                for name, spec in MOMENTUM_WINDOWS.items()
            },
            "breadth_bonus_weight": BREADTH_BONUS_WEIGHT,
            "volatility_penalty_weight": VOLATILITY_PENALTY_WEIGHT,
            "drawdown_penalty_weight": DRAWDOWN_PENALTY_WEIGHT,
            "theme_membership_source": "static versioned symbol_theme_exposure.csv",
        },
        "summary": {
            "ranked_theme_count": len(theme_ranks),
            "priced_symbol_count": len(symbol_scores),
            "top_theme_ids": [item["theme_id"] for item in theme_ranks[:5]],
        },
        "theme_ranks": theme_ranks,
        "data_quality": {
            "missing_price_symbols": sorted(missing_price_symbols),
            "unranked_themes": sorted(unranked_themes),
        },
        "policy": {
            "execution_allowed": False,
            "portfolio_allocation_allowed": False,
            "theme_rank_is_research_context_only": True,
            "downstream_use": "Theme momentum snapshot for research ranking and replay only; do not route to broker execution.",
        },
    }


def write_theme_momentum_snapshot(snapshot: Mapping[str, Any], path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path
