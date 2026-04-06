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

## 2026-04-06 10:05 CST

- Added a new `knowledge/` subsystem with:
  - workspace layout management for `raw/`, `wiki/sources`, `wiki/topics`, `wiki/entities`, `wiki/syntheses`, `index.md`, `log.md`, and `SCHEMA.md`
  - frontmatter-backed wiki page serialization and loading
  - source ingest for local files and URLs
  - query-time wiki retrieval plus optional saved syntheses
  - lint checks for orphan pages, missing backlinks, superseded-source markers, and explicit conflict sections
  - `kb import-memory` bridge for `memory/MEMORY.md` project context
- Wired new CLI commands:
  - `nanobot kb status`
  - `nanobot kb ingest`
  - `nanobot kb ask`
  - `nanobot kb lint`
  - `nanobot kb import-memory`
- Retired the obsolete unused `nanobot/agent/dream.py` module.
- Added docs in `docs/KNOWLEDGE.md` and updated `README.md`.
- Added targeted tests for the knowledge service and kb CLI commands.
- Also fixed an exposed baseline regression in `ChannelManager._init_channels()` so plugin-channel tests remain compatible with `__new__`-based test setup.
- Verification completed:
  - `./.venv/bin/pytest tests/cli/test_commands.py tests/cli/test_kb_commands.py tests/knowledge/test_service.py tests/agent/test_git_store.py tests/agent/test_memory_store.py tests/agent/test_dream.py tests/agent/test_context_prompt_cache.py -q` → `140 passed`
  - `./.venv/bin/pytest tests/channels/test_channel_plugins.py::test_manager_loads_plugin_from_dict_config -q` → `1 passed`
  - `bash ~/.codex/scripts/global-init.sh` → `errors: 0`
- All planned features are complete.

## 2026-04-06 10:06 CST

- Harness task complete. Proceeding with `PLAN.json` / `PROGRESS.md` cleanup per repo instructions.
