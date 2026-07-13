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
THEME_MOMENTUM_ARTIFACT_TYPE = "medium_horizon_theme_context"
THEME_MOMENTUM_HORIZON = "medium"
THEME_MOMENTUM_HORIZON_WINDOW = "2-12 weeks"
THEME_MOMENTUM_HORIZON_WINDOW_ZH = "2-12周"
THEME_MOMENTUM_MODEL_VERSION = "theme-momentum-v1"
THEME_MOMENTUM_SCORING_VERSION = "theme-momentum-rules-v1"
THEME_MOMENTUM_EXPIRY_DAYS = 84


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
    exposure_symbols = sorted({symbol.upper() for symbol in exposures})
    priced_exposure_symbols = [symbol for symbol in exposure_symbols if symbol in symbol_scores]
    insufficient_history_symbols = sorted(
        symbol for symbol in priced_exposure_symbols if symbol_scores[symbol]["momentum_score"] is None
    )
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
        "schema_version": "2",
        "as_of": snapshot_as_of,
        "generated_at": (generated_at or dt.datetime.now(dt.UTC)).isoformat().replace("+00:00", "Z"),
        "expires_at": (parse_price_date(snapshot_as_of) + dt.timedelta(days=THEME_MOMENTUM_EXPIRY_DAYS)).isoformat(),
        "model_version": THEME_MOMENTUM_MODEL_VERSION,
        "scoring_version": THEME_MOMENTUM_SCORING_VERSION,
        "mode": "theme_momentum_snapshot",
        "artifact_type": THEME_MOMENTUM_ARTIFACT_TYPE,
        "horizon": THEME_MOMENTUM_HORIZON,
        "horizon_window": THEME_MOMENTUM_HORIZON_WINDOW,
        "horizon_window_label": THEME_MOMENTUM_HORIZON_WINDOW_ZH,
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
            "gate": {
                "status": "pass",
                "allow_downstream_recommendation": True,
                "reasons": [],
            },
            "coverage": {
                "configured_symbol_count": len(exposure_symbols),
                "priced_symbol_count": len(priced_exposure_symbols),
                "price_coverage_ratio": round_optional(
                    len(priced_exposure_symbols) / len(exposure_symbols) if exposure_symbols else None
                ),
                "insufficient_history_symbol_count": len(insufficient_history_symbols),
            },
            "missing_price_symbols": sorted(missing_price_symbols),
            "insufficient_history_symbols": insufficient_history_symbols,
            "unranked_themes": sorted(unranked_themes),
        },
        "policy": {
            "execution_allowed": False,
            "portfolio_allocation_allowed": False,
            "theme_rank_is_research_context_only": True,
            "downstream_use": "Medium-horizon theme context for research ranking and replay only; do not route to broker execution.",
        },
    }


def validate_theme_momentum_snapshot(
    snapshot: Mapping[str, Any],
    *,
    reference_date: dt.date | None = None,
    compatibility: bool = True,
    check_freshness: bool = False,
    require_gate: bool = False,
    allow_expired: bool = False,
) -> None:
    """Validate the stable metadata and core shape of v1/v2 theme artifacts."""
    required = ("schema_version", "as_of", "generated_at", "mode", "artifact_type", "theme_ranks", "data_quality", "policy")
    missing = [key for key in required if key not in snapshot]
    if missing:
        raise ValueError(f"theme momentum snapshot missing required keys: {', '.join(missing)}")
    schema_version = str(snapshot["schema_version"])
    if schema_version not in {"1", "2"}:
        raise ValueError("theme momentum snapshot schema_version must be '1' or '2'")
    if schema_version == "1" and not compatibility:
        raise ValueError("schema 1 theme momentum snapshots require explicit compatibility=True")
    if snapshot["mode"] != "theme_momentum_snapshot":
        raise ValueError("theme momentum snapshot mode is invalid")
    if snapshot["artifact_type"] != THEME_MOMENTUM_ARTIFACT_TYPE:
        raise ValueError("theme momentum snapshot artifact_type is invalid")
    parse_price_date(snapshot["as_of"])
    generated_at = snapshot["generated_at"]
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise ValueError("theme momentum snapshot generated_at must be an ISO datetime")
    normalized_generated_at = generated_at[:-1] + "+00:00" if generated_at.endswith("Z") else generated_at
    try:
        dt.datetime.fromisoformat(normalized_generated_at)
    except ValueError as exc:
        raise ValueError("theme momentum snapshot generated_at must be an ISO datetime") from exc
    if schema_version == "2":
        for key in ("expires_at", "model_version", "scoring_version"):
            if not isinstance(snapshot.get(key), str) or not snapshot[key].strip():
                raise ValueError(f"theme momentum snapshot {key} must be a non-empty string")
        expires_at = parse_price_date(snapshot["expires_at"])
        as_of = parse_price_date(snapshot["as_of"])
        if expires_at < as_of:
            raise ValueError("theme momentum snapshot expires_at must not be before as_of")
        if check_freshness and reference_date and expires_at < reference_date and not allow_expired:
            raise ValueError(f"theme momentum snapshot expired on {expires_at.isoformat()}")
    if not isinstance(snapshot["theme_ranks"], list) or not isinstance(snapshot["data_quality"], Mapping):
        raise ValueError("theme momentum snapshot core shape is invalid")
    if require_gate:
        gate = snapshot["data_quality"].get("gate")
        if not isinstance(gate, Mapping):
            raise ValueError("theme momentum snapshot data_quality.gate is required")
        if gate.get("status") not in {"pass", "blocked"}:
            raise ValueError("theme momentum snapshot data_quality.gate.status is invalid")
        if not isinstance(gate.get("allow_downstream_recommendation"), bool):
            raise ValueError("theme momentum snapshot data_quality.gate.allow_downstream_recommendation must be boolean")
        if not isinstance(gate.get("reasons"), list):
            raise ValueError("theme momentum snapshot data_quality.gate.reasons must be a list")
        if gate["status"] != ("pass" if gate["allow_downstream_recommendation"] else "blocked"):
            raise ValueError("theme momentum snapshot data_quality.gate is inconsistent")


def write_theme_momentum_snapshot(snapshot: Mapping[str, Any], path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path
