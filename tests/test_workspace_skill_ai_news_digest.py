from pathlib import Path

from nanobot.agent.skills import SkillsLoader


EXAMPLE_WORKSPACE = Path(__file__).resolve().parents[1] / "examples" / "workspace"


def test_workspace_ai_news_digest_skill_is_discoverable() -> None:
    loader = SkillsLoader(EXAMPLE_WORKSPACE)

    skills = loader.list_skills(filter_unavailable=False)
    names = {skill["name"] for skill in skills}

    assert "ai-news-digest" in names


def test_workspace_ai_news_digest_skill_loads_content() -> None:
    loader = SkillsLoader(EXAMPLE_WORKSPACE)

    content = loader.load_skill("ai-news-digest")

    assert content is not None
    assert "# AI Builder Signal Radar" in content
    assert "only answers 4 question types" in content
    assert "Layer A: 每日必看" in content
    assert "Layer B: 每周深读 / 深听" in content
    assert "Layer C: 重大事件触发" in content
    assert "Builder relevance: 30" in content
    assert "Practicality: 20" in content
    assert "`85+`: 必推" in content
    assert "`70-84`: 候选" in content
    assert "`<70`: 默认过滤" in content
    assert "Module 1: Must Know" in content
    assert "Do not add any preamble" in content
    assert "process narration" in content
    assert "Module 2: Builder Takeaway" in content
    assert "Module 3: One Deep Read / Listen" in content
    assert "Module 4: Action Items" in content
    assert "AI Builder Weekly Calibration" in content
    assert "cron_expr=\"0 8 * * *\"" in content
    assert "cron_expr=\"0 9 * * 6\"" in content
    assert "Before creating a new schedule, list existing cron jobs first to avoid duplicates." in content


def test_workspace_ai_news_digest_skill_references_sources_file() -> None:
    skill_path = EXAMPLE_WORKSPACE / "skills" / "ai-news-digest" / "SKILL.md"
    sources_path = EXAMPLE_WORKSPACE / "skills" / "ai-news-digest" / "references" / "sources.md"

    assert sources_path.exists()

    skill_content = skill_path.read_text(encoding="utf-8")
    sources_content = sources_path.read_text(encoding="utf-8")

    assert "references/sources.md" in skill_content
    assert "Tier 1: Daily Must-Know" in sources_content
    assert "Tier 2: Weekly Deep Reads / Listens" in sources_content
    assert "Andrej Karpathy" in sources_content
    assert "Simon Willison" in sources_content
    assert "宝玉" in sources_content
    assert "Latent Space" in sources_content
    assert "OpenAI (official)" in sources_content
    assert "Anthropic (official)" in sources_content
    assert "Dwarkesh" in sources_content
    assert "张小珺商业访谈录" in sources_content
    assert "SemiAnalysis" in sources_content
    assert "https://rsshub.app/youtube/user/@dwarkeshpatel" in sources_content
    assert "https://rsshub.app/youtube/user/@LatentSpaceTV" in sources_content
    assert "Do not rely on RSSHub Twitter/X routes as a primary scheduled source" in sources_content
    assert "Major Event Trigger Watchlist" in sources_content
    assert "Noise Filter Baseline" in sources_content
