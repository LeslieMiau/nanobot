from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.config.schema import KnowledgeConfig
from nanobot.knowledge.markdown import dump_page, load_page
from nanobot.knowledge.models import KnowledgePage, PageMetadata
from nanobot.knowledge.service import KnowledgeBase


class _FakeProvider:
    def __init__(self, *responses: str):
        self._responses = list(responses)

    async def chat_with_retry(self, **kwargs):
        del kwargs
        if not self._responses:
            raise AssertionError("unexpected provider call")
        return SimpleNamespace(content=self._responses.pop(0))


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    return workspace


def test_frontmatter_round_trip(tmp_path: Path) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    page_path = knowledge_root / "wiki" / "topics" / "python.md"
    page_path.parent.mkdir(parents=True)
    page = KnowledgePage(
        path=Path("wiki/topics/python.md"),
        metadata=PageMetadata(
            type="topic",
            title="Python",
            aliases=["py"],
            source_ids=["src-1"],
            updated_at="2026-04-06T10:00:00Z",
            links_out=["wiki/entities/fastapi.md"],
        ),
        body="# Python\n\n## Overview\nA programming language.",
    )
    page_path.write_text(dump_page(page), encoding="utf-8")

    loaded = load_page(page_path, root=knowledge_root)

    assert loaded.path == Path("wiki/topics/python.md")
    assert loaded.metadata.type == "topic"
    assert loaded.metadata.aliases == ["py"]
    assert loaded.metadata.source_ids == ["src-1"]
    assert loaded.metadata.links_out == ["wiki/entities/fastapi.md"]


@pytest.mark.asyncio
async def test_ingest_creates_raw_pages_index_and_log(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source_file = workspace / "fastapi.md"
    source_file.write_text(
        "# FastAPI Notes\n\nFastAPI works with Pydantic and asyncio for API development.\n",
        encoding="utf-8",
    )
    provider = _FakeProvider(
        """
        {
          "summary": "FastAPI and Pydantic are used together for async APIs.",
          "topics": ["Async APIs"],
          "entities": ["FastAPI", "Pydantic"],
          "claims": ["FastAPI uses Pydantic models.", "Asyncio is part of the stack."],
          "contradictions": [],
          "supersedes": []
        }
        """
    )
    kb = KnowledgeBase(workspace, KnowledgeConfig(enabled=True))

    result = await kb.ingest(str(source_file), provider=provider, model="test-model")

    assert result.raw_path.exists()
    assert source_file.read_text(encoding="utf-8").startswith("# FastAPI Notes")
    assert result.source_page.exists()
    assert (workspace / "knowledge" / "wiki" / "topics" / "async-apis.md").exists()
    assert (workspace / "knowledge" / "wiki" / "entities" / "fastapi.md").exists()

    index = (workspace / "knowledge" / "index.md").read_text(encoding="utf-8")
    log = (workspace / "knowledge" / "log.md").read_text(encoding="utf-8")
    assert f"wiki/sources/{result.source_id}.md" in index
    assert f"ingest | {result.source_id}" in log


@pytest.mark.asyncio
async def test_ask_saves_synthesis_with_citations(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source_file = workspace / "stack.md"
    source_file.write_text(
        "# API Stack\n\nFastAPI uses Pydantic models and Starlette underneath.\n",
        encoding="utf-8",
    )
    provider = _FakeProvider(
        """
        {
          "summary": "FastAPI is paired with Pydantic and Starlette.",
          "topics": ["API Stack"],
          "entities": ["FastAPI", "Pydantic", "Starlette"],
          "claims": ["FastAPI relies on Pydantic.", "Starlette underpins the HTTP layer."],
          "contradictions": [],
          "supersedes": []
        }
        """,
        "FastAPI uses Pydantic for models and Starlette for the HTTP layer.",
    )
    kb = KnowledgeBase(workspace, KnowledgeConfig(enabled=True, auto_file_answers=False))
    await kb.ingest(str(source_file), provider=provider, model="test-model")

    answer = await kb.ask(
        "How does FastAPI use Pydantic?",
        provider=provider,
        model="test-model",
        save=True,
    )

    assert "[page:" in answer.answer
    assert answer.saved_path is not None
    assert answer.saved_path.exists()
    saved = answer.saved_path.read_text(encoding="utf-8")
    assert "## Supporting Pages" in saved
    assert "[page:wiki/" in saved


def test_lint_detects_orphan_backlink_superseded_and_conflict(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    kb = KnowledgeBase(workspace, KnowledgeConfig(enabled=True))
    kb.ensure_structure()

    orphan = KnowledgePage(
        path=Path("wiki/topics/orphan.md"),
        metadata=PageMetadata(
            type="topic",
            title="Orphan",
            aliases=[],
            source_ids=["src-orphan"],
            updated_at="2026-04-06T10:00:00Z",
            links_out=[],
        ),
        body="# Orphan\n\n## Overview\nA page with no inbound links.",
    )
    backlink = KnowledgePage(
        path=Path("wiki/entities/backlink.md"),
        metadata=PageMetadata(
            type="entity",
            title="Backlink",
            aliases=[],
            source_ids=["src-backlink"],
            updated_at="2026-04-06T10:00:00Z",
            links_out=["wiki/topics/orphan.md"],
        ),
        body="# Backlink\n\n## Overview\nMissing reciprocal link.",
    )
    old_source = KnowledgePage(
        path=Path("wiki/sources/old-source.md"),
        metadata=PageMetadata(
            type="source",
            title="Old Source",
            aliases=[],
            source_ids=["old-source"],
            updated_at="2026-04-06T10:00:00Z",
            links_out=[],
        ),
        body="# Old Source\n\n## Summary\nOld claim.",
    )
    new_source = KnowledgePage(
        path=Path("wiki/sources/new-source.md"),
        metadata=PageMetadata(
            type="source",
            title="New Source",
            aliases=[],
            source_ids=["new-source"],
            updated_at="2026-04-06T10:00:00Z",
            links_out=[],
        ),
        body="# New Source\n\n## Summary\nNew claim.\n\n## Supersedes\n- old-source",
    )
    conflict = KnowledgePage(
        path=Path("wiki/topics/conflict.md"),
        metadata=PageMetadata(
            type="topic",
            title="Conflict",
            aliases=[],
            source_ids=["src-conflict"],
            updated_at="2026-04-06T10:00:00Z",
            links_out=[],
        ),
        body="# Conflict\n\n## Conflicts\n- Two sources disagree.",
    )

    for page in (orphan, backlink, old_source, new_source, conflict):
        full_path = workspace / "knowledge" / page.path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(dump_page(page), encoding="utf-8")

    findings = kb.lint()
    codes = {finding.code for finding in findings}

    assert "orphan_page" in codes
    assert "missing_backlink" in codes
    assert "superseded_source_unmarked" in codes
    assert "explicit_conflict" in codes


@pytest.mark.asyncio
async def test_full_workflow_can_lint_clean(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source_one = workspace / "source-one.md"
    source_two = workspace / "source-two.md"
    source_one.write_text(
        "# FastAPI Guide\n\nFastAPI uses Pydantic models for request validation.\n",
        encoding="utf-8",
    )
    source_two.write_text(
        "# Starlette Note\n\nStarlette provides the HTTP foundation under FastAPI.\n",
        encoding="utf-8",
    )

    provider = _FakeProvider(
        """
        {
          "summary": "FastAPI uses Pydantic models for API validation.",
          "topics": ["API Stack"],
          "entities": ["FastAPI", "Pydantic"],
          "claims": ["FastAPI uses Pydantic models."],
          "contradictions": [],
          "supersedes": []
        }
        """,
        """
        {
          "summary": "Starlette provides the HTTP foundation used by FastAPI.",
          "topics": ["API Stack"],
          "entities": ["FastAPI", "Starlette"],
          "claims": ["Starlette underpins FastAPI."],
          "contradictions": [],
          "supersedes": []
        }
        """,
        "FastAPI uses Pydantic models and builds on Starlette for the HTTP layer.",
    )

    kb = KnowledgeBase(workspace, KnowledgeConfig(enabled=True))
    await kb.ingest(str(source_one), provider=provider, model="test-model")
    await kb.ingest(str(source_two), provider=provider, model="test-model")
    answer = await kb.ask(
        "What does FastAPI use for validation and HTTP?",
        provider=provider,
        model="test-model",
        save=True,
    )
    findings = kb.lint()

    assert answer.saved_path is not None
    assert findings == []
