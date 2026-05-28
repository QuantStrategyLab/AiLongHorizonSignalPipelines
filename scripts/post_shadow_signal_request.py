#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_API_URL = "https://api.github.com"
DEFAULT_LABEL = "long-horizon-shadow"


def github_request(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-long-horizon-shadow-signal",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset("utf-8")
        raw = response.read().decode(charset)
        return json.loads(raw) if raw else None


def ensure_label(api_url: str, repo: str, token: str, label: str) -> None:
    encoded = urllib.parse.quote(label, safe="")
    label_url = f"{api_url}/repos/{repo}/labels/{encoded}"
    try:
        github_request("GET", label_url, token)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        github_request(
            "POST",
            f"{api_url}/repos/{repo}/labels",
            token,
            {
                "name": label,
                "color": "5319E7",
                "description": "Long-horizon AI shadow signal request and review",
            },
        )


def find_existing_issue(api_url: str, repo: str, token: str, label: str, title: str) -> dict[str, Any] | None:
    issues = github_request(
        "GET",
        f"{api_url}/repos/{repo}/issues?state=open&labels={urllib.parse.quote(label)}&per_page=100",
        token,
    )
    return next((issue for issue in issues if issue.get("title") == title), None)


def build_issue_title(as_of_date: str) -> str:
    return f"Long-horizon AI shadow signal: {as_of_date}"


def build_issue_body(*, as_of_date: str, source_ref: str, provider: str, bridge_repository: str) -> str:
    return "\n".join(
        [
            "## Long-Horizon Shadow Signal Request",
            "",
            f"- As of date: `{as_of_date}`",
            f"- Source ref: `{source_ref}`",
            f"- Bridge repository: `{bridge_repository}`",
            f"- Provider: `{provider}`",
            "- Mode: `shadow`",
            "- Required output: `data/output/latest_signal.json`",
            "- Historical copy: `data/output/signal_history/YYYY-MM-DD.json` when evidence is sufficient",
            "",
            "## Operator Notification",
            "",
            "This issue is the operator-facing notification for the shadow signal run.",
            "CodexAuditBridge should post its review result here and may open a focused PR",
            "only for schema-valid shadow artifacts.",
            "",
            "## Boundaries",
            "",
            "- AI output must not place orders or change live strategy rules.",
            "- Any downstream use must remain advisory until a deterministic policy consumes the artifact.",
            "- If evidence is insufficient, report findings and leave artifacts unchanged.",
            "",
            "## Context",
            "",
            "Use committed examples, context bundles, and existing shadow artifacts as evidence.",
            "Do not infer historical AI signals that were not generated point-in-time.",
        ]
    )


def upsert_issue(
    *,
    api_url: str,
    repo: str,
    token: str,
    title: str,
    body: str,
    label: str,
) -> tuple[str, int, str]:
    ensure_label(api_url, repo, token, label)
    payload = {"title": title, "body": body, "labels": [label]}
    existing = find_existing_issue(api_url, repo, token, label, title)
    if existing:
        updated = github_request("PATCH", f"{api_url}/repos/{repo}/issues/{existing['number']}", token, payload)
        return "updated", int(updated["number"]), str(updated["html_url"])
    created = github_request("POST", f"{api_url}/repos/{repo}/issues", token, payload)
    return "created", int(created["number"]), str(created["html_url"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or update a long-horizon shadow signal issue.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--source-ref", default="main")
    parser.add_argument("--provider", default="auto")
    parser.add_argument("--bridge-repository", default="QuantStrategyLab/CodexAuditBridge")
    parser.add_argument("--as-of-date", default=dt.date.today().isoformat())
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    return parser.parse_args()


def write_outputs(*, action: str, issue_number: int, issue_url: str, title: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            print(f"issue_action={action}", file=handle)
            print(f"issue_number={issue_number}", file=handle)
            print(f"issue_url={issue_url}", file=handle)
            print(f"issue_title={title}", file=handle)
    print(f"issue_action={action}")
    print(f"issue_number={issue_number}")
    print(f"issue_url={issue_url}")
    print(f"issue_title={title}")


def main() -> int:
    args = parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 1

    title = build_issue_title(args.as_of_date)
    body = build_issue_body(
        as_of_date=args.as_of_date,
        source_ref=args.source_ref,
        provider=args.provider,
        bridge_repository=args.bridge_repository,
    )
    try:
        action, issue_number, issue_url = upsert_issue(
            api_url=args.api_url.rstrip("/"),
            repo=args.repo,
            token=token,
            title=title,
            body=body,
            label=args.label,
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"GitHub API request failed: {exc.code} {detail}", file=sys.stderr)
        return 1

    write_outputs(action=action, issue_number=issue_number, issue_url=issue_url, title=title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
