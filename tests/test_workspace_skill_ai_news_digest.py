from pathlib import Path

from nanobot.agent.skills import SkillsLoader


def test_workspace_ai_news_digest_skill_is_discoverable() -> None:
    workspace = Path(__file__).resolve().parents[1]
    loader = SkillsLoader(workspace)

    skills = loader.list_skills(filter_unavailable=False)
    names = {skill["name"] for skill in skills}

    assert "ai-news-digest" in names


def test_workspace_ai_news_digest_skill_loads_content() -> None:
    workspace = Path(__file__).resolve().parents[1]
    loader = SkillsLoader(workspace)

    content = loader.load_skill("ai-news-digest")

    assert content is not None
    assert "official announcements and RSS feeds (OpenAI, Anthropic, Google AI)" in content
    assert 'cron_expr="0 8 * * *"' in content
    assert "previous day 08:00 to the current day 08:00" in content
    assert "first-hand sources over quantity" in content
    assert "include only domain-relevant statements" in content
    assert "Only include an item when you can identify a concrete underlying artifact" in content
    assert "Treat X as a secondary heat signal" in content
    assert "Do not treat `x.com/<account>` profile pages as concrete artifacts" in content
    assert "Telegram formatting constraints (lightweight rich text)" in content
    assert "## 本轮未纳入" in content


def test_workspace_ai_news_digest_skill_references_sources_file() -> None:
    workspace = Path(__file__).resolve().parents[1]
    skill_path = workspace / "skills" / "ai-news-digest" / "SKILL.md"
    sources_path = workspace / "skills" / "ai-news-digest" / "references" / "sources.md"

    assert sources_path.exists()

    skill_content = skill_path.read_text(encoding="utf-8")
    sources_content = sources_path.read_text(encoding="utf-8")

    assert "references/sources.md" in skill_content
    assert "OpenAI" in sources_content
    assert "Hacker News" in sources_content
    assert "professional AI-domain posts" in sources_content
    assert "previous day 08:00 to the current day 08:00" in sources_content
    assert "GitHub Trending" in sources_content
    assert "Treat Hacker News and GitHub Trending as heat signals only" in sources_content
    assert "Recommended Test Sources (English-first)" in sources_content
    assert "https://openai.com/news/rss.xml" in sources_content
    assert "https://blog.google/rss/" in sources_content
    assert "https://export.arxiv.org/rss/cs.AI" in sources_content
