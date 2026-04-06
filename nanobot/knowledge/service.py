"""Persistent wiki services for knowledge ingest, ask, lint, and import."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from importlib.resources import files as pkg_files
from pathlib import Path
from textwrap import shorten
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx
import json_repair
from loguru import logger
from readability import Document

from nanobot.knowledge.markdown import dump_page, load_page
from nanobot.knowledge.models import (
    CompiledSource,
    IngestResult,
    KnowledgeAnswer,
    KnowledgePage,
    KnowledgeStatus,
    LintFinding,
    PageMetadata,
    SearchHit,
    SourceMaterial,
)
from nanobot.security.network import validate_resolved_url, validate_url_target

if TYPE_CHECKING:
    from nanobot.config.schema import KnowledgeConfig
    from nanobot.providers.base import LLMProvider


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "into", "is", "it", "of", "on", "or", "that", "the", "this",
    "to", "was", "were", "what", "when", "where", "which", "with", "you",
}
_ENTRY_RE = re.compile(r"^- \[(?P<title>.+?)\]\((?P<path>.+?)\) - (?P<summary>.+)$")
_SECTION_RE = re.compile(
    r"(^## (?P<title>[^\n]+)\n(?P<body>.*?))(?=^## |\Z)",
    flags=re.MULTILINE | re.DOTALL,
)
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"


class KnowledgeCompiler:
    """Compile raw sources and retrieved pages into wiki-friendly outputs."""

    def __init__(self, provider: "LLMProvider | None", model: str):
        self.provider = provider
        self.model = model

    async def compile_source(self, source: SourceMaterial, index_context: str) -> CompiledSource:
        if self.provider is None:
            return self._fallback_compile(source)

        prompt = (
            "Compile this source into a persistent wiki update.\n"
            "Return JSON with keys: summary, topics, entities, claims, contradictions, supersedes.\n"
            "topics/entities/claims/contradictions/supersedes must be arrays of strings.\n"
            "Keep topics and entities concise. Do not include markdown fences."
        )
        user = (
            f"## Existing Index\n{index_context or '(empty)'}\n\n"
            f"## Source Title\n{source.title}\n\n"
            f"## Source Origin\n{source.origin}\n\n"
            f"## Source Content\n{source.content[:16000]}"
        )
        try:
            response = await self.provider.chat_with_retry(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user},
                ],
                tools=None,
                tool_choice=None,
            )
            raw = (response.content or "").strip()
            data = json_repair.loads(raw) if raw else {}
            if not isinstance(data, dict):
                raise ValueError("compiler response was not an object")
            return self._normalize_compile_result(source, data)
        except Exception:
            logger.warning("Knowledge compiler fell back to heuristic source compilation")
            return self._fallback_compile(source)

    async def answer_question(self, question: str, pages: list[KnowledgePage]) -> str:
        if self.provider is None:
            return self._fallback_answer(question, pages)

        page_context = "\n\n".join(
            [
                (
                    f"## {page.metadata.title}\n"
                    f"Path: {page.relative_path}\n"
                    f"Sources: {', '.join(page.metadata.source_ids) or 'none'}\n"
                    f"{page.body[:4000]}"
                )
                for page in pages
            ]
        )
        prompt = (
            "Answer the question using only the provided wiki pages.\n"
            "Cite evidence inline with [page:relative/path.md] and [source:source-id].\n"
            "If the evidence is incomplete, say so explicitly."
        )
        try:
            response = await self.provider.chat_with_retry(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"## Question\n{question}\n\n## Pages\n{page_context}"},
                ],
                tools=None,
                tool_choice=None,
            )
            text = (response.content or "").strip()
            return text or self._fallback_answer(question, pages)
        except Exception:
            logger.warning("Knowledge answer synthesis fell back to extractive summary")
            return self._fallback_answer(question, pages)

    def _normalize_compile_result(self, source: SourceMaterial, data: dict[str, Any]) -> CompiledSource:
        summary = _normalize_text(data.get("summary")) or _summarize_text(source.content)
        return CompiledSource(
            summary=summary,
            topics=_clean_str_list(data.get("topics")) or _guess_topics(source.content),
            entities=_clean_str_list(data.get("entities")) or _guess_entities(source.content),
            claims=_clean_str_list(data.get("claims")) or _extract_claims(source.content),
            contradictions=_clean_str_list(data.get("contradictions")),
            supersedes=_clean_str_list(data.get("supersedes")),
        )

    def _fallback_compile(self, source: SourceMaterial) -> CompiledSource:
        return CompiledSource(
            summary=_summarize_text(source.content),
            topics=_guess_topics(source.content),
            entities=_guess_entities(source.content),
            claims=_extract_claims(source.content),
            contradictions=[],
            supersedes=[],
        )

    def _fallback_answer(self, question: str, pages: list[KnowledgePage]) -> str:
        del question
        excerpts = []
        for page in pages:
            excerpt = _summarize_text(page.body, max_chars=220)
            citations = " ".join(
                [f"[page:{page.relative_path}]"] + [f"[source:{sid}]" for sid in page.metadata.source_ids]
            )
            excerpts.append(f"- {page.metadata.title}: {excerpt} {citations}".strip())
        if not excerpts:
            return "No relevant knowledge pages were found."
        return "Best available evidence from the wiki:\n" + "\n".join(excerpts)


class KnowledgeBase:
    """Workspace-scoped persistent knowledge wiki."""

    def __init__(self, workspace: Path, config: "KnowledgeConfig") -> None:
        self.workspace = workspace
        self.config = config
        self.root = workspace / config.dir
        self.raw_dir = self.root / "raw"
        self.wiki_dir = self.root / "wiki"
        self.sources_dir = self.wiki_dir / "sources"
        self.topics_dir = self.wiki_dir / "topics"
        self.entities_dir = self.wiki_dir / "entities"
        self.syntheses_dir = self.wiki_dir / "syntheses"
        self.index_file = self.root / "index.md"
        self.log_file = self.root / "log.md"
        self.schema_file = self.root / "SCHEMA.md"

    def ensure_structure(self) -> None:
        for path in (
            self.root,
            self.raw_dir,
            self.wiki_dir,
            self.sources_dir,
            self.topics_dir,
            self.entities_dir,
            self.syntheses_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

        template_root = pkg_files("nanobot") / "templates" / "knowledge"
        self._ensure_file(self.schema_file, template_root / "SCHEMA.md")
        self._ensure_file(self.index_file, template_root / "index.md")
        self._ensure_file(self.log_file, template_root / "log.md")

    def status(self) -> KnowledgeStatus:
        if not self.root.exists():
            return KnowledgeStatus(enabled=self.config.enabled, root=self.root)
        return KnowledgeStatus(
            enabled=self.config.enabled,
            root=self.root,
            raw_count=len(list(self.raw_dir.glob("*"))) if self.raw_dir.exists() else 0,
            source_page_count=len(list(self.sources_dir.glob("*.md"))) if self.sources_dir.exists() else 0,
            topic_page_count=len(list(self.topics_dir.glob("*.md"))) if self.topics_dir.exists() else 0,
            entity_page_count=len(list(self.entities_dir.glob("*.md"))) if self.entities_dir.exists() else 0,
            synthesis_page_count=len(list(self.syntheses_dir.glob("*.md"))) if self.syntheses_dir.exists() else 0,
        )

    async def ingest(
        self,
        path_or_url: str,
        *,
        provider: "LLMProvider | None",
        model: str,
    ) -> IngestResult:
        self.ensure_structure()
        source = await self._load_source(path_or_url)
        raw_path = self._write_raw_source(source)
        compiler = KnowledgeCompiler(provider, model)
        compiled = await compiler.compile_source(source, self.index_file.read_text(encoding="utf-8"))

        touched: list[Path] = []
        source_page = self._write_source_page(source, compiled, raw_path)
        touched.append(source_page)

        topic_paths = [
            self._upsert_collection_page(
                directory=self.topics_dir,
                page_type="topic",
                title=topic,
                source_id=source.source_id,
                note=compiled.summary,
                related_pages=[source_page],
            )
            for topic in compiled.topics
        ]
        touched.extend(topic_paths)

        entity_paths = [
            self._upsert_collection_page(
                directory=self.entities_dir,
                page_type="entity",
                title=entity,
                source_id=source.source_id,
                note=compiled.summary,
                related_pages=[source_page, *topic_paths],
            )
            for entity in compiled.entities
        ]
        touched.extend(entity_paths)

        if topic_paths or entity_paths:
            self._refresh_source_links(source_page, [*topic_paths, *entity_paths])
        if topic_paths and entity_paths:
            for topic_path in topic_paths:
                self._append_related_links(topic_path, entity_paths)

        self._mark_superseded_sources(source.source_id, compiled.supersedes)
        self._rebuild_index()
        self._append_log(
            "ingest",
            source.source_id,
            [
                f"origin: {source.origin}",
                f"raw: {raw_path.relative_to(self.root).as_posix()}",
                f"pages: {', '.join(path.relative_to(self.root).as_posix() for path in touched)}",
            ],
        )
        return IngestResult(
            source_id=source.source_id,
            raw_path=raw_path,
            source_page=source_page,
            touched_pages=touched,
            log_path=self.log_file,
        )

    async def ask(
        self,
        question: str,
        *,
        provider: "LLMProvider | None",
        model: str,
        save: bool = False,
    ) -> KnowledgeAnswer:
        self.ensure_structure()
        hits = self.search(question, max_pages=self.config.max_pages_per_query)
        pages = [hit.page for hit in hits]
        compiler = KnowledgeCompiler(provider, model)
        answer = await compiler.answer_question(question, pages)

        cited_pages = [page.relative_path for page in pages]
        cited_source_ids = _dedupe(
            [source_id for page in pages for source_id in page.metadata.source_ids]
        )
        if pages and "[page:" not in answer:
            answer = answer.rstrip() + "\n\nSupporting citations:\n" + "\n".join(
                [
                    " ".join(
                        [f"- [page:{page.relative_path}]"]
                        + [f"[source:{source_id}]" for source_id in page.metadata.source_ids]
                    )
                    for page in pages
                ]
            )

        saved_path: Path | None = None
        should_save = save or self.config.auto_file_answers
        if should_save and pages:
            saved_path = self._write_synthesis_page(question, answer, pages)
            for page in pages:
                self._append_related_links(self.root / page.relative_path, [saved_path])
            cited_pages.append(saved_path.relative_to(self.root).as_posix())

        self._append_log(
            "query",
            shorten(question, width=60, placeholder="..."),
            [
                f"pages: {', '.join(cited_pages) or 'none'}",
                f"saved: {saved_path.relative_to(self.root).as_posix() if saved_path else 'no'}",
            ],
        )
        self._rebuild_index()
        return KnowledgeAnswer(
            answer=answer,
            cited_pages=cited_pages,
            cited_source_ids=cited_source_ids,
            selected_pages=[page.path for page in pages],
            saved_path=saved_path,
        )

    def lint(self) -> list[LintFinding]:
        self.ensure_structure()
        findings: list[LintFinding] = []
        pages = self._load_all_pages()
        page_map = {page.relative_path: page for page in pages}
        inbound: dict[str, int] = {path: 0 for path in page_map}

        for page in pages:
            for target in page.metadata.links_out:
                if target in inbound:
                    inbound[target] += 1
                if target in page_map and page.relative_path not in page_map[target].metadata.links_out:
                    findings.append(
                        LintFinding(
                            code="missing_backlink",
                            message=f"{page.relative_path} links to {target} without a reciprocal backlink",
                            page=page.relative_path,
                            related=[target],
                        )
                    )

            if self._section_has_content(page.body, "Conflicts"):
                findings.append(
                    LintFinding(
                        code="explicit_conflict",
                        message=f"{page.relative_path} contains explicit conflict markers",
                        page=page.relative_path,
                    )
                )

        for path, count in inbound.items():
            if count == 0:
                findings.append(
                    LintFinding(
                        code="orphan_page",
                        message=f"{path} has no inbound wiki links",
                        page=path,
                    )
                )

        for page in pages:
            supersedes = self._extract_section_bullets(page.body, "Supersedes")
            for source_id in supersedes:
                target = self.sources_dir / f"{source_id}.md"
                if not target.exists():
                    findings.append(
                        LintFinding(
                            code="superseded_source_missing",
                            message=f"{page.relative_path} supersedes missing source page {source_id}",
                            page=page.relative_path,
                            related=[f"wiki/sources/{source_id}.md"],
                        )
                    )
                    continue
                target_page = load_page(target, root=self.root)
                if f"Superseded by {page.metadata.source_ids[0]}" not in target_page.body:
                    findings.append(
                        LintFinding(
                            code="superseded_source_unmarked",
                            message=f"{target_page.relative_path} is superseded by {page.relative_path} but not marked",
                            page=target_page.relative_path,
                            related=[page.relative_path],
                        )
                    )

        self._append_log("lint", f"{len(findings)} finding(s)", [])
        return findings

    def import_memory(self) -> Path:
        self.ensure_structure()
        memory_file = self.workspace / "memory" / "MEMORY.md"
        if not memory_file.exists():
            raise FileNotFoundError(f"Memory file not found: {memory_file}")

        raw = memory_file.read_text(encoding="utf-8")
        section = self._extract_markdown_section(raw, "Project Context") or raw
        source_page = self._upsert_collection_page(
            directory=self.topics_dir,
            page_type="topic",
            title="Project Context",
            source_id="memory-import",
            note=_summarize_text(section),
            related_pages=[],
            overview=section.strip(),
        )
        self._append_log(
            "import",
            "memory/MEMORY.md",
            [f"page: {source_page.relative_to(self.root).as_posix()}"],
        )
        self._rebuild_index()
        return source_page

    def search(self, query: str, *, max_pages: int) -> list[SearchHit]:
        self.ensure_structure()
        page_map = {
            page.relative_path: page
            for page in self._load_all_pages()
        }
        if not page_map:
            return []

        index_candidates = self._score_index_entries(query)
        candidates = [
            page_map[path]
            for path in index_candidates
            if path in page_map
        ]
        if not candidates:
            candidates = list(page_map.values())

        tokens = _tokenize(query)
        hits: list[SearchHit] = []
        for page in candidates:
            haystack = " ".join(
                [
                    page.metadata.title,
                    " ".join(page.metadata.aliases),
                    " ".join(page.metadata.source_ids),
                    page.body,
                ]
            ).lower()
            score = sum(haystack.count(token) * 2 for token in tokens)
            score += sum(page.relative_path.lower().count(token) * 3 for token in tokens)
            if score <= 0:
                continue
            hits.append(
                SearchHit(
                    page=page,
                    score=score,
                    excerpt=_summarize_text(page.body, max_chars=240),
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.page.metadata.title.lower()))
        return hits[:max_pages]

    async def _load_source(self, path_or_url: str) -> SourceMaterial:
        if _looks_like_url(path_or_url):
            return await self._load_url_source(path_or_url)
        return self._load_local_source(path_or_url)

    def _load_local_source(self, path_or_url: str) -> SourceMaterial:
        path = Path(path_or_url).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Source file not found: {path}")
        content = path.read_text(encoding="utf-8")
        title = _extract_title(content) or path.stem.replace("-", " ").replace("_", " ").title()
        return SourceMaterial(
            source_id=_make_source_id(title),
            title=title,
            origin=str(path),
            content=content,
            fetched_via="file",
            raw_extension=path.suffix or ".txt",
        )

    async def _load_url_source(self, url: str) -> SourceMaterial:
        ok, message = validate_url_target(url)
        if not ok:
            raise ValueError(f"Unsafe URL: {message}")

        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url, headers={"User-Agent": _USER_AGENT})
            response.raise_for_status()
        ok, message = validate_resolved_url(str(response.url))
        if not ok:
            raise ValueError(message)

        doc = Document(response.text)
        title = doc.title() or urlparse(url).netloc
        content = f"# {title}\n\n{_normalize_text(_strip_html(doc.summary()))}"
        return SourceMaterial(
            source_id=_make_source_id(title),
            title=title,
            origin=str(response.url),
            content=content,
            fetched_via="url",
        )

    def _write_raw_source(self, source: SourceMaterial) -> Path:
        raw_path = self.raw_dir / f"{source.source_id}{source.raw_extension}"
        if raw_path.exists():
            return raw_path
        header = [
            f"# {source.title}",
            "",
            f"- source_id: {source.source_id}",
            f"- origin: {source.origin}",
            f"- fetched_via: {source.fetched_via}",
            f"- captured_at: {_utc_now()}",
            "",
        ]
        raw_path.write_text("\n".join(header) + source.content.strip() + "\n", encoding="utf-8")
        return raw_path

    def _write_source_page(
        self,
        source: SourceMaterial,
        compiled: CompiledSource,
        raw_path: Path,
    ) -> Path:
        path = self.sources_dir / f"{source.source_id}.md"
        links_out = [
            *(f"wiki/topics/{_slugify(topic)}.md" for topic in compiled.topics),
            *(f"wiki/entities/{_slugify(entity)}.md" for entity in compiled.entities),
        ]
        metadata = PageMetadata(
            type="source",
            title=source.title,
            aliases=[],
            source_ids=[source.source_id],
            updated_at=_utc_now(),
            links_out=_dedupe(links_out),
        )
        raw_link = _relative_link(path, raw_path)
        body = "\n\n".join(
            [
                f"# {source.title}",
                "## Summary\n" + compiled.summary,
                "## Key Claims\n" + _bullet_block(compiled.claims or [compiled.summary]),
                "## Topics\n" + _bullet_block(
                    [f"[{topic}]({_relative_link(path, self.topics_dir / f'{_slugify(topic)}.md')})" for topic in compiled.topics]
                    or ["(none)"]
                ),
                "## Entities\n" + _bullet_block(
                    [f"[{entity}]({_relative_link(path, self.entities_dir / f'{_slugify(entity)}.md')})" for entity in compiled.entities]
                    or ["(none)"]
                ),
                "## Conflicts\n" + _bullet_block(compiled.contradictions or ["(none)"]),
                "## Supersedes\n" + _bullet_block(compiled.supersedes or ["(none)"]),
                "## Raw Source\n" + f"- [{raw_path.name}]({raw_link})",
            ]
        )
        page = KnowledgePage(path=path.relative_to(self.root), metadata=metadata, body=body)
        self._write_page(page)
        return path

    def _upsert_collection_page(
        self,
        *,
        directory: Path,
        page_type: str,
        title: str,
        source_id: str,
        note: str,
        related_pages: list[Path],
        overview: str | None = None,
    ) -> Path:
        path = directory / f"{_slugify(title)}.md"
        existing: KnowledgePage | None = None
        if path.exists():
            existing = load_page(path, root=self.root)

        related_links = [
            relative
            for relative in (
                path_obj.relative_to(self.root).as_posix()
                for path_obj in related_pages
            )
        ]
        metadata = PageMetadata(
            type=page_type,
            title=title,
            aliases=existing.metadata.aliases if existing else [],
            source_ids=_dedupe((existing.metadata.source_ids if existing else []) + [source_id]),
            updated_at=_utc_now(),
            links_out=_dedupe((existing.metadata.links_out if existing else []) + related_links),
        )

        overview_text = overview or self._extract_markdown_section(existing.body if existing else "", "Overview") or (
            f"This {page_type} page aggregates updates about {title}."
        )
        related_source_bullets = _dedupe(
            self._extract_section_bullets(existing.body if existing else "", "Related Sources")
            + [source_id]
        )
        update_entry = f"{_utc_now()} — {source_id}: {shorten(note, width=180, placeholder='...')}"
        update_bullets = _dedupe(
            self._extract_section_bullets(existing.body if existing else "", "Updates")
            + [update_entry]
        )
        related_page_bullets = _dedupe(
            self._extract_section_bullets(existing.body if existing else "", "Related Pages")
            + related_links
        )

        body = "\n\n".join(
            [
                f"# {title}",
                "## Overview\n" + overview_text.strip(),
                "## Related Sources\n" + _bullet_block(related_source_bullets),
                "## Updates\n" + _bullet_block(update_bullets),
                "## Related Pages\n" + _bullet_block(related_page_bullets or ["(none)"]),
            ]
        )
        page = KnowledgePage(path=path.relative_to(self.root), metadata=metadata, body=body)
        self._write_page(page)
        return path

    def _refresh_source_links(self, source_page: Path, links: list[Path]) -> None:
        page = load_page(source_page, root=self.root)
        page.metadata.links_out = _dedupe(
            page.metadata.links_out + [link.relative_to(self.root).as_posix() for link in links]
        )
        self._write_page(page)

    def _append_related_links(self, page_path: Path, related_paths: list[Path]) -> None:
        if not page_path.exists() or not related_paths:
            return
        page = load_page(page_path, root=self.root)
        related = [path.relative_to(self.root).as_posix() for path in related_paths]
        page.metadata.links_out = _dedupe(page.metadata.links_out + related)
        related_page_bullets = _dedupe(
            self._extract_section_bullets(page.body, "Related Pages") + related
        )
        page.body = self._replace_section(
            page.body,
            "Related Pages",
            _bullet_block(related_page_bullets or ["(none)"]),
        )
        page.metadata.updated_at = _utc_now()
        self._write_page(page)

    def _mark_superseded_sources(self, source_id: str, supersedes: list[str]) -> None:
        if not supersedes:
            return
        source_page = self.sources_dir / f"{source_id}.md"
        for old_source_id in supersedes:
            old_path = self.sources_dir / f"{old_source_id}.md"
            if not old_path.exists():
                continue
            page = load_page(old_path, root=self.root)
            status_entries = self._extract_section_bullets(page.body, "Status")
            marker = f"Superseded by {source_id}"
            if marker in status_entries:
                continue
            updated = self._replace_section(
                page.body,
                "Status",
                _bullet_block(status_entries + [marker]),
            )
            if f"wiki/sources/{source_id}.md" not in page.metadata.links_out:
                page.metadata.links_out.append(f"wiki/sources/{source_id}.md")
            page.metadata.updated_at = _utc_now()
            page.body = updated
            self._write_page(page)

    def _write_synthesis_page(self, question: str, answer: str, pages: list[KnowledgePage]) -> Path:
        title = shorten(question.strip().rstrip("?"), width=60, placeholder="...")
        slug = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{_slugify(title)}"
        path = self.syntheses_dir / f"{slug}.md"
        metadata = PageMetadata(
            type="synthesis",
            title=title,
            aliases=[],
            source_ids=_dedupe([source_id for page in pages for source_id in page.metadata.source_ids]),
            updated_at=_utc_now(),
            links_out=_dedupe([page.relative_path for page in pages]),
        )
        cited = "\n".join(
            [
                " ".join(
                    [f"- [page:{page.relative_path}]"]
                    + [f"[source:{source_id}]" for source_id in page.metadata.source_ids]
                )
                for page in pages
            ]
        )
        body = "\n\n".join(
            [
                f"# {title}",
                "## Question\n" + question.strip(),
                "## Answer\n" + answer.strip(),
                "## Supporting Pages\n" + (cited or "- (none)"),
            ]
        )
        page = KnowledgePage(path=path.relative_to(self.root), metadata=metadata, body=body)
        self._write_page(page)
        return path

    def _rebuild_index(self) -> None:
        pages = self._load_all_pages()
        groups: dict[str, list[KnowledgePage]] = {
            "source": [],
            "topic": [],
            "entity": [],
            "synthesis": [],
        }
        for page in pages:
            groups[page.metadata.type].append(page)

        sections = ["# Knowledge Index", ""]
        for page_type, heading in (
            ("source", "Sources"),
            ("topic", "Topics"),
            ("entity", "Entities"),
            ("synthesis", "Syntheses"),
        ):
            sections.append(f"## {heading}")
            entries = sorted(groups[page_type], key=lambda page: page.metadata.title.lower())
            if not entries:
                sections.append("- (none)")
                sections.append("")
                continue
            for page in entries:
                summary = shorten(_summarize_text(page.body, max_chars=120), width=140, placeholder="...")
                sections.append(f"- [{page.metadata.title}]({page.relative_path}) - {summary}")
            sections.append("")
        self.index_file.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")

    def _append_log(self, action: str, subject: str, details: list[str]) -> None:
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
        entry_lines = [f"## [{stamp}] {action} | {subject}"]
        entry_lines.extend([f"- {detail}" for detail in details if detail])
        entry = "\n".join(entry_lines).rstrip() + "\n\n"
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(entry)

    def _score_index_entries(self, query: str) -> list[str]:
        if not self.index_file.exists():
            return []
        tokens = _tokenize(query)
        scored: list[tuple[int, str]] = []
        for line in self.index_file.read_text(encoding="utf-8").splitlines():
            match = _ENTRY_RE.match(line.strip())
            if not match:
                continue
            title = match.group("title").lower()
            path = match.group("path")
            summary = match.group("summary").lower()
            score = 0
            for token in tokens:
                score += title.count(token) * 4
                score += summary.count(token) * 2
                score += path.lower().count(token) * 3
            if score > 0:
                scored.append((score, path))
        scored.sort(key=lambda item: (-item[0], item[1]))
        limit = max(self.config.max_pages_per_query * 2, self.config.max_pages_per_query)
        return [path for _, path in scored[:limit]]

    def _load_all_pages(self) -> list[KnowledgePage]:
        pages: list[KnowledgePage] = []
        for directory in (self.sources_dir, self.topics_dir, self.entities_dir, self.syntheses_dir):
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.md")):
                pages.append(load_page(path, root=self.root))
        return pages

    def _write_page(self, page: KnowledgePage) -> None:
        full_path = self.root / page.path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(dump_page(page), encoding="utf-8")

    def _ensure_file(self, destination: Path, template) -> None:
        if destination.exists():
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")

    def _extract_markdown_section(self, body: str, heading: str) -> str:
        for match in _SECTION_RE.finditer(body or ""):
            if match.group("title").strip() == heading:
                return match.group("body").strip()
        return ""

    def _extract_section_bullets(self, body: str, heading: str) -> list[str]:
        section = self._extract_markdown_section(body, heading)
        bullets = []
        for line in section.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                value = stripped[2:].strip()
                if value != "(none)":
                    bullets.append(value)
        return bullets

    def _replace_section(self, body: str, heading: str, content: str) -> str:
        replacement = f"## {heading}\n{content.strip()}"
        if self._extract_markdown_section(body, heading):
            return re.sub(
                rf"(^## {re.escape(heading)}\n.*?)(?=^## |\Z)",
                replacement + "\n\n",
                body,
                flags=re.MULTILINE | re.DOTALL,
            ).strip()
        return body.rstrip() + f"\n\n{replacement}\n"

    def _section_has_content(self, body: str, heading: str) -> bool:
        section = self._extract_markdown_section(body, heading)
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        return any(line not in {"- (none)", "(none)"} for line in lines)


def _make_source_id(title: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{_slugify(title)}"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "entry"


def _tokenize(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]{2,}", text.lower())
        if token not in _STOPWORDS
    ]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _normalize_text(value: Any) -> str:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    return ""


def _clean_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe([_normalize_text(item) for item in value if _normalize_text(item)])


def _summarize_text(text: str, *, max_chars: int = 320) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return shorten(cleaned, width=max_chars, placeholder="...") if cleaned else "(empty)"


def _guess_topics(text: str) -> list[str]:
    tokens = _tokenize(text)
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [token.replace("-", " ").title() for token, _ in ranked[:5]]


def _guess_entities(text: str) -> list[str]:
    matches = re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", text)
    return _dedupe(matches[:8])


def _extract_claims(text: str) -> list[str]:
    claims: list[str] = []
    for chunk in re.split(r"\n{2,}", text):
        normalized = _normalize_text(chunk)
        if normalized:
            claims.append(shorten(normalized, width=180, placeholder="..."))
        if len(claims) >= 5:
            break
    return claims


def _extract_title(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped:
            return shorten(stripped, width=80, placeholder="...")
    return None


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _bullet_block(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item)


def _relative_link(from_path: Path, target_path: Path) -> str:
    return os.path.relpath(target_path, start=from_path.parent).replace(os.sep, "/")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _looks_like_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")
