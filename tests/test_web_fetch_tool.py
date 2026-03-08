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
