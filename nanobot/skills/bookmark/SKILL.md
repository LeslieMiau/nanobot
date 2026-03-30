---
name: bookmark
description: Save, organize, and export bookmarks with tag-based categorization. Supports Obsidian vault sync and NotebookLM export.
metadata: {"nanobot":{"emoji":"🔖"}}
---

# Bookmark Manager

Save interesting links, articles, and content with tags. Export to Obsidian or NotebookLM.

## When to use (trigger phrases)

- "收藏这个" / "bookmark this" / "保存这个链接"
- "我的收藏" / "list bookmarks" / "show bookmarks"
- "搜索收藏" / "search bookmarks"
- "同步到 Obsidian" / "export to Obsidian"
- "导出给 NotebookLM" / "export for NotebookLM"

## Saving a bookmark (recommended workflow)

When the user shares a URL or asks to save something:

1. **Fetch the content** first using `web_fetch` to get the title and content
2. **Generate a concise summary** (1-2 sentences)
3. **Suggest tags** based on the content
4. **Save** using the `bookmark` tool:

```
bookmark(action="save", url="https://...", title="...", summary="...", tags=["tech/ai", "reading"], content_snippet="first 500 chars...")
```

## Listing bookmarks

```
bookmark(action="list")
```

Shows the 20 most recent bookmarks with IDs, titles, tags, and dates.

## Searching

```
bookmark(action="search", query="AI agents")
```

Searches across title, summary, tags, and URL. Tag prefix matching supported (e.g., "tech/" matches "tech/ai").

## Managing tags

```
bookmark(action="tag", bookmark_id="abc123", tags=["new/tag", "another"])
```

## Removing

```
bookmark(action="remove", bookmark_id="abc123")
```

## Exporting to Obsidian

```
bookmark(action="export", format="obsidian", export_path="~/Obsidian/MyVault/Bookmarks")
```

Each bookmark becomes a Markdown note with YAML frontmatter (title, url, tags, date) compatible with Obsidian.

Default vault path: `~/Obsidian/Bookmarks/`

## Exporting for NotebookLM

```
bookmark(action="export", format="notebooklm")
```

Generates a single consolidated Markdown document organized by tag categories, saved to `exports/bookmarks-YYYY-MM-DD.md`. Upload this file to NotebookLM as a source.

## Tag conventions

Use hierarchical tags for better organization:
- `tech/ai`, `tech/web`, `tech/tools`
- `reading/article`, `reading/paper`, `reading/book`
- `work/project-x`, `work/meeting`
- `personal/health`, `personal/finance`
