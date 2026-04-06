---
name: runtime-troubleshooting
description: Diagnose nanobot runtime issues using logs, gateway.lock, cron/jobs.json, sessions/*.jsonl, and memory history. Use when replies are missing, cron jobs fail, heartbeat behaves unexpectedly, code errors (AttributeError, ImportError, TypeError) occur, or memory/log evidence needs to be traced.
---

# Runtime Troubleshooting

Use this skill when the user reports nanobot misbehavior, errors, or missing responses.

## Log file

Runtime logs are at `~/.nanobot/logs/nanobot.log` (5 MB rotation, 3 backups).
Always check this file first — it contains full tracebacks with local variables.

## What to inspect

| Symptom | First check |
|---------|-------------|
| Missing / wrong reply | `~/.nanobot/logs/nanobot.log` → channel session JSONL |
| Cron did not run / failed | `cron/jobs.json` → `cron_<jobid>.jsonl` |
| Heartbeat NOOP / over-triggering | `heartbeat.jsonl` + `HEARTBEAT.md` |
| Memory contamination | `memory/MEMORY.md` → `memory/HISTORY.md` → originating session |
| Multiple gateway suspicion | `gateway.lock` + running processes |
| Code-level crash (AttributeError, ImportError, TypeError, etc.) | `~/.nanobot/logs/nanobot.log` → grep repo for the missing attribute/import |

## Default workflow

1. Read the tail of the log file:
   ```bash
   tail -200 ~/.nanobot/logs/nanobot.log
   ```
2. If there's a traceback, identify the exception type and location.
3. For **runtime state issues** (cron, session, heartbeat):
   ```bash
   python -m nanobot.debug.runtime_diagnostics --format json
   ```
4. For **code-level bugs** (AttributeError, ImportError, TypeError, NameError):
   - Extract the class/attribute name from the traceback
   - Grep the repo for all references: `rg "attribute_name" nanobot/`
   - Grep for where it should be defined: `rg "self\.attribute_name\s*=" nanobot/`
   - Compare references vs definitions to find the gap
   - Fix: add the missing init / import / definition

## Guardrails

- Do not claim delivery failure unless the session or cron state actually shows it.
- Do not call something a model bug before checking tool output and scheduler state.
- If evidence is incomplete, report the top plausible causes and state what file is still missing.
- Ground every conclusion in file evidence. Quote the relevant timestamp, session key, job id, `lastError`, or tool result.
