"""Bookmark tool for saving, searching, and exporting collected links/content."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


from nanobot.agent.tools.base import Tool


class BookmarkTool(Tool):
    """Save, search, tag, and export bookmarks."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace
        self._path = workspace / "BOOKMARKS.jsonl"

    @property
    def name(self) -> str:
        return "bookmark"

    @property
    def description(self) -> str:
        return (
            "Manage bookmarks: save URLs/content with tags, list, search, "
            "remove, or export to Obsidian/NotebookLM format."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["save", "list", "search", "tag", "remove", "export"],
                    "description": "Action to perform",
                },
                "url": {
                    "type": "string",
                    "description": "URL to bookmark (for save)",
                },
                "title": {
                    "type": "string",
                    "description": "Title of the bookmark",
                },
                "summary": {
                    "type": "string",
                    "description": "Summary or notes about the content",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorization (e.g. ['tech/ai', 'reading'])",
                },
                "content_snippet": {
                    "type": "string",
                    "description": "Key content excerpt (first ~500 chars)",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (for search action)",
                },
                "bookmark_id": {
                    "type": "string",
                    "description": "Bookmark ID (for tag/remove actions)",
                },
                "format": {
                    "type": "string",
                    "enum": ["obsidian", "notebooklm", "json"],
                    "description": "Export format (for export action)",
                },
                "export_path": {
                    "type": "string",
                    "description": "Target directory for export (Obsidian vault path)",
                },
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "")
        try:
            if action == "save":
                return self._save(kwargs)
            elif action == "list":
                return self._list()
            elif action == "search":
                return self._search(kwargs.get("query", ""))
            elif action == "tag":
                return self._tag(kwargs)
            elif action == "remove":
                return self._remove(kwargs.get("bookmark_id", ""))
            elif action == "export":
                return self._export(kwargs)
            else:
                return f"Unknown action: {action}"
        except Exception as e:
            return f"Error: {e}"

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------

    def _load_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        entries = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def _append(self, entry: dict) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _rewrite(self, entries: list[dict]) -> None:
        with self._path.open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _save(self, kwargs: dict) -> str:
        url = kwargs.get("url", "")
        title = kwargs.get("title", url or "Untitled")
        tags = kwargs.get("tags", [])

        # Dedup: if same URL exists, update it
        entries = self._load_all()
        if url:
            for e in entries:
                if e.get("url") == url:
                    e["title"] = title
                    e["summary"] = kwargs.get("summary", e.get("summary", ""))
                    e["tags"] = tags or e.get("tags", [])
                    e["content_snippet"] = kwargs.get("content_snippet", e.get("content_snippet", ""))
                    e["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    self._rewrite(entries)
                    return f"Updated bookmark [{e['id']}] {title}"

        entry = {
            "id": uuid.uuid4().hex[:6],
            "url": url,
            "title": title,
            "summary": kwargs.get("summary", ""),
            "tags": tags,
            "content_snippet": kwargs.get("content_snippet", ""),
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._append(entry)
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        return f"Saved bookmark [{entry['id']}] {title}{tag_str}"

    def _list(self) -> str:
        entries = self._load_all()
        if not entries:
            return "No bookmarks saved."
        # Show most recent first, max 20
        recent = entries[-20:][::-1]
        lines = [f"Bookmarks ({len(entries)} total, showing latest {len(recent)}):\n"]
        for e in recent:
            tags = f" [{', '.join(e.get('tags', []))}]" if e.get("tags") else ""
            date = (e.get("saved_at") or "")[:10]
            url = f" — {e['url']}" if e.get("url") else ""
            lines.append(f"  [{e['id']}] {e.get('title', 'Untitled')}{tags} ({date}){url}")
        return "\n".join(lines)

    def _search(self, query: str) -> str:
        if not query:
            return "Please provide a search query."
        entries = self._load_all()
        q_lower = query.lower()
        matches = []
        for e in entries:
            searchable = " ".join([
                e.get("title", ""),
                e.get("summary", ""),
                " ".join(e.get("tags", [])),
                e.get("url", ""),
            ]).lower()
            if q_lower in searchable:
                matches.append(e)
            # Also match tag prefix (e.g. "tech/" matches "tech/ai")
            elif any(t.lower().startswith(q_lower) for t in e.get("tags", [])):
                matches.append(e)
        if not matches:
            return f"No bookmarks matching '{query}'."
        lines = [f"Found {len(matches)} bookmark(s) matching '{query}':\n"]
        for e in matches[:20]:
            tags = f" [{', '.join(e.get('tags', []))}]" if e.get("tags") else ""
            lines.append(f"  [{e['id']}] {e.get('title', 'Untitled')}{tags}")
            if e.get("summary"):
                lines.append(f"    {e['summary'][:100]}")
        return "\n".join(lines)

    def _tag(self, kwargs: dict) -> str:
        bid = kwargs.get("bookmark_id", "")
        new_tags = kwargs.get("tags", [])
        if not bid:
            return "Please provide bookmark_id."
        entries = self._load_all()
        for e in entries:
            if e["id"] == bid:
                e["tags"] = new_tags
                e["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._rewrite(entries)
                return f"Updated tags for [{bid}]: {', '.join(new_tags)}"
        return f"Bookmark [{bid}] not found."

    def _remove(self, bid: str) -> str:
        if not bid:
            return "Please provide bookmark_id."
        entries = self._load_all()
        before = len(entries)
        entries = [e for e in entries if e["id"] != bid]
        if len(entries) == before:
            return f"Bookmark [{bid}] not found."
        self._rewrite(entries)
        return f"Removed bookmark [{bid}]."

    def _export(self, kwargs: dict) -> str:
        fmt = kwargs.get("format", "json")
        entries = self._load_all()
        if not entries:
            return "No bookmarks to export."

        if fmt == "obsidian":
            return self._export_obsidian(entries, kwargs.get("export_path"))
        elif fmt == "notebooklm":
            return self._export_notebooklm(entries)
        elif fmt == "json":
            out = self._workspace / "exports"
            out.mkdir(exist_ok=True)
            path = out / f"bookmarks-{datetime.now().strftime('%Y-%m-%d')}.json"
            path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
            return f"Exported {len(entries)} bookmarks to {path}"
        return f"Unknown export format: {fmt}"

    def _export_obsidian(self, entries: list[dict], export_path: str | None) -> str:
        vault = Path(export_path).expanduser() if export_path else Path.home() / "Obsidian" / "Bookmarks"
        vault.mkdir(parents=True, exist_ok=True)
        count = 0
        for e in entries:
            title = (e.get("title") or "Untitled").replace("/", "-").replace("\\", "-")
            filename = f"{title[:80]}.md"
            filepath = vault / filename

            tags_yaml = ", ".join(f'"{t}"' for t in e.get("tags", []))
            frontmatter = "\n".join([
                "---",
                f"title: \"{title}\"",
                f"url: \"{e.get('url', '')}\"",
                f"tags: [{tags_yaml}]",
                f"date: {(e.get('saved_at') or '')[:10]}",
                "source: nanobot-bookmark",
                "---",
            ])
            body_parts = []
            if e.get("summary"):
                body_parts.append(f"## Summary\n\n{e['summary']}")
            if e.get("content_snippet"):
                body_parts.append(f"## Content\n\n{e['content_snippet']}")
            if e.get("url"):
                body_parts.append(f"## Source\n\n{e['url']}")

            content = frontmatter + "\n\n" + "\n\n".join(body_parts) + "\n"
            filepath.write_text(content, encoding="utf-8")
            count += 1

        return f"Exported {count} bookmarks to Obsidian vault: {vault}"

    def _export_notebooklm(self, entries: list[dict]) -> str:
        out = self._workspace / "exports"
        out.mkdir(exist_ok=True)
        path = out / f"bookmarks-{datetime.now().strftime('%Y-%m-%d')}.md"

        # Group by top-level tag
        groups: dict[str, list[dict]] = {}
        for e in entries:
            top_tag = e.get("tags", ["uncategorized"])[0].split("/")[0] if e.get("tags") else "uncategorized"
            groups.setdefault(top_tag, []).append(e)

        lines = [f"# Bookmarks Collection ({len(entries)} items)\n"]
        for group, items in sorted(groups.items()):
            lines.append(f"\n## {group.title()}\n")
            for e in items:
                lines.append(f"### {e.get('title', 'Untitled')}")
                if e.get("url"):
                    lines.append(f"Source: {e['url']}")
                if e.get("summary"):
                    lines.append(f"\n{e['summary']}")
                if e.get("content_snippet"):
                    lines.append(f"\n> {e['content_snippet'][:300]}")
                lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        return f"Exported {len(entries)} bookmarks for NotebookLM: {path}"
