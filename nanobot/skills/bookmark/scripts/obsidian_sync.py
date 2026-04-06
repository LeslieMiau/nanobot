#!/usr/bin/env python3
"""Sync nanobot bookmarks to an Obsidian vault as individual Markdown notes.

Usage:
    python obsidian_sync.py --workspace ~/.nanobot/workspace --vault ~/Obsidian/Bookmarks
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def sync(workspace: Path, vault: Path) -> int:
    """Export bookmarks as Obsidian-compatible Markdown notes. Returns count."""
    bookmarks_file = workspace / "BOOKMARKS.jsonl"
    if not bookmarks_file.exists():
        print("No bookmarks file found.")
        return 0

    vault.mkdir(parents=True, exist_ok=True)

    # Track last sync time
    sync_marker = workspace / "observability" / ".obsidian_sync_ts"
    last_sync = None
    if sync_marker.exists():
        try:
            last_sync = datetime.fromisoformat(sync_marker.read_text().strip())
        except (ValueError, OSError):
            pass

    count = 0
    for line in bookmarks_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Incremental: skip entries older than last sync
        if last_sync:
            saved = entry.get("updated_at") or entry.get("saved_at", "")
            if saved:
                try:
                    ts = datetime.fromisoformat(saved.replace("Z", "+00:00")).replace(tzinfo=None)
                    if ts < last_sync:
                        continue
                except ValueError:
                    pass

        title = (entry.get("title") or "Untitled").replace("/", "-").replace("\\", "-")
        filename = f"{title[:80]}.md"
        filepath = vault / filename

        tags_yaml = ", ".join(f'"{t}"' for t in entry.get("tags", []))
        frontmatter = "\n".join([
            "---",
            f'title: "{title}"',
            f'url: "{entry.get("url", "")}"',
            f"tags: [{tags_yaml}]",
            f"date: {(entry.get('saved_at') or '')[:10]}",
            "source: nanobot-bookmark",
            "---",
        ])

        body_parts = []
        if entry.get("summary"):
            body_parts.append(f"## Summary\n\n{entry['summary']}")
        if entry.get("content_snippet"):
            body_parts.append(f"## Content\n\n{entry['content_snippet']}")
        if entry.get("url"):
            body_parts.append(f"## Source\n\n{entry['url']}")

        content = frontmatter + "\n\n" + "\n\n".join(body_parts) + "\n"
        filepath.write_text(content, encoding="utf-8")
        count += 1

    # Update sync marker
    sync_marker.parent.mkdir(parents=True, exist_ok=True)
    sync_marker.write_text(datetime.now().isoformat())

    return count


def main():
    parser = argparse.ArgumentParser(description="Sync nanobot bookmarks to Obsidian vault")
    parser.add_argument("--workspace", required=True, help="Workspace path")
    parser.add_argument("--vault", default="~/Obsidian/Bookmarks", help="Obsidian vault path")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser()
    vault = Path(args.vault).expanduser()

    count = sync(workspace, vault)
    print(f"Synced {count} bookmark(s) to {vault}")


if __name__ == "__main__":
    main()
