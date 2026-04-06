from pathlib import Path

from nanobot.agent.skills import SkillsLoader


EXAMPLE_WORKSPACE = Path(__file__).resolve().parents[1] / "examples" / "workspace"


def test_workspace_content_factory_skill_is_discoverable() -> None:
    loader = SkillsLoader(EXAMPLE_WORKSPACE)

    skills = loader.list_skills(filter_unavailable=False)
    names = {skill["name"] for skill in skills}

    assert "content-factory" in names


def test_workspace_content_factory_skill_loads_content() -> None:
    loader = SkillsLoader(EXAMPLE_WORKSPACE)

    content = loader.load_skill("content-factory")

    assert content is not None
    assert "TradingCat" in content
    assert "content_queue/YYYY-MM-DD-slug.md" in content
    assert "/image-confirm" in content
    assert "Douyin" in content
    assert "X adaptation" in content
