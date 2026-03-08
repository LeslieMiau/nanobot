import json

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
          openai / openai-python
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
