# Siri Validation

## v1 acceptance target

Only `iPhone Siri` is part of the v1 pass condition.

## Supported phrases

- `嘿 Siri，问纳博特`

## Expected behavior

- Missing prompt should trigger a spoken follow-up question: `你想问纳博特什么？`
- Successful replies should be spoken back to the user
- Missing config, auth failures, timeout, or offline states should produce actionable spoken errors

## Simulator findings

- `XCUISiriService` on the iOS 18.6 simulator can trigger built-in Siri actions. A control probe using `Open Safari` reliably brought Safari to the foreground.
- The simulator also still passes the manual app smoke path: the Voice Bridge app can launch, send a manual prompt to `/chat`, and render a live backend reply.
- The supported two-step Siri phrase `问纳博特` followed by `你好` did not execute `AskBridgeIntent` in simulator UI tests. The app's persisted intent-result probe stayed at `No Siri intent recorded`.
- Treat the simulator as useful for Siri control probes and manual `/chat` smoke only. It is not a substitute for real-device Siri acceptance of the custom Voice Bridge invocation.

## Real-device UI smoke note

- The device UI test runner must not use `http://127.0.0.1:8900` as the backend URL. On a physical iPhone, `127.0.0.1` points back to the phone, not the Mac running nanobot.
- Real-device UI smoke should inject a Mac-reachable base URL through the host-side `VOICEBRIDGE_TEST_BASE_URL` environment variable before launching `xcodebuild test`.
- For the current workstation, the known reachable host is `http://192.168.3.79:8900` unless the local network address changes.
- The iPhone must have a real route to that host. In practice this means the phone and Mac must be on the same reachable LAN or another verified route, not just physically connected by USB for Xcode deployment.
- The first live run may trigger system prompts for local-network access or wireless-data access. Those prompts must be allowed, otherwise the app will surface `The Internet connection appears to be offline.`
- If the Mac firewall is enabled, the interpreter serving `nanobot` must also be allowed for incoming connections. A successful local `curl` from the Mac is not sufficient proof that the iPhone can reach the same service.
- After the app launches, it now calls `VoiceBridgeShortcuts.updateAppShortcutParameters()` so the system refreshes the registered App Shortcut metadata before Siri validation.

## Real-device Siri automation findings

- A real-device manual smoke test now passes end-to-end: the installed app can call `nanobot /chat` and render the reply on the connected iPhone.
- A real-device Siri control probe using the built-in phrase `Open Safari` also passes under `XCUISiriService`, so XCTest still has working Siri automation on the physical device.
- The custom Voice Bridge Siri phrase still does **not** execute `AskBridgeIntent` under XCTest automation on the physical device:
  - `问纳博特` followed by `你好` leaves `settings.lastIntentOutcome` at `No Siri intent recorded`
  - no new Voice Bridge-triggered `/chat` request is observed for that automated run
- Waiting after app launch, refreshing App Shortcut parameters on startup, and moving the app to the background before the Siri step did not change that result.
- Treat this as an XCTest automation boundary, not a proof that the product is broken on-device. The remaining acceptance step is a manual spoken Siri run on the physical iPhone.

## Inline prompt note

- `嘿 Siri，问纳博特 你好` is not a registered App Shortcut phrase in v1.
- Real Xcode metadata validation rejects free-form `String` interpolation inside App Shortcut phrases; the shipped v1 shortcut phrase is the follow-up form only.
- If Siri ever accepts an inline suffix on a real device, treat that as opportunistic system behavior, not a guaranteed contract.

## Non-goals for v1

- `HomePod` stable multi-turn conversational behavior
- `小爱同学` or `天猫精灵` runtime integration
- car head unit integration

Those surfaces are kept as future ingress adapters only.
