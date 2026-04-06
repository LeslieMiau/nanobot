# Progress Log

## 2026-04-06 09:45 CST

- Initialized harness state for the persistent wiki rollout.
- Requested implementation scope: add a separate `knowledge/` wiki system while keeping existing `memory/` and Dream behavior intact.
- Current baseline before feature work:
  - `bash ~/.codex/scripts/global-init.sh` reports one existing failure in `tests/agent/test_git_store.py::TestInit::test_init_creates_git_dir`.
  - CLI help renders successfully.
  - Unrelated untracked file present: `docs/HANDOFF_CLAUDE_REVIEW_2026-04-06.md` (left untouched).
- Next step: fix the GitStore baseline so the knowledge rollout can be validated on a stable test floor.

## 2026-04-06 09:48 CST

- Fixed the pre-existing GitStore baseline failure by making `nanobot.utils.gitstore.GitStore` use the `git` CLI directly for init, commit, log, diff, and revert flows.
- The new implementation only considers the tracked memory files when checking status or generating diffs, which avoids unrelated repo noise.
- Verification completed:
  - `./.venv/bin/pytest tests/agent/test_git_store.py -q` → `33 passed`
  - `./.venv/bin/pytest tests/agent/test_memory_store.py tests/agent/test_dream.py tests/agent/test_context_prompt_cache.py -q` → `35 passed`
- Next step: build the new `knowledge/` workspace structure and core services.
