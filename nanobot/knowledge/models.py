"""Typed models for the persistent knowledge wiki."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


PageType = Literal["source", "topic", "entity", "synthesis"]


@dataclass(slots=True)
class PageMetadata:
    type: PageType
    title: str
    aliases: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    updated_at: str = ""
    links_out: list[str] = field(default_factory=list)


@dataclass(slots=True)
class KnowledgePage:
    path: Path
    metadata: PageMetadata
    body: str

    @property
    def relative_path(self) -> str:
        return self.path.as_posix()


@dataclass(slots=True)
class SourceMaterial:
    source_id: str
    title: str
    origin: str
    content: str
    fetched_via: str
    raw_extension: str = ".md"


@dataclass(slots=True)
class CompiledSource:
    summary: str
    topics: list[str]
    entities: list[str]
    claims: list[str]
    contradictions: list[str]
    supersedes: list[str]


@dataclass(slots=True)
class IngestResult:
    source_id: str
    raw_path: Path
    source_page: Path
    touched_pages: list[Path]
    log_path: Path


@dataclass(slots=True)
class SearchHit:
    page: KnowledgePage
    score: int
    excerpt: str


@dataclass(slots=True)
class KnowledgeAnswer:
    answer: str
    cited_pages: list[str]
    cited_source_ids: list[str]
    selected_pages: list[Path]
    saved_path: Path | None = None


@dataclass(slots=True)
class LintFinding:
    code: str
    message: str
    page: str | None = None
    related: list[str] = field(default_factory=list)


@dataclass(slots=True)
class KnowledgeStatus:
    enabled: bool
    root: Path
    raw_count: int = 0
    source_page_count: int = 0
    topic_page_count: int = 0
    entity_page_count: int = 0
    synthesis_page_count: int = 0

    @property
    def page_count(self) -> int:
        return (
            self.source_page_count
            + self.topic_page_count
            + self.entity_page_count
            + self.synthesis_page_count
        )
