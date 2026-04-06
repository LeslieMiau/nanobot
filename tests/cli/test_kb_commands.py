from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.schema import Config
from nanobot.knowledge.service import KnowledgeBase


runner = CliRunner()


class _FakeProvider:
    def __init__(self, *responses: str):
        self._responses = list(responses)

    async def chat_with_retry(self, **kwargs):
        del kwargs
        return SimpleNamespace(content=self._responses.pop(0))


def _config_with_workspace(workspace: Path) -> Config:
    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config.knowledge.enabled = True
    return config


def test_kb_status_reports_empty_workspace(tmp_path: Path) -> None:
    config = _config_with_workspace(tmp_path / "workspace")

    with patch("nanobot.config.loader.load_config", return_value=config):
        result = runner.invoke(app, ["kb", "status"])

    assert result.exit_code == 0
    assert "Knowledge Status" in result.stdout
    assert "Total pages: 0" in result.stdout


def test_kb_ingest_command_creates_pages(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    source = workspace / "source.md"
    source.write_text("# FastAPI\n\nFastAPI uses Pydantic.\n", encoding="utf-8")
    config = _config_with_workspace(workspace)
    provider = _FakeProvider(
        """
        {
          "summary": "FastAPI uses Pydantic.",
          "topics": ["API Stack"],
          "entities": ["FastAPI", "Pydantic"],
          "claims": ["FastAPI uses Pydantic."],
          "contradictions": [],
          "supersedes": []
        }
        """
    )

    with patch("nanobot.config.loader.load_config", return_value=config), \
         patch("nanobot.cli.commands._maybe_make_provider", return_value=provider):
        result = runner.invoke(app, ["kb", "ingest", str(source)])

    assert result.exit_code == 0
    assert "Ingested source" in result.stdout
    assert (workspace / "knowledge" / "wiki" / "topics" / "api-stack.md").exists()


def test_kb_ask_command_can_save_synthesis(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    config = _config_with_workspace(workspace)
    provider = _FakeProvider(
        """
        {
          "summary": "FastAPI uses Pydantic.",
          "topics": ["API Stack"],
          "entities": ["FastAPI", "Pydantic"],
          "claims": ["FastAPI uses Pydantic."],
          "contradictions": [],
          "supersedes": []
        }
        """,
        "FastAPI uses Pydantic.",
    )
    source = workspace / "source.md"
    source.write_text("# FastAPI\n\nFastAPI uses Pydantic.\n", encoding="utf-8")
    kb = KnowledgeBase(workspace, config.knowledge)

    import asyncio

    asyncio.run(kb.ingest(str(source), provider=provider, model="test-model"))

    with patch("nanobot.config.loader.load_config", return_value=config), \
         patch("nanobot.cli.commands._maybe_make_provider", return_value=provider):
        result = runner.invoke(app, ["kb", "ask", "What does FastAPI use?", "--save"])

    assert result.exit_code == 0
    assert "Saved synthesis:" in result.stdout


def test_kb_lint_command_reports_findings(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    config = _config_with_workspace(workspace)
    kb = KnowledgeBase(workspace, config.knowledge)
    kb.ensure_structure()
    (workspace / "knowledge" / "wiki" / "topics").mkdir(parents=True, exist_ok=True)
    (workspace / "knowledge" / "wiki" / "topics" / "orphan.md").write_text(
        "---\n"
        "type: topic\n"
        "title: Orphan\n"
        "aliases:\n"
        "source_ids:\n"
        "  - src\n"
        "updated_at: 2026-04-06T10:00:00Z\n"
        "links_out:\n"
        "---\n\n"
        "# Orphan\n\n## Overview\nNo inbound links.\n",
        encoding="utf-8",
    )

    with patch("nanobot.config.loader.load_config", return_value=config):
        result = runner.invoke(app, ["kb", "lint"])

    assert result.exit_code == 1
    assert "[orphan_page]" in result.stdout


def test_kb_import_memory_command_creates_project_context_page(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    memory_dir = workspace / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text(
        "# Long-term Memory\n\n## Project Context\n\n- The system uses FastAPI.\n",
        encoding="utf-8",
    )
    config = _config_with_workspace(workspace)

    with patch("nanobot.config.loader.load_config", return_value=config):
        result = runner.invoke(app, ["kb", "import-memory"])

    assert result.exit_code == 0
    assert "Imported project context" in result.stdout
    assert (workspace / "knowledge" / "wiki" / "topics" / "project-context.md").exists()
