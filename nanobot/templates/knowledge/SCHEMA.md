# Knowledge Wiki Schema

This directory is a persistent wiki maintained by nanobot.

## Layout

- `raw/` stores immutable ingested sources.
- `wiki/sources/` stores one page per ingested source.
- `wiki/topics/` stores topic pages updated across sources.
- `wiki/entities/` stores entity pages updated across sources.
- `wiki/syntheses/` stores saved answers from `kb ask --save`.
- `index.md` is the catalog of wiki pages.
- `log.md` is the append-only operational log.

## Page Frontmatter

Every wiki page keeps YAML frontmatter with:

- `type`
- `title`
- `aliases`
- `source_ids`
- `updated_at`
- `links_out`

## Rules

- Raw sources are immutable once captured.
- Source, topic, entity, and synthesis pages may be regenerated or updated.
- Questions should search the wiki first instead of loading the whole knowledge tree into the agent prompt.
- Saved syntheses must cite the supporting pages and source ids.
