from __future__ import annotations

from pathlib import Path


def test_dispatch_shadow_signal_pins_bridge_ref_via_variable() -> None:
    workflow = Path(".github/workflows/dispatch_shadow_signal.yml").read_text(encoding="utf-8")

    assert "BRIDGE_REF: ${{ vars.CODEX_AUDIT_BRIDGE_REF || 'main' }}" in workflow
    assert '"ref": os.environ["BRIDGE_REF"]' in workflow
    assert "QuantStrategyLab/CodexAuditBridge" in workflow
