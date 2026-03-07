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
    assert "Andrej Karpathy" in content
    assert 'cron_expr="0 8 * * *"' in content
    assert "today's hot items" in content
    assert "first-hand sources over quantity" in content
