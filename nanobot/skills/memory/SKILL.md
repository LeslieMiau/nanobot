---
name: memory
description: Two-layer memory system with grep-based recall.
always: true
---

# Memory

## Structure

- `memory/MEMORY.md` — Long-term facts (preferences, project context, relationships). Always loaded into your context.
- `memory/HISTORY.md` — Append-only event log. NOT loaded into context. Search it with grep-style tools or in-memory filters. Each entry starts with [YYYY-MM-DD HH:MM].

## Search Past Events

Choose the search method based on file size:

- Small `memory/HISTORY.md`: use `read_file`, then search in-memory
- Large or long-lived `memory/HISTORY.md`: use the `exec` tool for targeted search

Examples:
- **Linux/macOS:** `grep -i "keyword" memory/HISTORY.md`
- **Windows:** `findstr /i "keyword" memory\HISTORY.md`
- **Cross-platform Python:** `python -c "from pathlib import Path; text = Path('memory/HISTORY.md').read_text(encoding='utf-8'); print('\n'.join([l for l in text.splitlines() if 'keyword' in l.lower()][-20:]))"`

Prefer targeted command-line search for large history files.

## When to Update MEMORY.md

Write important facts immediately using `edit_file` or `write_file`:
- User preferences ("I prefer dark mode")
- Project context ("The API uses OAuth2")
- Relationships ("Alice is the project lead")

## Auto-consolidation

Old conversations are automatically summarized and appended to HISTORY.md when the session grows large. Long-term facts are extracted to MEMORY.md. You don't need to manage this.

## MemOS Semantic Index (when enabled)

When `memory.backend = "memos"` is configured, a local MemOS fact index is maintained at `memory/memos/textual_memory.json`. It holds the same facts as MEMORY.md but supports keyword-based retrieval.

**How it works:**
- Each time MEMORY.md is updated during consolidation, the new facts are automatically synced into the MemOS index.
- At context-build time, the top-k most relevant facts are injected under `## Relevant Memory` based on the current user message — in addition to the full `## Long-term Memory` block.
- Do not edit `memory/memos/textual_memory.json` directly; it is managed automatically.

**Re-index after manual MEMORY.md edits:** If you manually edited MEMORY.md, you can trigger a re-sync by asking: "Re-index my long-term memory into MemOS." Then read MEMORY.md and call `write_file` to overwrite it with the same content, which triggers the upsert hook.
