---
name: runtime-troubleshooting
description: Diagnose nanobot runtime issues using gateway.lock, cron/jobs.json, sessions/*.jsonl, and memory history. Use when replies are missing, cron jobs fail, heartbeat behaves unexpectedly, or memory/log evidence needs to be traced.
---

# Runtime Troubleshooting

Use this skill when the user asks why nanobot misbehaved and you need evidence from runtime records.

## What to inspect

- `gateway.lock` for stale single-instance locks.
- `cron/jobs.json` for scheduled task state, `lastStatus`, and `lastError`.
- `sessions/*.jsonl` for raw user / assistant / tool turns.
- `memory/HISTORY.md` for summarized past events.

## Default workflow

1. Run the diagnostics module first:
   ```bash
   python -m nanobot.debug.runtime_diagnostics --format json
   ```
2. If the user points to one session or chat, rerun with:
   ```bash
   python -m nanobot.debug.runtime_diagnostics --format json --session-key "telegram:123456"
   ```
3. Use the report to choose the exact file to open next. Prefer the reported `cron_<jobid>.jsonl`, `heartbeat.jsonl`, or channel session file before scanning anything broad.
4. Ground every conclusion in file evidence. Quote the relevant timestamp, session key, job id, `lastError`, or tool result.

## Routing rules

- Missing or wrong reply: inspect the channel session JSONL first.
- Cron did not run or failed: inspect `cron/jobs.json` first, then `cron_<jobid>.jsonl`.
- Heartbeat NOOP / over-triggering: inspect `heartbeat.jsonl` and `HEARTBEAT.md`.
- Memory contamination: inspect `memory/MEMORY.md`, `memory/HISTORY.md`, then the originating session.
- Multiple gateway suspicion: inspect `gateway.lock` and compare with running processes.

## Guardrails

- Do not claim delivery failure unless the session or cron state actually shows it.
- Do not call something a model bug before checking tool output and scheduler state.
- If evidence is incomplete, report the top plausible causes and state what file is still missing.

For symptom-specific playbooks, read `references/playbooks.md`.

