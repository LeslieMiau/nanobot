## Harness initialized - 2026-04-05 (Voice Bridge v1)
- Task summary:
  - Started a new harness for `Voice Bridge v1`, with the explicit goal of shipping `iPhone Siri -> App Intent -> Bridge -> nanobot /chat -> Siri 播报`.
  - Locked in the long-term architecture direction: future voice surfaces should go through a generic bridge layer first, using a text-turn protocol rather than raw audio as the internal standard.
- Baseline validation before new feature work:
  - `bash ~/.codex/scripts/global-init.sh` -> exited 0 during startup restore.
  - `bash init.sh` -> passed after repairing four brittle test failures in `tests/cli/test_restart_command.py`, `tests/config/test_config_migration.py`, `tests/test_openai_oauth_provider.py`, and `tests/tools/test_tool_validation.py`.
  - `.venv/bin/pytest tests/test_openai_oauth_provider.py tests/config/test_config_migration.py tests/cli/test_restart_command.py tests/tools/test_tool_validation.py -q` -> passed before initialization.
- Confirmed architecture decisions:
  - v1 runtime target is `iPhone Siri`; `HomePod` stays a future ingress experiment and is not part of the acceptance bar.
  - v1 backend target is `nanobot /chat`; `openclaw` remains a reserved backend slot only.
  - The bridge implementation must live inside a self-contained `ios/VoiceBridge/` subtree so it can later move into its own repository.
- Current blockers / environment gates:
  - `xcode-select -p` currently points at `/Library/Developer/CommandLineTools`.
  - `xcodebuild -showsdks` currently fails because full Xcode is not installed.
  - `xcrun simctl list devices available` currently fails because simulator tooling is unavailable without full Xcode.
  - The harness should treat full iOS build and Siri/App Intent runtime validation as blocked until the Xcode toolchain is available, while still allowing architecture and core code to progress.

## Session update - 2026-04-05 (Voice Bridge AppShell/Docs scaffold)
- Completed features:
  - Added a self-contained `ios/VoiceBridge/` subtree with a top-level `README.md` that explains the migration intent and keeps the bridge subtree portable for a future repo split.
  - Added architecture and operational docs under `ios/VoiceBridge/Docs/` covering the three-layer bridge design, local development/Xcode gating, Siri validation expectations, and future ingress/backend reservations.
  - Added an AppShell scaffold with Swift source for the bridge app entry, shared runtime/state container, App Intent/App Shortcuts entry point, nanobot backend client, local config storage, history model, manual smoke-test UI, settings UI, and history UI.
  - Added shared bridge support types for request/response models, source platform/device enums, session IDs, reply truncation policy, and local configuration persistence.
- Verification:
  - `rg --files ios/VoiceBridge` -> confirmed the subtree contains the README, Docs, and AppShell scaffolding files.
  - `swift -e 'import Foundation; print("foundation-ok")'` -> passed.
  - `swift -e 'import Foundation; import Combine; print("combine-ok")'` -> passed.
  - `python3 -m json.tool PLAN.json` and `python3 -m json.tool .harness/status.json` -> passed.
- Remaining blockers / follow-up:
  - Full Xcode is still missing, so `SwiftUI` / `AppIntents` / actual iOS build and Siri validation remain environment-gated.
  - `ios/VoiceBridge/` still lacks a checked-in Xcode project or Swift Package manifest by design for this write scope; the next thread can decide whether to add that packaging layer or keep the subtree source-only until the app repo split.
  - BridgeCore tests were intentionally not touched in this worker scope.

## Session update - 2026-04-05 (Voice Bridge BridgeCore package + AppShell alignment)
- Completed features:
  - Added a checked-in Swift Package under `ios/VoiceBridge/` with a `BridgeCore` library target and `BridgeCoreTests` so the bridge protocol, backend mapping, history store, and reply formatting can be validated on this machine without full Xcode.
  - Implemented BridgeCore source for backend kind/platform/device models, `BridgeRequest`, `BridgeResponse`, `BridgeConfig`, `BridgeError`, reply truncation, `BridgeRuntime`, `NanobotBackend`, `OpenClawBackend` placeholder, local history store, and config persistence.
  - Refactored the AppShell scaffold so Siri/App Intent and SwiftUI-facing runtime code depend on `BridgeCore` instead of duplicating bridge models and backend transport logic inside the app layer.
  - Added `.build/` to `.gitignore` and removed generated Swift Package artifacts from the worktree so the repository only carries source and harness state.
- Verification:
  - `swift test` in `ios/VoiceBridge/` -> passed (9 tests covering `/chat` encoding, response decoding, timeout/auth/malformed JSON mapping, truncation, and history retention).
  - `bash init.sh` in the repo root -> passed after the Voice Bridge source additions.
  - `git status --short` after removing `.build/` -> only shows source changes intended for the next checkpoint.
- Remaining blockers / follow-up:
  - Final iPhone Siri/App Intent runtime acceptance is still blocked by the local Xcode gate; this harness must not report v1 as complete until a full Xcode toolchain is available and the voice path is exercised on-device.
  - The current AppShell files are still scaffold source and have not been compiled on-device; they now point at the correct `BridgeCore` boundary, but real SwiftUI/App Intents validation remains pending.
