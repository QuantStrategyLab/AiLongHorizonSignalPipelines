"""Research signal context artifact helpers."""

from .artifact_io import DEFAULT_MAX_ARTIFACT_BYTES, read_bounded_artifact_bytes
from .overlay_backtest import OverlayPolicy, backtest_overlay
from .context_bundle import DEFAULT_UNIVERSE, build_context_bundle, build_context_from_source
from .price_history import PriceExtractionSummary, write_filtered_price_history
from .schema import SignalValidationError, validate_signal
from .theme_momentum import (
    build_theme_momentum_snapshot,
    validate_theme_momentum_snapshot,
    write_theme_momentum_snapshot,
)
from .theme_universe import build_theme_context, load_symbol_theme_exposure, load_theme_taxonomy

__all__ = [
    "OverlayPolicy",
    "PriceExtractionSummary",
    "SignalValidationError",
    "DEFAULT_UNIVERSE",
    "DEFAULT_MAX_ARTIFACT_BYTES",
    "backtest_overlay",
    "build_context_bundle",
    "build_context_from_source",
    "build_theme_context",
    "build_theme_momentum_snapshot",
    "load_symbol_theme_exposure",
    "load_theme_taxonomy",
    "read_bounded_artifact_bytes",
    "validate_signal",
    "validate_theme_momentum_snapshot",
    "write_filtered_price_history",
    "write_theme_momentum_snapshot",
]
