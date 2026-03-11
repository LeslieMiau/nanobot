import json

import pytest

from nanobot.agent.tools import web as web_tool
from nanobot.agent.tools.web import WebFetchTool


def test_web_fetch_extracts_hn_items_from_html() -> None:
    html = """
    <html><body>
      <span class="titleline"><a href="https://example.com/a">First Post</a></span>
      <span class="titleline"><a href="https://example.com/b">Second Post</a></span>
    </body></html>
    """

    result = WebFetchTool._site_specific_extract("https://news.ycombinator.com/", html)

    assert result is not None
    text, extractor = result
    assert extractor == "hn-list"
    assert "[First Post](https://example.com/a)" in text
    assert "[Second Post](https://example.com/b)" in text


def test_web_fetch_extracts_github_trending_items_from_html() -> None:
    html = """
    <html><body>
      <h2 class="h3 lh-condensed">
        <a href="/openai/openai-python">
          openai /

          openai-python
        </a>
      </h2>
      <h2 class="h3 lh-condensed">
        <a href="/anthropics/anthropic-sdk-python">
          anthropics / anthropic-sdk-python
        </a>
      </h2>
    </body></html>
    """

    result = WebFetchTool._site_specific_extract("https://github.com/trending?since=daily", html)

    assert result is not None
    text, extractor = result
    assert extractor == "github-trending"
    assert "[openai/openai-python](https://github.com/openai/openai-python)" in text
    assert "[anthropics/anthropic-sdk-python](https://github.com/anthropics/anthropic-sdk-python)" in text
    assert "/\n" not in text


def test_web_fetch_extracts_rss_items_from_xml() -> None:
    rss = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>OpenAI News</title>
        <item>
          <title>Introducing new model</title>
          <link>https://openai.com/news/new-model</link>
          <pubDate>Sun, 08 Mar 2026 02:19:13 GMT</pubDate>
        </item>
        <item>
          <title>Pricing update</title>
          <link>https://openai.com/news/pricing-update</link>
        </item>
      </channel>
    </rss>
    """

    text = web_tool._extract_rss_atom_items(rss, max_items=10)

    assert text is not None
    assert text.startswith("# OpenAI News")
    assert "[Introducing new model](https://openai.com/news/new-model)" in text
    assert "(Sun, 08 Mar 2026 02:19:13 GMT)" in text
    assert "[Pricing update](https://openai.com/news/pricing-update)" in text


def test_web_fetch_extracts_json_feed_items() -> None:
    feed = """
    {
      "version": "https://jsonfeed.org/version/1.1",
      "title": "Research Updates",
      "items": [
        {
          "title": "Model update",
          "url": "https://example.com/model-update",
          "date_published": "2026-03-08T01:00:00Z"
        }
      ]
    }
    """

    text = web_tool._extract_json_feed_items(feed, max_items=10)

    assert text is not None
    assert text.startswith("# Research Updates")
    assert "[Model update](https://example.com/model-update)" in text
    assert "(2026-03-08T01:00:00Z)" in text


@pytest.mark.asyncio
async def test_web_fetch_returns_error_for_empty_rss_instead_of_raw_xml(monkeypatch) -> None:
    class _FakeResponse:
        def __init__(self, url: str):
            self.url = url
            self.status_code = 200
            self.headers = {"content-type": "application/rss+xml"}
            self.text = """<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>"""

        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str, headers: dict[str, str]):  # noqa: ARG002
            return _FakeResponse(url)

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda *args, **kwargs: _FakeClient())

    tool = WebFetchTool()
    result = await tool.execute("https://example.com/feed.xml")
    payload = json.loads(result)

    assert payload["error"] == "RSS/Atom feed returned no extractable entries"
    assert payload["status"] == 200
    assert "text" not in payload


def test_web_fetch_flags_x_placeholder_pages() -> None:
    text = "# [no-title]\n\nSomething went wrong, but don’t fret — let’s give it another shot."

    reason = WebFetchTool._detect_unusable_page("https://x.com/karpathy", "<html></html>", text)

    assert reason == "x.com returned a placeholder error page instead of concrete post content"


def test_web_fetch_flags_youtube_channel_shell_pages() -> None:
    text = "# OpenAI - YouTube\n\n簡介新聞中心版權聯絡我們創作者刊登廣告開發人員條款私隱政策及安全YouTube 的運作方式"

    reason = WebFetchTool._detect_unusable_page(
        "https://www.youtube.com/@OpenAI/videos",
        "<html><body></body></html>",
        text,
    )

    assert reason == "YouTube channel page returned a generic shell without concrete videos"


def test_web_fetch_builds_fallback_candidates_for_x_status_pages() -> None:
    candidates = WebFetchTool._fallback_candidates("https://x.com/karpathy/status/123")

    assert candidates == [("reader", "https://r.jina.ai/http://x.com/karpathy/status/123")]


def test_web_fetch_builds_rss_then_reader_fallbacks_for_youtube_channel_pages() -> None:
    candidates = WebFetchTool._fallback_candidates("https://www.youtube.com/channel/UC123ABC/videos")

    assert candidates == [
        ("youtube-rss", "https://www.youtube.com/feeds/videos.xml?channel_id=UC123ABC"),
        ("reader", "https://r.jina.ai/http://www.youtube.com/channel/UC123ABC/videos"),
    ]


def test_web_fetch_builds_youtube_rss_fallback_from_handle_page_html() -> None:
    html = '<link rel="alternate" type="application/rss+xml" title="RSS" href="https://www.youtube.com/feeds/videos.xml?channel_id=UCvi5jNRoRVm436TVAXet1kQ">'

    candidates = WebFetchTool._fallback_candidates(
        "https://www.youtube.com/@LatentSpaceTV/videos",
        html,
    )

    assert candidates == [
        ("youtube-rss", "https://www.youtube.com/feeds/videos.xml?channel_id=UCvi5jNRoRVm436TVAXet1kQ"),
        ("reader", "https://r.jina.ai/http://www.youtube.com/@LatentSpaceTV/videos"),
    ]


def test_web_fetch_builds_discovered_feed_fallbacks_for_source_pages() -> None:
    html = """
    <html><head>
      <link rel="alternate" type="application/rss+xml" title="RSS" href="/news/rss.xml">
      <link rel="alternate" type="application/atom+xml" href="https://example.com/blog/atom.xml">
    </head></html>
    """

    candidates = WebFetchTool._fallback_candidates("https://example.com/news", html)

    assert candidates == [
        ("discovered-feed", "https://example.com/news/rss.xml"),
        ("discovered-feed", "https://example.com/blog/atom.xml"),
    ]


def test_web_fetch_flags_source_landing_pages_with_feed_metadata() -> None:
    html = """
    <html><head>
      <link rel="alternate" type="application/rss+xml" title="RSS" href="/news/rss.xml">
    </head><body>Latest company updates</body></html>
    """

    reason = WebFetchTool._detect_unusable_page(
        "https://example.com/news",
        html,
        "# Example News\n\nLatest company updates",
    )

    assert reason == "Source landing page exposed feed metadata but returned no concrete entries"


@pytest.mark.asyncio
async def test_web_fetch_falls_back_to_reader_for_x_placeholder_pages(monkeypatch) -> None:
    class _FakeResponse:
        def __init__(self, url: str, headers: dict[str, str], text: str, status_code: int = 200):
            self.url = url
            self.headers = headers
            self.text = text
            self.status_code = status_code

        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str, headers: dict[str, str]):  # noqa: ARG002
            if url == "https://x.com/karpathy/status/123":
                return _FakeResponse(
                    url,
                    {"content-type": "text/html"},
                    "<html><head><title>X</title></head><body>Something went wrong, but don’t fret — let’s give it another shot.</body></html>",
                )
            if url == "https://r.jina.ai/http://x.com/karpathy/status/123":
                return _FakeResponse(
                    url,
                    {"content-type": "text/plain"},
                    "# Karpathy post\n\nTesting-time compute is becoming product surface area.",
                )
            raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda *args, **kwargs: _FakeClient())

    tool = WebFetchTool()
    result = await tool.execute("https://x.com/karpathy/status/123")
    payload = json.loads(result)

    assert payload["extractor"] == "reader-fallback"
    assert payload["usedFallback"] is True
    assert payload["fallbackUrl"] == "https://r.jina.ai/http://x.com/karpathy/status/123"
    assert "Testing-time compute" in payload["text"]


def test_web_fetch_flags_reader_shell_for_missing_x_post() -> None:
    text = (
        "Title: X\n\nDon’t miss what’s happening\n\nLog in\n\nSign up\n\n"
        "Hmm...this page doesn’t exist. Try searching for something else."
    )

    reason = WebFetchTool._detect_unusable_page(
        "https://r.jina.ai/http://x.com/karpathy/status/123",
        text,
        text,
    )

    assert reason == "x.com reader fallback returned a login or missing-page shell"


def test_web_fetch_flags_live_youtube_shell_pages_in_multiple_locales() -> None:
    text = (
        "# Latent Space TV - YouTube\n\n概要 プレスルーム 著作権 クリエイター向け "
        "開発者向け 利用規約 ポリシーとセキュリティ"
    )

    reason = WebFetchTool._detect_unusable_page(
        "https://www.youtube.com/@LatentSpaceTV/videos",
        "<html><body></body></html>",
        text,
    )

    assert reason == "YouTube channel page returned a generic shell without concrete videos"


@pytest.mark.asyncio
async def test_web_fetch_falls_back_to_youtube_rss_for_channel_pages(monkeypatch) -> None:
    class _FakeResponse:
        def __init__(self, url: str, headers: dict[str, str], text: str, status_code: int = 200):
            self.url = url
            self.headers = headers
            self.text = text
            self.status_code = status_code

        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str, headers: dict[str, str]):  # noqa: ARG002
            if url == "https://www.youtube.com/channel/UC123ABC/videos":
                return _FakeResponse(
                    url,
                    {"content-type": "text/html"},
                    "<html><body>簡介新聞中心版權聯絡我們創作者刊登廣告開發人員條款私隱政策及安全YouTube 的運作方式</body></html>",
                )
            if url == "https://www.youtube.com/feeds/videos.xml?channel_id=UC123ABC":
                return _FakeResponse(
                    url,
                    {"content-type": "application/atom+xml"},
                    """<?xml version="1.0" encoding="UTF-8"?>
                    <feed xmlns="http://www.w3.org/2005/Atom">
                      <title>YouTube</title>
                      <entry>
                        <title>Agent update</title>
                        <link rel="alternate" href="https://www.youtube.com/watch?v=abc123" />
                        <updated>2026-03-08T01:00:00+00:00</updated>
                      </entry>
                    </feed>""",
                )
            raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda *args, **kwargs: _FakeClient())

    tool = WebFetchTool()
    result = await tool.execute("https://www.youtube.com/channel/UC123ABC/videos")
    payload = json.loads(result)

    assert payload["extractor"] == "youtube-rss-fallback"
    assert payload["usedFallback"] is True
    assert payload["fallbackUrl"] == "https://www.youtube.com/feeds/videos.xml?channel_id=UC123ABC"
    assert "[Agent update](https://www.youtube.com/watch?v=abc123)" in payload["text"]


@pytest.mark.asyncio
async def test_web_fetch_falls_back_to_youtube_rss_for_handle_pages_using_html_metadata(monkeypatch) -> None:
    class _FakeResponse:
        def __init__(self, url: str, headers: dict[str, str], text: str, status_code: int = 200):
            self.url = url
            self.headers = headers
            self.text = text
            self.status_code = status_code

        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str, headers: dict[str, str]):  # noqa: ARG002
            if url == "https://www.youtube.com/@LatentSpaceTV/videos":
                return _FakeResponse(
                    url,
                    {"content-type": "text/html"},
                    """
                    <html><head>
                      <link rel="alternate" type="application/rss+xml" title="RSS"
                        href="https://www.youtube.com/feeds/videos.xml?channel_id=UCvi5jNRoRVm436TVAXet1kQ">
                    </head><body>
                      概要 プレスルーム 著作権 クリエイター向け 開発者向け 利用規約 ポリシーとセキュリティ
                    </body></html>
                    """,
                )
            if url == "https://www.youtube.com/feeds/videos.xml?channel_id=UCvi5jNRoRVm436TVAXet1kQ":
                return _FakeResponse(
                    url,
                    {"content-type": "application/atom+xml"},
                    """<?xml version="1.0" encoding="UTF-8"?>
                    <feed xmlns="http://www.w3.org/2005/Atom">
                      <title>YouTube</title>
                      <entry>
                        <title>Agent update</title>
                        <link rel="alternate" href="https://www.youtube.com/watch?v=abc123" />
                        <updated>2026-03-08T01:00:00+00:00</updated>
                      </entry>
                    </feed>""",
                )
            raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda *args, **kwargs: _FakeClient())

    tool = WebFetchTool()
    result = await tool.execute("https://www.youtube.com/@LatentSpaceTV/videos")
    payload = json.loads(result)

    assert payload["extractor"] == "youtube-rss-fallback"
    assert payload["usedFallback"] is True
    assert payload["fallbackUrl"] == "https://www.youtube.com/feeds/videos.xml?channel_id=UCvi5jNRoRVm436TVAXet1kQ"
    assert "[Agent update](https://www.youtube.com/watch?v=abc123)" in payload["text"]


@pytest.mark.asyncio
async def test_web_fetch_falls_back_to_discovered_feed_for_source_pages(monkeypatch) -> None:
    class _FakeResponse:
        def __init__(self, url: str, headers: dict[str, str], text: str, status_code: int = 200):
            self.url = url
            self.headers = headers
            self.text = text
            self.status_code = status_code

        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str, headers: dict[str, str]):  # noqa: ARG002
            if url == "https://example.com/news":
                return _FakeResponse(
                    url,
                    {"content-type": "text/html"},
                    """
                    <html><head>
                      <link rel="alternate" type="application/rss+xml" title="RSS" href="/news/rss.xml">
                    </head><body>Latest company updates</body></html>
                    """,
                )
            if url == "https://example.com/news/rss.xml":
                return _FakeResponse(
                    url,
                    {"content-type": "application/rss+xml"},
                    """<?xml version="1.0"?>
                    <rss version="2.0">
                      <channel>
                        <title>Example News</title>
                        <item>
                          <title>Launch update</title>
                          <link>https://example.com/news/launch-update</link>
                          <pubDate>Sun, 08 Mar 2026 02:19:13 GMT</pubDate>
                        </item>
                      </channel>
                    </rss>""",
                )
            raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda *args, **kwargs: _FakeClient())

    tool = WebFetchTool()
    result = await tool.execute("https://example.com/news")
    payload = json.loads(result)

    assert payload["extractor"] == "discovered-feed-fallback"
    assert payload["usedFallback"] is True
    assert payload["fallbackUrl"] == "https://example.com/news/rss.xml"
    assert "[Launch update](https://example.com/news/launch-update)" in payload["text"]


@pytest.mark.asyncio
async def test_web_fetch_returns_original_error_when_all_fallbacks_fail(monkeypatch) -> None:
    class _FakeResponse:
        def __init__(self, url: str, headers: dict[str, str], text: str, status_code: int = 200):
            self.url = url
            self.headers = headers
            self.text = text
            self.status_code = status_code

        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str, headers: dict[str, str]):  # noqa: ARG002
            if url == "https://x.com/karpathy":
                return _FakeResponse(
                    url,
                    {"content-type": "text/html"},
                    "<html><body>Something went wrong, but don’t fret — let’s give it another shot.</body></html>",
                )
            if url == "https://r.jina.ai/http://x.com/karpathy":
                return _FakeResponse(url, {"content-type": "text/plain"}, "")
            raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda *args, **kwargs: _FakeClient())

    tool = WebFetchTool()
    result = await tool.execute("https://x.com/karpathy")
    payload = json.loads(result)

    assert payload["error"] == "x.com returned a placeholder error page instead of concrete post content"
    assert payload["attemptedFallbacks"] == [
        {"strategy": "reader", "url": "https://r.jina.ai/http://x.com/karpathy"}
    ]
