from nanobot.channels.telegram import _markdown_to_telegram_html, _split_markdown_for_telegram


def test_markdown_to_telegram_html_keeps_lightweight_rich_text_structure() -> None:
    markdown = """# 今日 AI 重要资讯

## 1. OpenAI 发布更新
- 来源: OpenAI
- 链接: [OpenAI News](https://openai.com/news/rss.xml?utm_source=nanobot&utm_medium=telegram)
"""

    html = _markdown_to_telegram_html(markdown)

    assert "<b>今日 AI 重要资讯</b>" in html
    assert "<b>1. OpenAI 发布更新</b>" in html
    assert "• 来源: OpenAI" in html
    assert (
        '<a href="https://openai.com/news/rss.xml?utm_source=nanobot&amp;utm_medium=telegram">OpenAI News</a>'
        in html
    )


def test_split_markdown_for_telegram_keeps_markdown_links_intact() -> None:
    link = "[OpenAI News](https://openai.com/news/rss.xml?utm_source=nanobot&utm_medium=telegram)"
    content = (
        "# 今日 AI 重要资讯\n\n"
        "## 1. OpenAI 发布更新\n"
        f"- 要点: {'a' * 180}\n"
        f"- 链接: {link}\n"
        "- 热度归因: HN front page\n"
    )

    chunks = _split_markdown_for_telegram(content, max_len=220)

    assert len(chunks) > 1
    assert sum(link in chunk for chunk in chunks) == 1
    assert not any("[OpenAI News](" in chunk and ")" not in chunk for chunk in chunks)
    assert not any("https://openai.com/news/rss.xml" in chunk and "[OpenAI News](" not in chunk for chunk in chunks)
