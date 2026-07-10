from __future__ import annotations

import datetime as dt
import email.utils
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


DEFAULT_WEB_RESEARCH_TIMEOUT_SECONDS = 10.0
DEFAULT_WEB_RESEARCH_MAX_ENTRIES = 8
WEB_RESEARCH_USER_AGENT = "Mozilla/5.0"


@dataclass(frozen=True)
class ResearchSourceConfig:
    url: str
    kind: str = "auto"


def _clean_text(value: object) -> str:
    text = " ".join(str(value or "").split())
    return text.strip()


def _isoformat_utc(value: dt.datetime | None) -> str:
    timestamp = value or dt.datetime.now(dt.timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
    return timestamp.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: object) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _load_research_config(path: Path) -> tuple[list[str], list[ResearchSourceConfig]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        whitelist: list[str] = []
        sources_payload = payload
    elif isinstance(payload, dict):
        whitelist = [_clean_text(item) for item in payload.get("whitelist", []) if _clean_text(item)]
        sources_payload = list(payload.get("sources", []))
    else:
        raise ValueError("research sources config must be a list or object")

    sources: list[ResearchSourceConfig] = []
    for raw in sources_payload:
        if not isinstance(raw, Mapping):
            raise ValueError("research source entries must be objects")
        url = _clean_text(raw.get("url"))
        if not url:
            raise ValueError("research source entries require url")
        sources.append(ResearchSourceConfig(url=url, kind=_clean_text(raw.get("kind")) or "auto"))

    return whitelist, sources


def _is_whitelisted(url: str, whitelist: Iterable[str]) -> bool:
    if not whitelist:
        return False
    candidate = urlsplit(url.strip())
    if not candidate.scheme or not candidate.netloc:
        return False
    candidate_path = candidate.path or "/"
    for raw_prefix in whitelist:
        allowed = urlsplit(raw_prefix)
        if candidate.scheme != allowed.scheme or candidate.netloc != allowed.netloc:
            continue
        allowed_path = allowed.path or "/"
        if allowed_path == "/":
            return True
        normalized_allowed = allowed_path.rstrip("/")
        if candidate_path == allowed_path or candidate_path.startswith(f"{normalized_allowed}/"):
            return True
    return False


def _source_kind(source: ResearchSourceConfig, *, content_type: str | None, body: bytes) -> str:
    if source.kind and source.kind != "auto":
        return source.kind.lower()
    if content_type:
        lowered = content_type.lower()
        if "rss" in lowered or "atom" in lowered or "xml" in lowered:
            return "rss"
        if "html" in lowered:
            return "http"
    prefix = body.lstrip()[:200].lower()
    if prefix.startswith(b"<?xml") or prefix.startswith(b"<rss") or prefix.startswith(b"<feed"):
        return "rss"
    return "http"


def _entry_from_feed_item(item: ET.Element, *, source_url: str, fetched_at: str) -> dict[str, Any]:
    def child_text(*names: str) -> str:
        for node in item:
            local_name = node.tag.rsplit("}", 1)[-1].lower()
            if local_name in names:
                text = _clean_text("".join(node.itertext()))
                if text:
                    return text
        return ""

    link = ""
    for node in item:
        local_name = node.tag.rsplit("}", 1)[-1].lower()
        if local_name == "link":
            href = _clean_text(node.attrib.get("href"))
            if href:
                link = href
                break
            text = _clean_text(node.text)
            if text:
                link = text
                break

    published_at = None
    for field in ("published", "updated", "pubdate", "date"):
        published_at = _parse_datetime(child_text(field))
        if published_at:
            break

    summary = child_text("summary", "description", "encoded")
    title = child_text("title") or source_url
    return {
        "title": title,
        "summary": summary,
        "published_at": published_at,
        "url": link or source_url,
        "source_url": source_url,
        "source_type": "rss",
        "fetched_at": fetched_at,
    }


def _feed_entries(body: bytes, *, source_url: str, fetched_at: str) -> list[dict[str, Any]]:
    root = ET.fromstring(body)
    local_root = root.tag.rsplit("}", 1)[-1].lower()
    items: list[ET.Element] = []
    if local_root == "rss":
        channel = next((child for child in root if child.tag.rsplit("}", 1)[-1].lower() == "channel"), root)
        items = [child for child in channel if child.tag.rsplit("}", 1)[-1].lower() == "item"]
    else:
        items = [child for child in root.iter() if child.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}]
    return [_entry_from_feed_item(item, source_url=source_url, fetched_at=fetched_at) for item in items]


class _NewsHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self._capture_title = False
        self._capture_paragraph = False
        self._paragraph_buffer: list[str] = []
        self.title: str = ""
        self.summary: str = ""
        self.published_at: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        lowered = tag.lower()
        if lowered == "title":
            self._capture_title = True
        elif lowered == "p" and not self.summary:
            self._capture_paragraph = True
            self._paragraph_buffer = []
        elif lowered == "meta":
            name = attributes.get("name", "").lower()
            prop = attributes.get("property", "").lower()
            content = _clean_text(attributes.get("content"))
            if not content:
                return
            if name == "description" or prop in {"og:description", "twitter:description"}:
                self.summary = content
            if prop == "article:published_time" or name in {"pubdate", "date"}:
                self.published_at = self.published_at or _parse_datetime(content)
        elif lowered == "time" and not self.published_at:
            self.published_at = _parse_datetime(attributes.get("datetime"))

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "title":
            self._capture_title = False
            if not self.title:
                self.title = _clean_text("".join(self.title_parts))
        elif lowered == "p" and self._capture_paragraph:
            self._capture_paragraph = False
            if not self.summary:
                summary = _clean_text("".join(self._paragraph_buffer))
                if summary:
                    self.summary = summary

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self.title_parts.append(data)
        if self._capture_paragraph:
            self._paragraph_buffer.append(data)


def _html_entry(body: bytes, *, source_url: str, fetched_at: str) -> dict[str, Any]:
    parser = _NewsHTMLParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    title = parser.title or source_url
    summary = parser.summary
    return {
        "title": title,
        "summary": summary,
        "published_at": parser.published_at,
        "url": source_url,
        "source_url": source_url,
        "source_type": "news",
        "fetched_at": fetched_at,
    }


class ResearchContextAdapter:
    def __init__(
        self,
        sources_path: Path,
        *,
        timeout_seconds: float = DEFAULT_WEB_RESEARCH_TIMEOUT_SECONDS,
        max_entries: int = DEFAULT_WEB_RESEARCH_MAX_ENTRIES,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.sources_path = Path(sources_path)
        self.timeout_seconds = float(timeout_seconds)
        self.max_entries = int(max_entries)

    def build_context(self, *, pit_timestamp: dt.datetime | None = None) -> dict[str, Any]:
        fetched_at = _isoformat_utc(pit_timestamp)
        context: dict[str, Any] = {
            "pit_timestamp": fetched_at,
            "research_sources": [],
            "warnings": [],
        }
        if not self.sources_path.exists():
            context["warnings"].append(f"research sources file not found: {self.sources_path}")
            return context

        try:
            whitelist, sources = _load_research_config(self.sources_path)
        except Exception as exc:
            context["warnings"].append(f"failed to load research sources config: {type(exc).__name__}: {exc}")
            return context

        if not whitelist:
            context["warnings"].append("research sources config has no whitelist")
            return context

        collected: list[dict[str, Any]] = []
        warnings = context["warnings"]
        for source in sources:
            if len(collected) >= self.max_entries:
                break
            if not _is_whitelisted(source.url, whitelist):
                warnings.append(f"skipped non-whitelisted source: {source.url}")
                continue
            try:
                request = Request(source.url, headers={"User-Agent": WEB_RESEARCH_USER_AGENT, "Accept": "*/*"})
                with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - operator-controlled research fetch.
                    body = response.read()
                    content_type = response.headers.get_content_type() if hasattr(response.headers, "get_content_type") else None
            except (OSError, URLError, TimeoutError, ValueError) as exc:
                warnings.append(f"failed to fetch research source {source.url}: {type(exc).__name__}: {exc}")
                continue

            kind = _source_kind(source, content_type=content_type, body=body)
            try:
                entries = _feed_entries(body, source_url=source.url, fetched_at=fetched_at) if kind == "rss" else [_html_entry(body, source_url=source.url, fetched_at=fetched_at)]
            except Exception as exc:
                warnings.append(f"failed to parse research source {source.url}: {type(exc).__name__}: {exc}")
                continue

            for entry in entries:
                if len(collected) >= self.max_entries:
                    break
                collected.append(entry)

        context["research_sources"] = collected
        context["source_count"] = len(collected)
        return context
