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

## Inline prompt note

- `嘿 Siri，问纳博特 你好` is not a registered App Shortcut phrase in v1.
- Real Xcode metadata validation rejects free-form `String` interpolation inside App Shortcut phrases; the shipped v1 shortcut phrase is the follow-up form only.
- If Siri ever accepts an inline suffix on a real device, treat that as opportunistic system behavior, not a guaranteed contract.

## Non-goals for v1

- `HomePod` stable multi-turn conversational behavior
- `小爱同学` or `天猫精灵` runtime integration
- car head unit integration

Those surfaces are kept as future ingress adapters only.
