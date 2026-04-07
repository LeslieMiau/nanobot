# `/coding` Postflight + Status Sync Review Handoff

## Scope

This review target covers one focused follow-up on the Telegram `/coding` task system:

1. Add a real completion gate for coding tasks:
   - run repository validation
   - merge the task branch into `main`
   - push `main` to `origin`
   - only then mark the task `completed`
2. Fix the state mismatch where Telegram `/coding list` could show a task as completed while `/coding status` still showed it as running.

This landed in commit `803e3f1 feat(coding-tasks): add postflight completion gate`.

## User-visible behavior change

Before this change:

- a worker could finish or disappear and the task could become `completed` without a system-enforced `test -> merge -> push` gate
- `/coding list` refreshed some active tasks before rendering, but `/coding status` could still render a stale pre-refresh task object

After this change:

- completed coding tasks now go through a postflight runner before terminal completion
- tasks with missing tmux sessions are triaged into postflight when the harness looks complete
- Telegram `/coding status` and CLI `coding-task status` both refresh active tasks through the same missing-session-aware path

## Main implementation

### 1. New postflight runner

Primary file: `nanobot/coding_tasks/postflight.py`

`CodexPostflightRunner` executes three ordered steps:

1. `validation`
2. `merge`
3. `push`

Validation command detection is intentionally conservative:

- prefer `bash init.sh` when present
- otherwise use `corepack pnpm test` / `npm test` only when `package.json` declares a `test` script
- otherwise use `.venv/bin/pytest` or `pytest` for Python repos
- otherwise fail with a structured `postflight_failed` summary

Merge target rules:

- target branch is currently hard-coded to `main`
- remote is currently hard-coded to `origin`
- the main worktree must be on `main`
- the main worktree must be clean, except that `.codex-tasks/` is ignored because it is framework-owned task isolation state

Important implementation detail:

- the first postflight attempt exposed a real bug where `git status --short` treated `.codex-tasks/` as dirty and blocked every merge
- this was fixed by filtering `.codex-tasks` entries out of the cleanliness check instead of relaxing cleanliness globally

### 2. New metadata and failure reason

Primary file: `nanobot/coding_tasks/types.py`

Added:

- `FAILURE_POSTFLIGHT = "postflight_failed"`
- `postflight_stage`
- `postflight_result`
- `postflight_summary`
- `preserve_failure_worktree`

These fields are used to:

- avoid duplicate completion claims
- expose which postflight step failed
- preserve the task worktree on postflight failure for inspection

### 3. Completion flow moved behind postflight

Primary file: `nanobot/coding_tasks/progress.py`

The missing-session triage path now routes likely-finished tasks into `_complete_via_postflight(...)` instead of directly calling `mark_completed(...)`.

This happens in two cases:

- `PLAN.json` is fully complete
- there is strong completion evidence from the worker output

If postflight succeeds:

- task becomes `completed`
- success summary is persisted

If postflight fails:

- task becomes `failed`
- failure summary is persisted as `postflight_failed: ...`
- worktree preservation is enabled for forensics

### 4. Status mismatch fix

Primary files:

- `nanobot/coding_tasks/router.py`
- `nanobot/cli/commands.py`

Telegram `/coding status` now:

- refreshes active tasks before rendering
- reloads the current task from the store after refresh
- uses `launcher.has_session(...)` to detect a missing tmux session and passes `session_missing=True` into `monitor.refresh_task(...)`

CLI `coding-task status` now mirrors the same behavior.

This matters because previously:

- `/coding list` could detect a missing session and update the task
- `/coding status` could still print the old in-memory `running` state

### 5. Cleanup semantics

Primary file: `nanobot/coding_tasks/worker.py`

Successful postflight:

- worktree directory is removed
- task branch is retained

Failed postflight:

- worktree is preserved when `preserve_failure_worktree` is set
- branch is also preserved for inspection

This is a deliberate tradeoff:

- successful tasks should leave a clean runtime surface
- failed postflight tasks should remain debuggable

### 6. Reporting/runtime wiring

Primary files:

- `nanobot/coding_tasks/runtime.py`
- `nanobot/coding_tasks/reporting.py`
- `nanobot/coding_tasks/__init__.py`

Changes:

- runtime builder now instantiates and injects `CodexPostflightRunner`
- failure reporting knows about `postflight_failed`
- public exports were updated so tests and runtime assembly can import the new types directly

## Review hotspots

Opus should pay extra attention to these areas:

### A. Duplicate execution and race behavior

Questions to review:

- Can watcher polling trigger postflight more than once under concurrent refreshes?
- Is `postflight_result == "passed"` sufficient as the only duplicate-execution guard?
- Are there races between status refresh, watcher polling, and cleanup callbacks?

### B. Main worktree safety

Questions to review:

- Is ignoring `.codex-tasks/` in the dirty check the right boundary?
- Are there other framework-managed paths that should also be ignored?
- Should merge safety require additional guards such as verifying branch ancestry or remote freshness?

### C. Postflight command inference

Questions to review:

- Is `init.sh` always safe as the highest-priority validation command in this codebase family?
- Are there repositories where `npm test` or `pnpm test` would be valid but still undesirable?
- Should command inference become repo-policy-driven instead of heuristic?

### D. Status/render consistency

Questions to review:

- Are there any remaining paths where `build_task_report(...)` can still render stale active task data?
- Should `/coding list` and `/coding status` share a single helper for active-task refresh instead of each performing similar logic?

### E. Failure observability

Questions to review:

- Is the current failure summary detailed enough for real Telegram triage?
- Should postflight step results be appended to run events instead of only task metadata and terminal summaries?

## Files changed

Core implementation:

- `nanobot/coding_tasks/postflight.py`
- `nanobot/coding_tasks/progress.py`
- `nanobot/coding_tasks/router.py`
- `nanobot/cli/commands.py`
- `nanobot/coding_tasks/worker.py`
- `nanobot/coding_tasks/runtime.py`
- `nanobot/coding_tasks/types.py`
- `nanobot/coding_tasks/reporting.py`
- `nanobot/coding_tasks/__init__.py`

Tests:

- `tests/coding_tasks/test_postflight.py`
- `tests/coding_tasks/test_progress.py`
- `tests/coding_tasks/test_e2e.py`
- `tests/cli/test_commands.py`
- `tests/agent/test_coding_task_routing.py`

## Validation run

Targeted automated validation completed:

- `.venv/bin/pytest tests/coding_tasks/test_postflight.py tests/cli/test_commands.py tests/agent/test_coding_task_routing.py -q`
  - `108 passed`
- `.venv/bin/pytest tests/coding_tasks/ tests/agent/test_coding_task_routing.py tests/cli/test_commands.py -q`
  - `205 passed`

Repository-wide baseline remains unchanged:

- `bash ~/.codex/scripts/global-init.sh`
  - still stops on the pre-existing unrelated import failure in `tests/test_coding_mode.py`
  - error: `ImportError: cannot import name 'CodingConfig' from 'nanobot.config.schema'`

## Real smoke evidence

A disposable repo smoke was run outside mocks to verify the actual completion path:

- created a fresh local repo with `main`, `origin`, `PLAN.json`, `PROGRESS.md`, and `init.sh`
- launched a real coding task in an isolated worktree
- simulated a completed harness repo inside the task worktree
- invoked `coding-task status` after the worker session disappeared

Observed result:

- `coding-task status` detected `session_missing=True`
- postflight ran automatically
- validation succeeded
- task branch merged into `main`
- `origin/main` advanced
- task status became `completed`
- task worktree directory was removed after success

Smoke sandbox used:

- repo: `/tmp/nanobot-postflight-smoke-lQLHaT/repo`
- remote: `/tmp/nanobot-postflight-smoke-lQLHaT/remote.git`

## Runtime rollout status

The local Telegram gateway was restarted in the existing tmux pane after the change.

Observed runtime evidence:

- tmux pane: `nanobot:1.0`
- restart time: `2026-04-07 09:24`
- log confirmation:
  - `Telegram bot @kimmydoomyBot connected`
  - commands registered successfully

## Known non-goals in this patch

These were intentionally not completed here even though the expanded micro-plan mentioned them:

- richer per-step postflight run events
- broader Telegram/UI affordances for “postflight running”
- explicit coverage for every failure branch of merge/push/reporting
- configurable target branch/remote beyond `main` and `origin`

## Suggested review output

Suggested review focus:

1. correctness and safety of the `test -> merge -> push` gate
2. concurrency/race risks around repeated refreshes
3. whether the `.codex-tasks/` dirty-check exemption is scoped correctly
4. any remaining stale-state rendering paths between list/status/history
