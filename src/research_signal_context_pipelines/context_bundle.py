from __future__ import annotations

import datetime as dt
import json
import math
import time
import urllib.error
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from .price_history import PriceRow, parse_price_date, read_price_rows


DEFAULT_UNIVERSE = (
    "SPY",
    "QQQ",
    "SOXX",
    "TQQQ",
    "BIL",
    "BOXX",
    "IWM",
    "DIA",
    "XLF",
    "XLV",
    "XLE",
    "XLI",
    "XLU",
    "XLK",
    "NVDA",
    "AMD",
    "AVGO",
    "TSM",
    "MU",
    "INTC",
    "DELL",
    "SMCI",
    "VRT",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "CRWD",
    "PANW",
    "LMT",
    "RTX",
    "NOC",
    "CVX",
    "XOM",
    "JPM",
    "UNH",
    "NEE",
    "TSLA",
    "COIN",
    "MSTR",
)
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_USER_AGENT = "Mozilla/5.0"


@dataclass(frozen=True)
class SymbolContext:
    symbol: str
    as_of: str
    latest_close: float
    observations: int
    returns: dict[str, float | None]
    sma: dict[str, float | None]
    drawdown_63d: float | None
    realized_vol_21d: float | None
    trend: str
    volatility: str


def normalize_symbols(symbols: str | list[str] | tuple[str, ...]) -> list[str]:
    raw_symbols = symbols.split(",") if isinstance(symbols, str) else list(symbols)
    normalized: list[str] = []
    for symbol in raw_symbols:
        text = str(symbol or "").strip().upper()
        if text and text not in normalized:
            normalized.append(text)
    if not normalized:
        raise ValueError("at least one symbol is required")
    return normalized


def period_timestamp(value: dt.date) -> int:
    return int(dt.datetime.combine(value, dt.time.min, tzinfo=dt.timezone.utc).timestamp())


def fetch_yahoo_chart_payload(symbol: str, *, start: dt.date, end: dt.date | None = None) -> dict[str, Any]:
    end_date = end or dt.date.today()
    period1 = period_timestamp(start)
    period2 = period_timestamp(end_date + dt.timedelta(days=1))
    url = (
        f"{YAHOO_CHART_URL.format(symbol=quote(symbol, safe=''))}"
        f"?period1={period1}&period2={period2}&interval=1d&events=history&includeAdjustedClose=true"
    )
    request = Request(url, headers={"User-Agent": YAHOO_USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed Yahoo Finance chart endpoint.
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
            time.sleep(1.0 + attempt)
        except urllib.error.URLError as exc:
            last_error = exc
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"Yahoo chart download failed for {symbol}: {last_error}") from last_error


def normalize_yahoo_chart_payload(payload: Mapping[str, Any], *, symbol: str) -> list[PriceRow]:
    chart = dict(payload.get("chart") or {})
    error = chart.get("error")
    if error:
        raise RuntimeError(f"Yahoo chart error for {symbol}: {error}")
    result = list(chart.get("result") or [])
    if not result:
        return []
    node = dict(result[0] or {})
    timestamps = list(node.get("timestamp") or [])
    indicators = dict(node.get("indicators") or {})
    adjclose_nodes = list(indicators.get("adjclose") or [])
    adjclose_values = list(dict(adjclose_nodes[0] or {}).get("adjclose") or []) if adjclose_nodes else []
    quote_nodes = list(indicators.get("quote") or [])
    close_values = list(dict(quote_nodes[0] or {}).get("close") or []) if quote_nodes else []

    rows: list[PriceRow] = []
    for idx, raw_ts in enumerate(timestamps):
        close = _indexed_float(adjclose_values, idx)
        if close is None:
            close = _indexed_float(close_values, idx)
        if close is None or close <= 0:
            continue
        row_date = dt.datetime.fromtimestamp(int(raw_ts), tz=dt.timezone.utc).date()
        rows.append(PriceRow(date=row_date, symbol=symbol.upper(), close=close))
    return rows


def _indexed_float(values: list[Any], idx: int) -> float | None:
    if idx >= len(values):
        return None
    value = values[idx]
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def download_price_rows(
    symbols: list[str],
    *,
    start: dt.date,
    end: dt.date | None = None,
    fetch_fn: Callable[..., Mapping[str, Any]] | None = None,
    allow_partial: bool = False,
) -> list[PriceRow]:
    fetch = fetch_fn or fetch_yahoo_chart_payload
    rows: list[PriceRow] = []
    missing: list[str] = []
    failed: list[str] = []
    for symbol in symbols:
        try:
            payload = fetch(symbol, start=start, end=end)
            symbol_rows = normalize_yahoo_chart_payload(payload, symbol=symbol)
        except Exception as exc:
            if not allow_partial:
                raise RuntimeError(f"price download failed for {symbol}: {exc}") from exc
            failed.append(symbol)
            continue
        if not symbol_rows:
            missing.append(symbol)
        rows.extend(symbol_rows)
        time.sleep(0.05)
    unavailable = missing + failed
    if unavailable and not allow_partial:
        raise RuntimeError(f"price download missing symbols: {', '.join(unavailable)}")
    if not rows:
        detail = f" unavailable symbols: {', '.join(unavailable)}" if unavailable else ""
        raise RuntimeError(f"price download produced no usable rows for: {', '.join(symbols)}.{detail}")
    return sorted(rows, key=lambda item: (item.date, item.symbol))


def build_symbol_context(symbol: str, rows: list[PriceRow]) -> SymbolContext:
    if not rows:
        raise ValueError(f"no price rows for {symbol}")
    ordered = sorted(rows, key=lambda item: item.date)
    closes = [row.close for row in ordered]
    latest = ordered[-1]
    sma_50 = moving_average(closes, 50)
    sma_200 = moving_average(closes, 200)
    vol_21 = realized_volatility(closes, 21)
    return SymbolContext(
        symbol=symbol.upper(),
        as_of=latest.date.isoformat(),
        latest_close=latest.close,
        observations=len(ordered),
        returns={
            "5d": trailing_return(closes, 5),
            "21d": trailing_return(closes, 21),
            "63d": trailing_return(closes, 63),
            "126d": trailing_return(closes, 126),
            "252d": trailing_return(closes, 252),
        },
        sma={"50d": sma_50, "200d": sma_200},
        drawdown_63d=trailing_drawdown(closes, 63),
        realized_vol_21d=vol_21,
        trend=classify_trend(latest.close, sma_50, sma_200),
        volatility=classify_volatility(vol_21),
    )


def trailing_return(closes: list[float], periods: int) -> float | None:
    if len(closes) <= periods:
        return None
    base = closes[-periods - 1]
    return closes[-1] / base - 1.0 if base > 0 else None


def moving_average(closes: list[float], periods: int) -> float | None:
    if len(closes) < periods:
        return None
    return sum(closes[-periods:]) / periods


def trailing_drawdown(closes: list[float], periods: int) -> float | None:
    if len(closes) < 2:
        return None
    window = closes[-periods:] if len(closes) >= periods else closes
    peak = max(window)
    return closes[-1] / peak - 1.0 if peak > 0 else None


def realized_volatility(closes: list[float], periods: int) -> float | None:
    if len(closes) <= periods:
        return None
    window = closes[-periods - 1 :]
    returns = [window[idx] / window[idx - 1] - 1.0 for idx in range(1, len(window))]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252)


def classify_trend(close: float, sma_50: float | None, sma_200: float | None) -> str:
    if sma_200 is None:
        return "insufficient_history"
    if close >= sma_200 and (sma_50 is None or sma_50 >= sma_200):
        return "above_200d"
    if close < sma_200 and sma_50 is not None and sma_50 < sma_200:
        return "below_200d"
    return "mixed"


def classify_volatility(volatility: float | None) -> str:
    if volatility is None:
        return "unknown"
    if volatility >= 0.35:
        return "high"
    if volatility >= 0.22:
        return "elevated"
    return "normal"


def build_context_bundle(
    rows: list[PriceRow],
    *,
    symbols: list[str],
    generated_at: dt.datetime | None = None,
    theme_context: Mapping[str, Any] | None = None,
    web_research_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contexts: dict[str, SymbolContext] = {}
    warnings: list[str] = []
    for symbol in symbols:
        symbol_rows = [row for row in rows if row.symbol.upper() == symbol.upper()]
        if not symbol_rows:
            warnings.append(f"missing price history for {symbol.upper()}")
            continue
        contexts[symbol.upper()] = build_symbol_context(symbol, symbol_rows)

    if not contexts:
        raise ValueError("context bundle requires at least one symbol with price history")

    latest_as_of = max(parse_price_date(context.as_of) for context in contexts.values()).isoformat()
    stale_symbols = [
        symbol
        for symbol, context in contexts.items()
        if context.as_of != latest_as_of
    ]
    if stale_symbols:
        warnings.append(f"symbols not updated to latest as_of {latest_as_of}: {', '.join(stale_symbols)}")

    timestamp = generated_at or dt.datetime.now(dt.timezone.utc)
    bundle = {
        "schema_version": "1",
        "as_of": latest_as_of,
        "generated_at": timestamp.isoformat().replace("+00:00", "Z"),
        "horizon": "1-3 years",
        "universe": [symbol.upper() for symbol in symbols],
        "price_context": {
            symbol: {
                "as_of": context.as_of,
                "latest_close": round(context.latest_close, 6),
                "observations": context.observations,
                "returns": round_optional_mapping(context.returns),
                "sma": round_optional_mapping(context.sma),
                "drawdown_63d": round_optional(context.drawdown_63d),
                "realized_vol_21d": round_optional(context.realized_vol_21d),
                "trend": context.trend,
                "volatility": context.volatility,
            }
            for symbol, context in contexts.items()
        },
        "existing_strategy_context": {
            "ai_may_place_orders": False,
            "ai_mode": "shadow",
            "downstream_policy_required": True,
        },
        "data_quality": {
            "source": "yahoo_chart_or_operator_price_csv",
            "warnings": warnings,
            "synthetic": False,
        },
        "notes": [
            "Point-in-time context bundle for shadow research only.",
            "This bundle is evidence for AI review, not a trading instruction.",
            "Historical AI judgments must come from saved artifacts, not regenerated prompts.",
        ],
    }
    if theme_context is not None:
        bundle["theme_context"] = dict(theme_context)
    if web_research_context is not None:
        bundle["web_research"] = dict(web_research_context)
    return bundle


def build_error_context_bundle(
    *,
    symbols: list[str],
    error: str,
    as_of_date: dt.date | None = None,
    generated_at: dt.datetime | None = None,
    theme_context: Mapping[str, Any] | None = None,
    web_research_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    as_of = as_of_date or dt.date.today()
    timestamp = generated_at or dt.datetime.now(dt.timezone.utc)
    bundle = {
        "schema_version": "1",
        "as_of": as_of.isoformat(),
        "generated_at": timestamp.isoformat().replace("+00:00", "Z"),
        "horizon": "1-3 years",
        "universe": [symbol.upper() for symbol in symbols],
        "price_context": {},
        "existing_strategy_context": {
            "ai_may_place_orders": False,
            "ai_mode": "shadow",
            "downstream_policy_required": True,
        },
        "data_quality": {
            "source": "yahoo_chart_or_operator_price_csv",
            "warnings": ["context bundle contains no usable price context"],
            "errors": [error],
            "synthetic": False,
        },
        "notes": [
            "Point-in-time context bundle generation failed before market evidence was available.",
            "This is an operator notification input, not a trading instruction.",
        ],
    }
    if theme_context is not None:
        bundle["theme_context"] = dict(theme_context)
    if web_research_context is not None:
        bundle["web_research"] = dict(web_research_context)
    return bundle


def round_optional(value: float | None, digits: int = 6) -> float | None:
    return round(value, digits) if value is not None else None


def round_optional_mapping(values: Mapping[str, float | None]) -> dict[str, float | None]:
    return {key: round_optional(value) for key, value in values.items()}


def build_context_from_source(
    *,
    symbols: list[str],
    prices_path: Path | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    lookback_days: int = 420,
    fetch_fn: Callable[..., Mapping[str, Any]] | None = None,
    theme_context: Mapping[str, Any] | None = None,
    web_research_context: Mapping[str, Any] | None = None,
    allow_partial_downloads: bool = False,
    generated_at: dt.datetime | None = None,
) -> dict[str, Any]:
    end = parse_price_date(end_date) if end_date else dt.date.today()
    start = parse_price_date(start_date) if start_date else end - dt.timedelta(days=int(lookback_days))
    if prices_path is not None:
        rows = read_price_rows(prices_path, symbols=symbols, start_date=start.isoformat(), end_date=end.isoformat())
    else:
        rows = download_price_rows(
            symbols,
            start=start,
            end=end,
            fetch_fn=fetch_fn,
            allow_partial=allow_partial_downloads,
        )
    return build_context_bundle(
        rows,
        symbols=symbols,
        generated_at=generated_at,
        theme_context=theme_context,
        web_research_context=web_research_context,
    )


def write_context_bundle(bundle: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
