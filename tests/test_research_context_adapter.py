from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from research_signal_context_pipelines.research_context_adapter import ResearchContextAdapter


class _FakeHeaders:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get_content_type(self) -> str:
        return self._content_type

    def get_content_charset(self, default: str = "utf-8") -> str:
        return default


class _FakeResponse:
    def __init__(self, body: str, content_type: str) -> None:
        self._body = body.encode("utf-8")
        self.headers = _FakeHeaders(content_type)

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_research_context_adapter_respects_whitelist_and_max_entries(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "web_research.json"
    config_path.write_text(
        json.dumps(
            {
                "whitelist": ["https://allowed.example"],
                "sources": [
                    {"url": "https://allowed.example/feed.xml", "kind": "rss"},
                    {"url": "https://blocked.example/news", "kind": "news"},
                ],
            }
        ),
        encoding="utf-8",
    )

    rss_body = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <title>Allowed Feed</title>
        <item>
          <title>First signal</title>
          <description>Alpha summary</description>
          <pubDate>Wed, 01 Jan 2025 12:00:00 GMT</pubDate>
          <link>https://allowed.example/a</link>
        </item>
        <item>
          <title>Second signal</title>
          <description>Beta summary</description>
          <pubDate>Thu, 02 Jan 2025 12:00:00 GMT</pubDate>
          <link>https://allowed.example/b</link>
        </item>
      </channel>
    </rss>
    """

    def fake_urlopen(request, timeout):
        assert timeout == 3.0
        assert request.full_url == "https://allowed.example/feed.xml"
        return _FakeResponse(rss_body, "application/rss+xml; charset=utf-8")

    monkeypatch.setattr("research_signal_context_pipelines.research_context_adapter.urlopen", fake_urlopen)

    context = ResearchContextAdapter(config_path, timeout_seconds=3.0, max_entries=1).build_context(
        pit_timestamp=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    )

    assert context["pit_timestamp"] == "2026-01-01T00:00:00Z"
    assert context["source_count"] == 1
    assert [item["title"] for item in context["research_sources"]] == ["First signal"]
    assert context["research_sources"][0]["url"] == "https://allowed.example/a"
    assert context["research_sources"][0]["published_at"] == "2025-01-01T12:00:00Z"


def test_research_context_adapter_skips_non_whitelisted_sources(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "web_research.json"
    config_path.write_text(
        json.dumps(
            {
                "whitelist": ["https://allowed.example"],
                "sources": [{"url": "https://blocked.example/news", "kind": "news"}],
            }
        ),
        encoding="utf-8",
    )

    def fake_urlopen(request, timeout):  # pragma: no cover - should not be called
        raise AssertionError("blocked source must not be fetched")

    monkeypatch.setattr("research_signal_context_pipelines.research_context_adapter.urlopen", fake_urlopen)

    context = ResearchContextAdapter(config_path, timeout_seconds=3.0, max_entries=3).build_context(
        pit_timestamp=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    )

    assert context["research_sources"] == []
    assert any("skipped non-whitelisted source" in warning for warning in context["warnings"])


def test_research_context_adapter_extracts_html_news(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "web_research.json"
    config_path.write_text(
        json.dumps(
            {
                "whitelist": ["https://news.example"],
                "sources": [{"url": "https://news.example/story", "kind": "news"}],
            }
        ),
        encoding="utf-8",
    )

    html_body = """
    <html>
      <head>
        <title>Breaking research</title>
        <meta name="description" content="Short summary">
        <meta property="article:published_time" content="2026-01-02T03:04:05Z">
      </head>
      <body>
        <p>Fallback summary</p>
      </body>
    </html>
    """

    def fake_urlopen(request, timeout):
        assert timeout == 5.0
        assert request.full_url == "https://news.example/story"
        return _FakeResponse(html_body, "text/html; charset=utf-8")

    monkeypatch.setattr("research_signal_context_pipelines.research_context_adapter.urlopen", fake_urlopen)

    context = ResearchContextAdapter(config_path, timeout_seconds=5.0, max_entries=3).build_context(
        pit_timestamp=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    )

    assert context["source_count"] == 1
    assert context["research_sources"] == [
        {
            "title": "Breaking research",
            "summary": "Short summary",
            "published_at": "2026-01-02T03:04:05Z",
            "url": "https://news.example/story",
            "source_url": "https://news.example/story",
            "source_type": "news",
            "fetched_at": "2026-01-01T00:00:00Z",
        }
    ]
