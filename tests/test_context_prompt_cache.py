"""Tests for cache-friendly prompt construction."""

from __future__ import annotations

from datetime import datetime as real_datetime
from importlib.resources import files as pkg_files
from pathlib import Path
import datetime as datetime_module

from nanobot.agent.context import ContextBuilder

EXAMPLE_WORKSPACE = Path(__file__).resolve().parents[1] / "examples" / "workspace"


class _FakeDatetime(real_datetime):
    current = real_datetime(2026, 2, 24, 13, 59)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return cls.current


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    return workspace


def test_bootstrap_files_are_backed_by_templates() -> None:
    template_dir = pkg_files("nanobot") / "templates"

    for filename in ContextBuilder.BOOTSTRAP_FILES:
        assert (template_dir / filename).is_file(), f"missing bootstrap template: {filename}"


def test_system_prompt_stays_stable_when_clock_changes(tmp_path, monkeypatch) -> None:
    """System prompt should not change just because wall clock minute changes."""
    monkeypatch.setattr(datetime_module, "datetime", _FakeDatetime)

    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    _FakeDatetime.current = real_datetime(2026, 2, 24, 13, 59)
    prompt1 = builder.build_system_prompt()

    _FakeDatetime.current = real_datetime(2026, 2, 24, 14, 0)
    prompt2 = builder.build_system_prompt()

    assert prompt1 == prompt2


def test_runtime_context_is_separate_untrusted_user_message(tmp_path) -> None:
    """Runtime metadata should be merged with the user message."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = builder.build_messages(
        history=[],
        current_message="Return exactly: OK",
        channel="cli",
        chat_id="direct",
    )

    assert messages[0]["role"] == "system"
    assert "## Current Session" not in messages[0]["content"]

    # Runtime context is now merged with user message into a single message
    assert messages[-1]["role"] == "user"
    user_content = messages[-1]["content"]
    assert isinstance(user_content, str)
    assert ContextBuilder._RUNTIME_CONTEXT_TAG in user_content
    assert "Current Time:" in user_content
    assert "Channel: cli" in user_content
    assert "Chat ID: direct" in user_content
    assert "Return exactly: OK" in user_content

def test_system_prompt_requests_direct_non_coding_answers(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt()

    assert "answer with the final result first" in prompt
    assert "Do not reveal hidden reasoning" in prompt


def test_system_prompt_loads_agents_soul_and_user_but_omits_tools_by_default(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    (workspace / "AGENTS.md").write_text("agent rules", encoding="utf-8")
    (workspace / "SOUL.md").write_text("default style", encoding="utf-8")
    (workspace / "USER.md").write_text("profile", encoding="utf-8")
    (workspace / "TOOLS.md").write_text("tool notes", encoding="utf-8")
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt()

    assert "## AGENTS.md" in prompt
    assert "agent rules" in prompt
    assert "## SOUL.md" in prompt
    assert "default style" in prompt
    assert "## USER.md" in prompt
    assert "profile" in prompt
    assert "## TOOLS.md" not in prompt
    assert "# Skills" not in prompt


def test_coding_prompt_is_injected_only_when_coding_mode_enabled(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    (workspace / "CODING.md").write_text("Always inspect files before editing.", encoding="utf-8")
    builder = ContextBuilder(workspace)

    normal = builder.build_messages(history=[], current_message="hello", coding_mode=False)
    coding = builder.build_messages(history=[], current_message="fix bug", coding_mode=True)

    assert "Always inspect files before editing." not in normal[0]["content"]
    assert "Always inspect files before editing." in coding[0]["content"]


def test_requested_skills_are_injected_into_system_prompt() -> None:
    builder = ContextBuilder(EXAMPLE_WORKSPACE)

    prompt = builder.build_system_prompt(skill_names=["ai-news-digest"])

    assert "# Requested Skills" in prompt
    assert "### Skill: ai-news-digest" in prompt
    assert "AI Builder Signal Radar" in prompt


def test_cron_prompt_includes_structured_source_priorities_for_referenced_skill() -> None:
    builder = ContextBuilder(EXAMPLE_WORKSPACE)

    prompt = builder.build_cron_prompt(
        "每日 AI 要闻",
        "Use ai-news-digest to generate the AI Builder Signal Radar daily digest.",
    )

    assert "Structured source priorities" in prompt
    assert "Skill: ai-news-digest" in prompt
    assert "Priority order: primary -> fallback -> signal-only" in prompt
    assert "OpenAI (official) | News RSS | primary" in prompt
    assert "Andrej Karpathy | X (signal) | signal-only" in prompt
