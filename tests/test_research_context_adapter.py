from __future__ import annotations

import datetime as dt
import json
import importlib.util
import sys

import pytest
from pathlib import Path

from research_signal_context_pipelines.research_context_adapter import ResearchContextAdapter
from research_signal_context_pipelines import research_context_adapter as adapter_module


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    real_datetime = dt.datetime

    class Clock(real_datetime):
        current = real_datetime(2026, 9, 5, 12, tzinfo=dt.timezone.utc)
        observed = []

        @classmethod
        def now(cls, tz=None):
            value = cls.current
            cls.observed.append(value)
            cls.current += dt.timedelta(milliseconds=1)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(adapter_module.dt, "datetime", Clock)
    return Clock


def _config(tmp_path, kind="rss"):
    path = tmp_path / "synthetic_sources.json"
    path.write_text(json.dumps({"whitelist": ["https://synthetic.example"],
                                "sources": [{"url": "https://synthetic.example/source", "kind": kind}]}))
    return path


def _rss(*dates):
    return "<rss><channel>" + "".join(
        f"<item><title>synthetic-{index}</title><pubDate>{date}</pubDate></item>"
        for index, date in enumerate(dates)
    ) + "</channel></rss>"


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


def test_research_context_adapter_respects_whitelist_and_max_entries(tmp_path: Path, monkeypatch, clock) -> None:
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

    context = ResearchContextAdapter(config_path, timeout_seconds=3.0, max_entries=1).build_context()

    assert context["pit_timestamp"] == clock.observed[-1].isoformat().replace("+00:00", "Z")
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

    context = ResearchContextAdapter(config_path, timeout_seconds=3.0, max_entries=3).build_context()

    assert context["research_sources"] == []
    assert any("skipped non-whitelisted source" in warning for warning in context["warnings"])


def test_research_context_adapter_extracts_html_news(tmp_path: Path, monkeypatch, clock) -> None:
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

    context = ResearchContextAdapter(config_path, timeout_seconds=5.0, max_entries=3).build_context()

    assert context["source_count"] == 1
    assert context["research_sources"] == [
        {
            "title": "Breaking research",
            "summary": "Short summary",
            "published_at": "2026-01-02T03:04:05Z",
            "url": "https://news.example/story",
            "source_url": "https://news.example/story",
            "source_type": "news",
            "fetched_at": (clock.observed[0] + dt.timedelta(milliseconds=1)).isoformat().replace("+00:00", "Z"),
        }
    ]


@pytest.mark.parametrize("cutoff", [dt.datetime(2026, 9, 4, tzinfo=dt.timezone.utc), dt.datetime(2026, 9, 4)])
def test_historical_request_is_empty_unsupported_and_does_not_fetch(tmp_path, monkeypatch, cutoff):
    calls = []
    def fetch(*args, **kwargs):
        calls.append(args)
        return _FakeResponse(_rss("2026-09-03T00:00:00Z"), "application/rss+xml")
    monkeypatch.setattr(adapter_module, "urlopen", fetch)
    context = ResearchContextAdapter(_config(tmp_path)).build_context(pit_timestamp=cutoff)
    assert calls == []
    assert context["research_sources"] == []
    assert context["source_count"] == 0
    assert context["pit_timestamp"] == "2026-09-04T00:00:00Z"
    assert any("unsupported" in warning and "saved" in warning for warning in context["warnings"])


def test_current_fetch_timestamps_are_observed_after_response_not_query_start(tmp_path, monkeypatch, clock):
    class DelayedResponse(_FakeResponse):
        def read(self):
            clock.current += dt.timedelta(seconds=1)
            return super().read()

    monkeypatch.setattr(adapter_module, "urlopen", lambda *args, **kwargs: DelayedResponse(
        _rss("2026-09-05T11:59:00Z"), "application/rss+xml"))
    context = ResearchContextAdapter(_config(tmp_path)).build_context()
    assert context["source_count"] == 1
    entry = context["research_sources"][0]
    fetched = dt.datetime.fromisoformat(entry["fetched_at"].replace("Z", "+00:00"))
    cutoff = dt.datetime.fromisoformat(context["pit_timestamp"].replace("Z", "+00:00"))
    assert clock.observed[0] < fetched <= cutoff
    assert fetched == clock.observed[1]


@pytest.mark.parametrize("kind", ["rss", "news"])
@pytest.mark.parametrize("published", ["2026-09-06T00:00:00Z", "invalid", ""])
def test_future_and_unknown_publication_times_are_not_pit_evidence(tmp_path, monkeypatch, kind, published):
    body = _rss(published) if kind == "rss" else f'<html><title>synthetic</title><meta property="article:published_time" content="{published}"></html>'
    monkeypatch.setattr(adapter_module, "urlopen", lambda *args, **kwargs: _FakeResponse(body, "text/html"))
    context = ResearchContextAdapter(_config(tmp_path, kind)).build_context()
    assert context["research_sources"] == []
    assert context["source_count"] == 0
    assert context["warnings"]


def test_future_feed_item_does_not_consume_entry_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter_module, "urlopen", lambda *args, **kwargs: _FakeResponse(
        _rss("2026-09-06T00:00:00Z", "2026-09-04T00:00:00Z"), "application/rss+xml"))
    context = ResearchContextAdapter(_config(tmp_path), max_entries=1).build_context()
    assert [entry["title"] for entry in context["research_sources"]] == ["synthetic-1"]


@pytest.mark.parametrize("end_date,current", [(None, True), ("2026-09-05", True), ("2026-09-06", True), ("2026-09-04", False)])
def test_cli_routes_current_and_explicit_historical_web_without_price_or_artifact_io(tmp_path, monkeypatch, clock, end_date, current):
    script = Path(__file__).resolve().parents[1] / "scripts/build_context_bundle.py"
    spec = importlib.util.spec_from_file_location("synthetic_build_context_cli", script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    calls, captured, written = [], {}, []

    def fetch(*args, **kwargs):
        calls.append(True)
        return _FakeResponse(_rss("2026-09-04T00:00:00Z"), "application/rss+xml")

    def prices(**kwargs):
        captured.update(kwargs)
        return {"as_of": end_date or "2026-09-05", "universe": ["SPY"], "web_research": kwargs["web_research_context"]}

    monkeypatch.setattr(adapter_module, "urlopen", fetch)
    monkeypatch.setattr(cli, "build_context_from_source", prices)
    monkeypatch.setattr(cli, "write_context_bundle", lambda bundle, path: written.append(bundle))
    argv = [str(script), "--symbols", "SPY", "--no-theme-context", "--web-research-sources", str(_config(tmp_path))]
    if end_date:
        argv.extend(["--end-date", end_date])
    monkeypatch.setattr(sys, "argv", argv)
    assert cli.main() == 0
    web = captured["web_research_context"]
    assert len(calls) == int(current)
    assert web["source_count"] == int(current)
    assert captured["generated_at"] == clock.observed[0]
    assert len(written) == 1
    if current:
        assert dt.datetime.fromisoformat(web["research_sources"][0]["fetched_at"].replace("Z", "+00:00")) > captured["generated_at"]
    else:
        assert web["warnings"]
        assert web["pit_timestamp"].startswith("2026-09-04")


def test_explicit_future_cutoff_does_not_replace_actual_fetch_time(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter_module, "urlopen", lambda *args, **kwargs: _FakeResponse(
        _rss("2026-09-04T00:00:00Z"), "application/rss+xml"))
    cutoff = dt.datetime(2026, 9, 6, tzinfo=dt.timezone.utc)
    context = ResearchContextAdapter(_config(tmp_path)).build_context(pit_timestamp=cutoff)
    assert context["source_count"] == 1
    assert context["pit_timestamp"] == "2026-09-06T00:00:00Z"
    assert context["research_sources"][0]["fetched_at"].startswith("2026-09-05T12:00:00.")


def test_response_finishing_after_explicit_cutoff_is_not_backdated(tmp_path, monkeypatch, clock):
    class DelayedResponse(_FakeResponse):
        def read(self):
            clock.current += dt.timedelta(seconds=2)
            return super().read()

    monkeypatch.setattr(adapter_module, "urlopen", lambda *args, **kwargs: DelayedResponse(
        _rss("2026-09-04T00:00:00Z"), "application/rss+xml"))
    cutoff = clock.current + dt.timedelta(seconds=1)
    context = ResearchContextAdapter(_config(tmp_path)).build_context(pit_timestamp=cutoff)
    assert context["source_count"] == 0
    assert context["pit_timestamp"] == "2026-09-05T12:00:01Z"
    assert any("fetched after" in warning for warning in context["warnings"])
