"""Web tools: web_search and web_fetch."""

import html
import json
import os
import re
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool

# Shared constants
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  # Limit redirects to prevent DoS attacks


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


class WebSearchTool(Tool):
    """Search the web using Brave Search API."""

    name = "web_search"
    description = "Search the web. Returns titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {"type": "integer", "description": "Results (1-10)", "minimum": 1, "maximum": 10}
        },
        "required": ["query"]
    }

    def __init__(self, api_key: str | None = None, max_results: int = 5, proxy: str | None = None):
        self._init_api_key = api_key
        self.max_results = max_results
        self.proxy = proxy

    @property
    def api_key(self) -> str:
        """Resolve API key at call time so env/config changes are picked up."""
        return self._init_api_key or os.environ.get("BRAVE_API_KEY", "")

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        if not self.api_key:
            return (
                "Error: Brave Search API key not configured. Set it in "
                "~/.nanobot/config.json under tools.web.search.apiKey "
                "(or export BRAVE_API_KEY), then restart the gateway."
            )

        try:
            n = min(max(count or self.max_results, 1), 10)
            logger.debug("WebSearch: {}", "proxy enabled" if self.proxy else "direct connection")
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                    timeout=10.0
                )
                r.raise_for_status()

            results = r.json().get("web", {}).get("results", [])[:n]
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results, 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")
            return "\n".join(lines)
        except httpx.ProxyError as e:
            logger.error("WebSearch proxy error: {}", e)
            return f"Proxy error: {e}"
        except Exception as e:
            logger.error("WebSearch error: {}", e)
            return f"Error: {e}"


class WebFetchTool(Tool):
    """Fetch and extract content from a URL using Readability."""

    name = "web_fetch"
    description = "Fetch URL and extract readable content (HTML → markdown/text)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100}
        },
        "required": ["url"]
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

        if host.endswith("youtube.com"):
            channel_id = cls._extract_youtube_channel_id(path) or cls._extract_youtube_channel_id_from_html(raw_html)
            if channel_id:
                candidates.append(
                    ("youtube-rss", f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
                )
            candidates.append(("reader", cls._reader_fallback_url(url)))
        elif host.endswith("x.com"):
            candidates.append(("reader", cls._reader_fallback_url(url)))

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

        if "application/json" in ctype:
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

        try:
            logger.debug("WebFetch: {}", "proxy enabled" if self.proxy else "direct connection")
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=30.0,
                proxy=self.proxy,
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
                text, extractor, error = self._extract_response(r, extractMode)

                if error:
                    attempts: list[dict[str, str]] = []
                    for strategy, fallback_url in self._fallback_candidates(str(r.url), r.text):
                        attempts.append({"strategy": strategy, "url": fallback_url})
                        try:
                            fallback_response = await client.get(
                                fallback_url,
                                headers={"User-Agent": USER_AGENT},
                            )
                            fallback_response.raise_for_status()
                            fallback_text, fallback_extractor, fallback_error = self._extract_response(
                                fallback_response,
                                extractMode,
                            )
                            if fallback_error or not fallback_text or not fallback_extractor:
                                continue

                            text = fallback_text
                            extractor = f"{strategy}-fallback"
                            r = fallback_response
                            break
                        except Exception as fallback_exc:
                            logger.warning(
                                "WebFetch fallback {} failed for {}: {}",
                                strategy,
                                fallback_url,
                                fallback_exc,
                            )
                    else:
                        return json.dumps(
                            {
                                "error": error,
                                "url": url,
                                "finalUrl": str(r.url),
                                "status": r.status_code,
                                "attemptedFallbacks": attempts,
                            },
                            ensure_ascii=False,
                        )
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

            return json.dumps(payload, ensure_ascii=False)
        except httpx.ProxyError as e:
            logger.error("WebFetch proxy error for {}: {}", url, e)
            return json.dumps({"error": f"Proxy error: {e}", "url": url}, ensure_ascii=False)
        except Exception as e:
            logger.error("WebFetch error for {}: {}", url, e)
            return json.dumps({"error": str(e), "url": url}, ensure_ascii=False)

    def _to_markdown(self, html: str) -> str:
        """Convert HTML to markdown."""
        # Convert links, headings, lists before stripping tags
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                      lambda m: f'[{_strip_tags(m[2])}]({m[1]})', html, flags=re.I)
        text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                      lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        return _normalize(_strip_tags(text))
