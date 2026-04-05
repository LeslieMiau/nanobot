# Siri Validation

## v1 acceptance target

Only `iPhone Siri` is part of the v1 pass condition.

## Supported phrases

- `嘿 Siri，问纳博特`

## Expected behavior

- Missing prompt should trigger a spoken follow-up question: `你想问纳博特什么？`
- Successful replies should be spoken back to the user
- Missing config, auth failures, timeout, or offline states should produce actionable spoken errors

## Inline prompt note

- `嘿 Siri，问纳博特 你好` is not a registered App Shortcut phrase in v1.
- Real Xcode metadata validation rejects free-form `String` interpolation inside App Shortcut phrases; the shipped v1 shortcut phrase is the follow-up form only.
- If Siri ever accepts an inline suffix on a real device, treat that as opportunistic system behavior, not a guaranteed contract.

## Non-goals for v1

- `HomePod` stable multi-turn conversational behavior
- `小爱同学` or `天猫精灵` runtime integration
- car head unit integration

Those surfaces are kept as future ingress adapters only.
