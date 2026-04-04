## 2026-04-04 Session Start
- Initialized a new harness checkpoint for the Telegram `/coding status` mismatch repair in `/Users/miau/Documents/nanobot`.
- Baseline verification from `bash ~/.codex/scripts/global-init.sh` found one pre-existing unrelated pytest failure: `tests/cli/test_restart_command.py::test_channels_status_shows_runtime_details` exits via a `load_config` monkeypatch signature mismatch. This task will keep that baseline separate and use focused verification for the `/coding` repair.
- Runtime diagnosis confirmed the active workspace store is `/Users/miau/.nanobot/workspace/automation/coding/tasks.json`, not the repository-local tree.
- The current Telegram private-chat task store still contains a visible `waiting_user` placeholder task `e15939a3` for `/Users/miau/Documents/codex-remote`, but the actual repo no longer has `PLAN.json` or `PROGRESS.md`; only `init.sh` remains, so the stored `repo_active_harness` conflict reason is stale.
- Repair intent for this task: when `/coding` sees a placeholder conflict record whose stored harness expectation no longer matches the repository's actual harness files, clear that stale record immediately and continue using live repo state as the source of truth.

## 2026-04-04 Implementation Checkpoint
- Added stale harness-conflict reconciliation to `nanobot/coding_tasks/policy.py`. The policy now checks `waiting_user` placeholder tasks with `repo_active_harness` or `repo_completed_harness` against `detect_repo_harness(repo_path)` before they can block a new task or become the default `/coding` control target.
- When the stored conflict reason no longer matches the repository's actual harness files, the placeholder record is auto-transitioned to `cancelled` with an audit summary instead of continuing to pollute `/coding status`, `/coding list`, or workspace blocking.
- Kept the rule intentionally narrow: genuine active harness conflicts still remain visible, and `worker_exit_review` waiting states are unchanged.
- Added regression coverage in `tests/coding_tasks/test_policy.py` and `tests/agent/test_coding_task_routing.py` for stale placeholder cleanup during status lookup, origin task listing, and new `/coding` task startup.
- Verification: `./.venv/bin/pytest tests/coding_tasks/test_policy.py tests/agent/test_coding_task_routing.py -q` passed with `42 passed in 0.30s`.
- Runtime data verification: applied the same policy logic to the live workspace store and cleared stale Telegram task `e15939a3`; before cleanup it was the only active `waiting_user` task, and afterward the active task set became empty.
- Baseline note remains unchanged: the unrelated pre-existing failure `tests/cli/test_restart_command.py::test_channels_status_shows_runtime_details` still reproduces and was not modified as part of this scoped fix.
