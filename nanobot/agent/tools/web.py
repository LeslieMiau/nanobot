"""Web tools: web_search and web_fetch."""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.config.schema import WebSearchConfig

# Shared constants
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  # Limit redirects to prevent DoS attacks
FEED_LINK_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/feed+json",
}
SOURCE_LANDING_SEGMENTS = {
    "announcements",
    "blog",
    "changelog",
    "newsletter",
    "news",
    "podcast",
    "release-notes",
    "releases",
    "research",
    "updates",
}


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """Normalize whitespace."""
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _looks_like_feed_url(url: str) -> bool:
    """Heuristic for alternate links that are likely feeds even without explicit MIME type."""
    lower = url.lower()
    return any(
        token in lower
        for token in (
            "/feed",
            "rss",
            "atom",
            "jsonfeed",
            "feed.xml",
            "rss.xml",
            "atom.xml",
            "feed.json",
        )
    ) or lower.endswith((".xml", ".atom", ".rss", ".json"))


def _extract_hn_items(html_text: str, max_items: int = 10) -> str | None:
    """Extract concrete post entries from Hacker News HTML."""
    pattern = re.compile(
        r'<span class="titleline">\s*<a href="([^"]+)".*?>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    items = []
    for href, title_html in pattern.findall(html_text):
        title = _normalize(_strip_tags(title_html))
        if not title:
            continue
        items.append(f"- [{title}]({html.unescape(href)})")
        if len(items) >= max_items:
            break
    if not items:
        return None
    return "# Hacker News\n\n" + "\n".join(items)


def _extract_github_trending_items(html_text: str, max_items: int = 10) -> str | None:
    """Extract concrete repository entries from GitHub Trending HTML."""
    pattern = re.compile(
        r'<h2[^>]*>\s*<a[^>]*href="(/[^"/\s]+/[^"/\s]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    items = []
    seen: set[str] = set()
    for href, repo_html in pattern.findall(html_text):
        repo_name = re.sub(r"\s+", "", _strip_tags(repo_html))
        if not repo_name or href in seen:
            continue
        seen.add(href)
        items.append(f"- [{repo_name}](https://github.com{href})")
        if len(items) >= max_items:
            break
    if not items:
        return None
    return "# Trending repositories on GitHub today\n\n" + "\n".join(items)


def _extract_rss_atom_items(feed_text: str, max_items: int = 10) -> str | None:
    """Extract concrete entries from RSS/Atom feeds."""
    try:
        root = ElementTree.fromstring(feed_text)
    except ElementTree.ParseError:
        return None

    items: list[str] = []
    feed_title = ""
    root_tag = root.tag.lower()
    is_atom = root_tag.endswith("feed")

    if is_atom:
        feed_title = _normalize((root.findtext("{*}title") or "").strip())
        for entry in root.findall("{*}entry"):
            title = _normalize((entry.findtext("{*}title") or "").strip())
            link = ""
            for link_node in entry.findall("{*}link"):
                href = (link_node.attrib.get("href") or "").strip()
                rel = (link_node.attrib.get("rel") or "").strip().lower()
                if href and (not rel or rel == "alternate"):
                    link = href
                    break
            if not link:
                link = (entry.findtext("{*}id") or "").strip()
            published = (
                (entry.findtext("{*}updated") or entry.findtext("{*}published") or "").strip()
            )
            if not title or not link:
                continue
            line = f"- [{title}]({link})"
            if published:
                line += f" ({published})"
            items.append(line)
            if len(items) >= max_items:
                break
    else:
        channel = root.find("{*}channel")
        node = channel if channel is not None else root
        feed_title = _normalize((node.findtext("{*}title") or "").strip())
        for item in node.findall("{*}item"):
            title = _normalize((item.findtext("{*}title") or "").strip())
            link = (item.findtext("{*}link") or "").strip()
            if not link:
                link_node = item.find("{*}link")
                if link_node is not None:
                    link = (link_node.attrib.get("href") or "").strip()
            published = (
                (
                    item.findtext("{*}pubDate")
                    or item.findtext("{*}date")
                    or item.findtext("{*}updated")
                    or ""
                ).strip()
            )
            if not title or not link:
                continue
            line = f"- [{title}]({link})"
            if published:
                line += f" ({published})"
            items.append(line)
            if len(items) >= max_items:
                break

    if not items:
        return None
    heading = feed_title or "RSS/Atom Feed"
    return f"# {heading}\n\n" + "\n".join(items)


def _extract_json_feed_items(feed_text: str, max_items: int = 10) -> str | None:
    """Extract concrete entries from a JSON Feed payload."""
    try:
        payload = json.loads(feed_text)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    version = str(payload.get("version") or "")
    items_data = payload.get("items")
    if "jsonfeed.org" not in version or not isinstance(items_data, list):
        return None

    feed_title = _normalize(str(payload.get("title") or "").strip())
    items: list[str] = []
    for item in items_data:
        if not isinstance(item, dict):
            continue
        title = _normalize(str(item.get("title") or "").strip())
        link = str(item.get("url") or item.get("external_url") or item.get("id") or "").strip()
        published = _normalize(str(item.get("date_published") or item.get("date_modified") or "").strip())
        if not title or not link:
            continue
        line = f"- [{title}]({link})"
        if published:
            line += f" ({published})"
        items.append(line)
        if len(items) >= max_items:
            break

    if not items:
        return None
    heading = feed_title or "JSON Feed"
    return f"# {heading}\n\n" + "\n".join(items)


def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with valid domain."""
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


def _format_results(query: str, items: list[dict[str, Any]], n: int) -> str:
    """Format provider results into shared plaintext output."""
    if not items:
        return f"No results for: {query}"
    lines = [f"Results for: {query}\n"]
    for i, item in enumerate(items[:n], 1):
        title = _normalize(_strip_tags(item.get("title", "")))
        snippet = _normalize(_strip_tags(item.get("content", "")))
        lines.append(f"{i}. {title}\n   {item.get('url', '')}")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


class _SourceHealthTracker:
    """Track short-lived fetch failures so bad fallback sources can cool down."""

    SOFT_SOURCE_COOLDOWN_SECONDS = 10 * 60
    HARD_SOURCE_COOLDOWN_SECONDS = 60 * 60
    DOMAIN_FAILURE_WINDOW_SECONDS = 10 * 60
    DOMAIN_FAILURE_THRESHOLD = 2
    DOMAIN_BACKOFF_SECONDS = 30 * 60

    def __init__(self) -> None:
        self._source_cooldowns: dict[str, tuple[float, str]] = {}
        self._domain_failures: dict[str, list[float]] = {}
        self._domain_backoffs: dict[str, tuple[float, str]] = {}

    def reset(self) -> None:
        self._source_cooldowns.clear()
        self._domain_failures.clear()
        self._domain_backoffs.clear()

    def _prune(self, now: float) -> None:
        self._source_cooldowns = {
            url: entry for url, entry in self._source_cooldowns.items() if entry[0] > now
        }
        self._domain_backoffs = {
            host: entry for host, entry in self._domain_backoffs.items() if entry[0] > now
        }

        kept_failures: dict[str, list[float]] = {}
        for host, failures in self._domain_failures.items():
            recent = [ts for ts in failures if now - ts <= self.DOMAIN_FAILURE_WINDOW_SECONDS]
            if recent:
                kept_failures[host] = recent
        self._domain_failures = kept_failures

    @staticmethod
    def _domain(url: str) -> str:
        return urlparse(url).netloc.lower()

    @staticmethod
    def _is_hard_failure(reason: str) -> bool:
        normalized = reason.lower()
        hard_markers = (
            "http 401",
            "http 403",
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "placeholder error page",
            "login or missing-page shell",
            "proxy error",
            "timed out",
            "connection refused",
            "connection reset",
        )
        return any(marker in normalized for marker in hard_markers)

    def record_failure(self, url: str, reason: str) -> None:
        now = time.monotonic()
        self._prune(now)
        host = self._domain(url)
        cooldown = (
            self.HARD_SOURCE_COOLDOWN_SECONDS
            if self._is_hard_failure(reason)
            else self.SOFT_SOURCE_COOLDOWN_SECONDS
        )
        self._source_cooldowns[url] = (now + cooldown, reason)

        failures = self._domain_failures.setdefault(host, [])
        failures.append(now)
        failures = [ts for ts in failures if now - ts <= self.DOMAIN_FAILURE_WINDOW_SECONDS]
        self._domain_failures[host] = failures
        if len(failures) >= self.DOMAIN_FAILURE_THRESHOLD:
            self._domain_backoffs[host] = (
                now + self.DOMAIN_BACKOFF_SECONDS,
                "domain backoff active for "
                f"{host} after repeated fetch failures",
            )

    def record_success(self, url: str) -> None:
        now = time.monotonic()
        self._prune(now)
        host = self._domain(url)
        self._source_cooldowns.pop(url, None)
        self._domain_failures.pop(host, None)
        self._domain_backoffs.pop(host, None)

    def should_skip(self, url: str) -> str | None:
        now = time.monotonic()
        self._prune(now)
        host = self._domain(url)
        domain_backoff = self._domain_backoffs.get(host)
        if domain_backoff:
            return domain_backoff[1]

        source_cooldown = self._source_cooldowns.get(url)
        if source_cooldown:
            return (
                "source cooldown active after recent fetch failure: "
                f"{source_cooldown[1]}"
            )

        return None


_SOURCE_HEALTH = _SourceHealthTracker()


class WebSearchTool(Tool):
    """Search the web using configured provider."""

    name = "web_search"
    description = "Search the web. Returns titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {"type": "integer", "description": "Results (1-10)", "minimum": 1, "maximum": 10},
        },
        "required": ["query"],
    }

    def __init__(
        self,
        config: WebSearchConfig | None = None,
        proxy: str | None = None,
        *,
        api_key: str | None = None,
        max_results: int | None = None,
        base_url: str | None = None,
    ):
        from nanobot.config.schema import WebSearchConfig

        self.config = config if config is not None else WebSearchConfig()
        if api_key is not None and not self.config.api_key:
            self.config.api_key = api_key
        if max_results is not None and (config is None or self.config.max_results == WebSearchConfig().max_results):
            self.config.max_results = max_results
        if base_url is not None and not self.config.base_url:
            self.config.base_url = base_url
        self.proxy = proxy

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        provider = self.config.provider.strip().lower() or "brave"
        n = min(max(count or self.config.max_results, 1), 10)

        if provider == "duckduckgo":
            return await self._search_duckduckgo(query, n)
        elif provider == "tavily":
            return await self._search_tavily(query, n)
        elif provider == "searxng":
            return await self._search_searxng(query, n)
        elif provider == "jina":
            return await self._search_jina(query, n)
        elif provider == "brave":
            return await self._search_brave(query, n)
        else:
            return f"Error: unknown search provider '{provider}'"

    async def _search_brave(self, query: str, n: int) -> str:
        api_key = self.config.api_key or os.environ.get("BRAVE_API_KEY", "")
        if not api_key:
            logger.warning("BRAVE_API_KEY not set, falling back to DuckDuckGo")
            return await self._search_duckduckgo(query, n)
        try:
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                    timeout=10.0,
                )
                r.raise_for_status()
            items = [
                {"title": x.get("title", ""), "url": x.get("url", ""), "content": x.get("description", "")}
                for x in r.json().get("web", {}).get("results", [])
            ]
            return _format_results(query, items, n)
        except Exception as e:
            return f"Error: {e}"

    async def _search_tavily(self, query: str, n: int) -> str:
        api_key = self.config.api_key or os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            logger.warning("TAVILY_API_KEY not set, falling back to DuckDuckGo")
            return await self._search_duckduckgo(query, n)
        try:
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.post(
                    "https://api.tavily.com/search",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"query": query, "max_results": n},
                    timeout=15.0,
                )
                r.raise_for_status()
            return _format_results(query, r.json().get("results", []), n)
        except Exception as e:
            return f"Error: {e}"

    async def _search_searxng(self, query: str, n: int) -> str:
        base_url = (self.config.base_url or os.environ.get("SEARXNG_BASE_URL", "")).strip()
        if not base_url:
            logger.warning("SEARXNG_BASE_URL not set, falling back to DuckDuckGo")
            return await self._search_duckduckgo(query, n)
        endpoint = f"{base_url.rstrip('/')}/search"
        is_valid, error_msg = _validate_url(endpoint)
        if not is_valid:
            return f"Error: invalid SearXNG URL: {error_msg}"
        try:
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    endpoint,
                    params={"q": query, "format": "json"},
                    headers={"User-Agent": USER_AGENT},
                    timeout=10.0,
                )
                r.raise_for_status()
            return _format_results(query, r.json().get("results", []), n)
        except Exception as e:
            return f"Error: {e}"

    async def _search_jina(self, query: str, n: int) -> str:
        api_key = self.config.api_key or os.environ.get("JINA_API_KEY", "")
        if not api_key:
            logger.warning("JINA_API_KEY not set, falling back to DuckDuckGo")
            return await self._search_duckduckgo(query, n)
        try:
            headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    f"https://s.jina.ai/",
                    params={"q": query},
                    headers=headers,
                    timeout=15.0,
                )
                r.raise_for_status()
            data = r.json().get("data", [])[:n]
            items = [
                {"title": d.get("title", ""), "url": d.get("url", ""), "content": d.get("content", "")[:500]}
                for d in data
            ]
            return _format_results(query, items, n)
        except Exception as e:
            return f"Error: {e}"

    async def _search_duckduckgo(self, query: str, n: int) -> str:
        try:
            from ddgs import DDGS

            ddgs = DDGS(timeout=10)
            raw = await asyncio.to_thread(ddgs.text, query, max_results=n)
            if not raw:
                return f"No results for: {query}"
            items = [
                {"title": r.get("title", ""), "url": r.get("href", ""), "content": r.get("body", "")}
                for r in raw
            ]
            return _format_results(query, items, n)
        except Exception as e:
            logger.warning("DuckDuckGo search failed: {}", e)
            return f"Error: DuckDuckGo search failed ({e})"


class WebFetchTool(Tool):
    """Fetch and extract content from a URL."""

    name = "web_fetch"
    description = "Fetch URL and extract readable content (HTML → markdown/text)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100},
        },
        "required": ["url"],
    }

    def __init__(self, max_chars: int = 50000, proxy: str | None = None):
        self.max_chars = max_chars
        self.proxy = proxy

    @staticmethod
    def _site_specific_extract(url: str, raw_html: str) -> tuple[str, str] | None:
        """Extract structured content for sites where Readability performs poorly."""
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path or "/"

        if host.endswith("news.ycombinator.com"):
            extracted = _extract_hn_items(raw_html)
            if extracted:
                return extracted, "hn-list"

        if host.endswith("github.com") and path == "/trending":
            extracted = _extract_github_trending_items(raw_html)
            if extracted:
                return extracted, "github-trending"

        return None

    @staticmethod
    def _extract_youtube_channel_id(path: str) -> str | None:
        """Extract a YouTube channel ID from a canonical /channel/<id> path."""
        match = re.match(r"^/channel/([A-Za-z0-9_-]+)(?:/|$)", path)
        if not match:
            return None
        return match.group(1)

    @staticmethod
    def _extract_youtube_channel_id_from_html(raw_html: str) -> str | None:
        """Extract a YouTube channel ID from page HTML metadata."""
        patterns = (
            r'feeds/videos\.xml\?channel_id=([A-Za-z0-9_-]+)',
            r'"externalId":"([A-Za-z0-9_-]+)"',
            r'"browseId":"(UC[A-Za-z0-9_-]+)"',
            r'www\.youtube\.com/channel/([A-Za-z0-9_-]+)',
        )
        for pattern in patterns:
            match = re.search(pattern, raw_html)
            if match:
                return html.unescape(match.group(1))
        return None

    @staticmethod
    def _discover_feed_urls(raw_html: str, base_url: str) -> list[str]:
        """Discover alternate RSS/Atom/JSON feeds exposed in page metadata."""
        if not raw_html:
            return []

        urls: list[str] = []
        seen: set[str] = set()
        for attrs in re.findall(r"<link\b([^>]+)>", raw_html, flags=re.IGNORECASE):
            href_match = re.search(r"""\bhref\s*=\s*["']([^"']+)["']""", attrs, flags=re.IGNORECASE)
            if not href_match:
                continue
            href = html.unescape(href_match.group(1)).strip()
            if not href:
                continue

            rel_match = re.search(r"""\brel\s*=\s*["']([^"']+)["']""", attrs, flags=re.IGNORECASE)
            rel_tokens = {
                token.strip().lower()
                for token in re.split(r"\s+", rel_match.group(1))
                if token.strip()
            } if rel_match else set()
            if "alternate" not in rel_tokens:
                continue

            type_match = re.search(r"""\btype\s*=\s*["']([^"']+)["']""", attrs, flags=re.IGNORECASE)
            link_type = (type_match.group(1).strip().lower() if type_match else "")
            if link_type not in FEED_LINK_TYPES and not _looks_like_feed_url(href):
                continue

            resolved = urljoin(base_url, href)
            if resolved not in seen:
                seen.add(resolved)
                urls.append(resolved)

        return urls

    @staticmethod
    def _is_source_landing_path(path: str) -> bool:
        """Detect landing pages that often act as stable source registries."""
        normalized = path.lower().strip("/")
        if not normalized:
            return False
        return normalized.split("/")[-1] in SOURCE_LANDING_SEGMENTS

    @staticmethod
    def _reader_fallback_url(url: str) -> str:
        """Build a public reader mirror URL for a login-gated page."""
        parsed = urlparse(url)
        suffix = f"{parsed.netloc}{parsed.path}"
        if parsed.query:
            suffix += f"?{parsed.query}"
        return f"https://r.jina.ai/http://{suffix}"

    @staticmethod
    def _reader_source_url(url: str) -> str | None:
        """Recover the source URL from a r.jina.ai reader mirror URL."""
        parsed = urlparse(url)
        if not parsed.netloc.lower().endswith("r.jina.ai"):
            return None
        candidate = parsed.path.lstrip("/")
        if candidate.startswith(("http://", "https://")):
            return candidate
        return None

    @classmethod
    def _fallback_candidates(cls, url: str, raw_html: str = "") -> list[tuple[str, str]]:
        """Return fallback sources for pages that often require login or JS hydration."""
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path or "/"
        candidates: list[tuple[str, str]] = []
        discovered_feeds = cls._discover_feed_urls(raw_html, url)
        seen_urls: set[str] = set()

        def add_candidate(strategy: str, candidate_url: str) -> None:
            if candidate_url in seen_urls:
                return
            seen_urls.add(candidate_url)
            candidates.append((strategy, candidate_url))

        if host.endswith("youtube.com"):
            channel_id = cls._extract_youtube_channel_id(path) or cls._extract_youtube_channel_id_from_html(raw_html)
            if channel_id:
                add_candidate("youtube-rss", f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
            for discovered_feed in discovered_feeds:
                add_candidate("discovered-feed", discovered_feed)
            add_candidate("reader", cls._reader_fallback_url(url))
        elif host.endswith("x.com"):
            add_candidate("reader", cls._reader_fallback_url(url))
        else:
            for discovered_feed in discovered_feeds:
                add_candidate("discovered-feed", discovered_feed)

        return candidates

    @staticmethod
    def _detect_unusable_page(url: str, raw_html: str, text: str) -> str | None:
        """Return a human-readable reason when the page is a known unusable shell."""
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path or "/"
        normalized = _normalize(text).lower()
        source_url = WebFetchTool._reader_source_url(url)

        if source_url:
            source_parsed = urlparse(source_url)
            host = source_parsed.netloc.lower()
            path = source_parsed.path or "/"

        if host.endswith("x.com"):
            if "something went wrong, but don’t fret" in normalized:
                return "x.com returned a placeholder error page instead of concrete post content"
            x_shell_markers = (
                "don’t miss what’s happening",
                "don't miss what's happening",
                "hmm...this page doesn’t exist",
                "hmm...this page doesn't exist",
                "join x today",
                "log in",
                "sign up",
            )
            if sum(marker in normalized for marker in x_shell_markers) >= 2:
                return "x.com reader fallback returned a login or missing-page shell"

        if host.endswith("youtube.com") and (
            "/@" in path
            or path.startswith("/channel/")
            or path.startswith("/user/")
            or path.startswith("/c/")
        ):
            has_visible_watch_links = "/watch?v=" in text or "watch?v=" in normalized
            generic_shell_markers = (
                "youtube 的運作方式",
                "how youtube works",
                "news center",
                "pressroom",
                "copyright",
                "privacy",
                "terms",
                "creators",
                "developers",
                "policy and safety",
                "policies and safety",
                "プレスルーム",
                "著作権",
                "クリエイター向け",
                "開発者向け",
                "利用規約",
                "ポリシーとセキュリティ",
                "概要",
                "簡介",
                "新聞中心",
                "版權",
                "聯絡我們",
                "創作者",
                "刊登廣告",
                "開發人員",
                "條款",
                "私隱",
                "政策及安全",
            )
            if not has_visible_watch_links and sum(marker in normalized for marker in generic_shell_markers) >= 3:
                return "YouTube channel page returned a generic shell without concrete videos"

        if host.endswith("news.ycombinator.com") and normalized == "# hacker news":
            return "Hacker News page returned no extractable post entries"

        if host.endswith("github.com") and path == "/trending" and "see what the github community is most excited about today" in normalized:
            return "GitHub Trending page returned only the directory shell without repository entries"

        discovered_feeds = WebFetchTool._discover_feed_urls(raw_html, url)
        concrete_links = re.findall(r"\[[^\]]+\]\((https?://[^)]+)\)", text)
        if (
            discovered_feeds
            and WebFetchTool._is_source_landing_path(path)
            and len(concrete_links) < 2
        ):
            return "Source landing page exposed feed metadata but returned no concrete entries"

        return None

    def _extract_response(
        self,
        response: httpx.Response,
        extract_mode: str,
    ) -> tuple[str | None, str | None, str | None]:
        """Extract normalized content from an HTTP response."""
        from readability import Document

        ctype = response.headers.get("content-type", "")
        final_url = str(response.url)

        if "application/feed+json" in ctype or "application/json" in ctype:
            extracted = _extract_json_feed_items(response.text)
            if extracted:
                return extracted, "json-feed-list", None
            text = json.dumps(response.json(), indent=2, ensure_ascii=False)
            unusable_reason = self._detect_unusable_page(final_url, response.text, text)
            if unusable_reason:
                return None, None, unusable_reason
            return text, "json", None

        if "xml" in ctype or response.text.lstrip().startswith(("<?xml", "<rss", "<feed")):
            extracted = _extract_rss_atom_items(response.text)
            if not extracted:
                return None, None, "RSS/Atom feed returned no extractable entries"
            return extracted, "rss-list", None

        if "text/html" in ctype or response.text[:256].lower().startswith(("<!doctype", "<html")):
            specialized = self._site_specific_extract(final_url, response.text)
            if specialized:
                text, extractor = specialized
            else:
                doc = Document(response.text)
                content = (
                    self._to_markdown(doc.summary())
                    if extract_mode == "markdown"
                    else _strip_tags(doc.summary())
                )
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"

            unusable_reason = self._detect_unusable_page(final_url, response.text, text)
            if unusable_reason:
                return None, None, unusable_reason
            return text, extractor, None

        unusable_reason = self._detect_unusable_page(final_url, response.text, response.text)
        if unusable_reason:
            return None, None, unusable_reason
        return response.text, "raw", None
    async def execute(self, url: str, extractMode: str = "markdown", maxChars: int | None = None, **kwargs: Any) -> str:
        max_chars = maxChars or self.max_chars
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url}, ensure_ascii=False)

        result = await self._fetch_jina(url, max_chars)
        if result is None:
            result = await self._fetch_readability(url, extractMode, max_chars)
        return result

    async def _fetch_jina(self, url: str, max_chars: int) -> str | None:
        """Try fetching via Jina Reader API. Returns None on failure."""
        try:
            headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
            jina_key = os.environ.get("JINA_API_KEY", "")
            if jina_key:
                headers["Authorization"] = f"Bearer {jina_key}"
            async with httpx.AsyncClient(proxy=self.proxy, timeout=20.0) as client:
                r = await client.get(f"https://r.jina.ai/{url}", headers=headers)
                if r.status_code == 429:
                    logger.debug("Jina Reader rate limited, falling back to readability")
                    return None
                r.raise_for_status()

            data = r.json().get("data", {})
            title = data.get("title", "")
            text = data.get("content", "")
            if not text:
                return None

            if title:
                text = f"# {title}\n\n{text}"
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]

            return json.dumps({
                "url": url, "finalUrl": data.get("url", url), "status": r.status_code,
                "extractor": "jina", "truncated": truncated, "length": len(text), "text": text,
            }, ensure_ascii=False)
        except Exception as e:
            logger.debug("Jina Reader failed for {}, falling back to readability: {}", url, e)
            return None

    async def _fetch_readability(self, url: str, extract_mode: str, max_chars: int) -> str:
        """Local fallback using readability-lxml."""
        from readability import Document

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=30.0,
                proxy=self.proxy,
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
                text, extractor, error = self._extract_response(r, extract_mode)
                skipped_fallbacks: list[dict[str, str]] = []

                if error:
                    attempts: list[dict[str, str]] = []
                    for strategy, fallback_url in self._fallback_candidates(str(r.url), r.text):
                        skip_reason = _SOURCE_HEALTH.should_skip(fallback_url)
                        if skip_reason:
                            skipped_fallbacks.append(
                                {
                                    "strategy": strategy,
                                    "url": fallback_url,
                                    "reason": skip_reason,
                                }
                            )
                            continue

                        attempts.append({"strategy": strategy, "url": fallback_url})
                        try:
                            fallback_response = await client.get(
                                fallback_url,
                                headers={"User-Agent": USER_AGENT},
                            )
                            fallback_response.raise_for_status()
                            fallback_text, fallback_extractor, fallback_error = self._extract_response(
                                fallback_response,
                                extract_mode,
                            )
                            if fallback_error or not fallback_text or not fallback_extractor:
                                _SOURCE_HEALTH.record_failure(
                                    fallback_url,
                                    fallback_error or "fallback returned no extractable content",
                                )
                                continue

                            text = fallback_text
                            extractor = f"{strategy}-fallback"
                            r = fallback_response
                            _SOURCE_HEALTH.record_success(fallback_url)
                            break
                        except httpx.HTTPStatusError as fallback_exc:
                            status_code = fallback_exc.response.status_code if fallback_exc.response else 0
                            _SOURCE_HEALTH.record_failure(fallback_url, f"HTTP {status_code}")
                            logger.warning(
                                "WebFetch fallback {} failed for {} with status {}",
                                strategy,
                                fallback_url,
                                status_code,
                            )
                        except Exception as fallback_exc:
                            _SOURCE_HEALTH.record_failure(fallback_url, str(fallback_exc))
                            logger.warning(
                                "WebFetch fallback {} failed for {}: {}",
                                strategy,
                                fallback_url,
                                fallback_exc,
                            )
                    else:
                        payload = {
                            "error": error,
                            "url": url,
                            "finalUrl": str(r.url),
                            "status": r.status_code,
                            "attemptedFallbacks": attempts,
                        }
                        if skipped_fallbacks:
                            payload["skippedFallbacks"] = skipped_fallbacks
                        return json.dumps(payload, ensure_ascii=False)
                else:
                    assert text is not None
                    assert extractor is not None

            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]

            payload: dict[str, Any] = {
                "url": url,
                "finalUrl": str(r.url),
                "status": r.status_code,
                "extractor": extractor,
                "truncated": truncated,
                "length": len(text),
                "text": text,
            }
            if str(r.url) != url and extractor.endswith("-fallback"):
                payload["usedFallback"] = True
                payload["fallbackUrl"] = str(r.url)
            if skipped_fallbacks:
                payload["skippedFallbacks"] = skipped_fallbacks

            return json.dumps(payload, ensure_ascii=False)
        except httpx.ProxyError as e:
            logger.error("WebFetch proxy error for {}: {}", url, e)
            return json.dumps({"error": f"Proxy error: {e}", "url": url}, ensure_ascii=False)
        except Exception as e:
            logger.error("WebFetch error for {}: {}", url, e)
            return json.dumps({"error": str(e), "url": url}, ensure_ascii=False)

    def _to_markdown(self, html_content: str) -> str:
        """Convert HTML to markdown."""
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                      lambda m: f'[{_strip_tags(m[2])}]({m[1]})', html_content, flags=re.I)
        text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                      lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        return _normalize(_strip_tags(text))
