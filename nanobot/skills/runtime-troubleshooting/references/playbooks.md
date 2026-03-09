# Runtime Troubleshooting Playbooks

## Missing Reply

1. Run `python -m nanobot.debug.runtime_diagnostics --format json`.
2. Identify the latest channel session in `sessions.latest`.
3. Open that session file and inspect the target turn:
   - user message
   - assistant tool calls
   - tool results
   - final assistant reply
4. Separate these cases:
   - no tool call: likely prompt / model / routing issue
   - tool call with error: tool or environment issue
   - tool succeeded but no final reply: agent flow issue

## Cron Failure

1. Read `cron.failing_jobs`.
2. For each failing job, open `sessions/cron_<jobid>.jsonl`.
3. Determine whether the failure happened:
   - before agent execution: `jobs.json` has error but session is missing or empty
   - during agent execution: session shows tool or assistant error
   - after execution: session succeeded but downstream delivery still needs confirmation

## Heartbeat Misfire

1. Run diagnostics and inspect recent `heartbeat` activity.
2. Open `heartbeat.jsonl`.
3. Compare the recorded heartbeat prompt with `HEARTBEAT.md`.
4. Verify:
   - time window
   - skip conditions
   - marker / output file existence
   - missing tool capability noted in the session

## Memory Issue

1. Inspect `memory/MEMORY.md` and `memory/HISTORY.md`.
2. Find the most recent history entry that mentions the disputed fact.
3. Open the corresponding session from the same time window.
4. Decide whether the bad fact came from:
   - an explicit user instruction
   - an over-aggressive summary
   - a temporary note that should not have been promoted to memory

## Multiple Gateway or Lock Issue

1. Inspect `gateway.lock` from diagnostics.
2. If the lock PID is not running, treat it as stale evidence, not a live instance.
3. If the lock PID is running, compare it with the process table before any restart.

