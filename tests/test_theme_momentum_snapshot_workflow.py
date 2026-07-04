from __future__ import annotations

from pathlib import Path


def test_theme_momentum_snapshot_workflow_tolerates_repo_rule_push_rejection() -> None:
    workflow = Path(".github/workflows/theme_momentum_snapshot.yml").read_text(encoding="utf-8")

    assert "Push blocked by repository rules; keeping artifact-only output." in workflow
    assert "GH013|repository rule violations|required status check" in workflow
    assert "git push 2>\"${push_log}\"" in workflow
