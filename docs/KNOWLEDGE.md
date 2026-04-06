# Knowledge Wiki in nanobot

nanobot now separates long-term agent memory from a persistent knowledge wiki.

## What it is

- `memory/` remains the place for agent continuity: `SOUL.md`, `USER.md`, `memory/MEMORY.md`, and `history.jsonl`.
- `knowledge/` is a separate file-first wiki for curated sources and accumulated analysis.

This keeps conversational memory compact while letting the knowledge base grow without
inflating the normal agent prompt.

## Layout

```text
workspace/
└── knowledge/
    ├── raw/                 # Immutable ingested sources
    ├── wiki/
    │   ├── sources/         # One page per source
    │   ├── topics/          # Cross-source topic pages
    │   ├── entities/        # Cross-source entity pages
    │   └── syntheses/       # Saved answers from kb ask --save
    ├── index.md             # Content-oriented catalog
    ├── log.md               # Append-only ingest/query/lint log
    └── SCHEMA.md            # Maintenance conventions
```

Every wiki page uses YAML frontmatter with:

- `type`
- `title`
- `aliases`
- `source_ids`
- `updated_at`
- `links_out`

## Commands

| Command | What it does |
|---------|--------------|
| `nanobot kb status` | Show counts and the active knowledge root |
| `nanobot kb ingest <path-or-url>` | Capture a local file or URL, write raw source, build wiki pages, refresh index/log |
| `nanobot kb ask "<question>" [--save]` | Search the wiki, answer from the selected pages, optionally file a synthesis page |
| `nanobot kb lint` | Report orphan pages, missing backlinks, superseded-source markers, and explicit conflict sections |
| `nanobot kb import-memory` | Create/update `wiki/topics/project-context.md` from `memory/MEMORY.md` |

## Design Notes

- Query-time retrieval reads `knowledge/index.md` first, then the top matching wiki pages.
- The full `knowledge/` tree is not injected into the normal `ContextBuilder` prompt.
- Raw captured sources are immutable after ingest.
- Saved syntheses become first-class wiki pages with citations back to source and topic/entity pages.
