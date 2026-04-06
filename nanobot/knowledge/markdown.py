"""Markdown helpers for the persistent knowledge wiki."""

from __future__ import annotations

from pathlib import Path

from nanobot.knowledge.models import KnowledgePage, PageMetadata


def dump_frontmatter(metadata: PageMetadata) -> str:
    lines = [
        "---",
        f"type: {metadata.type}",
        f"title: {metadata.title}",
        "aliases:",
        *[f"  - {value}" for value in metadata.aliases],
        "source_ids:",
        *[f"  - {value}" for value in metadata.source_ids],
        f"updated_at: {metadata.updated_at}",
        "links_out:",
        *[f"  - {value}" for value in metadata.links_out],
        "---",
    ]
    return "\n".join(lines)


def dump_page(page: KnowledgePage) -> str:
    body = page.body.strip()
    return f"{dump_frontmatter(page.metadata)}\n\n{body}\n"


def load_page(path: Path, *, root: Path | None = None) -> KnowledgePage:
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ValueError(f"Missing frontmatter in {path}")

    try:
        _, frontmatter, body = content.split("---\n", 2)
    except ValueError as exc:
        raise ValueError(f"Invalid frontmatter in {path}") from exc

    data = _parse_frontmatter(frontmatter.strip().splitlines())
    metadata = PageMetadata(
        type=data.get("type", "topic"),
        title=data.get("title", path.stem.replace("-", " ").title()),
        aliases=data.get("aliases", []),
        source_ids=data.get("source_ids", []),
        updated_at=data.get("updated_at", ""),
        links_out=data.get("links_out", []),
    )
    stored_path = path.relative_to(root) if root is not None and path.is_absolute() else path
    return KnowledgePage(path=stored_path, metadata=metadata, body=body.strip())


def _parse_frontmatter(lines: list[str]) -> dict[str, object]:
    data: dict[str, object] = {}
    current_list: str | None = None

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("  - ") and current_list:
            data.setdefault(current_list, [])
            cast = data[current_list]
            if isinstance(cast, list):
                cast.append(line[4:].strip())
            continue
        if ":" not in line:
            current_list = None
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            data[key] = value
            current_list = None
        else:
            data[key] = []
            current_list = key
    return data
