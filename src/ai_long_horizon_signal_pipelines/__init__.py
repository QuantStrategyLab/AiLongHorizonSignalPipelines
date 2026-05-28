"""Shadow-only long-horizon AI signal artifact helpers."""

from .overlay_backtest import OverlayPolicy, backtest_overlay
from .schema import SignalValidationError, validate_signal

__all__ = ["OverlayPolicy", "SignalValidationError", "backtest_overlay", "validate_signal"]
