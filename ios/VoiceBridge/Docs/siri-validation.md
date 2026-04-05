# Siri Validation

## v1 acceptance target

Only `iPhone Siri` is part of the v1 pass condition.

## Supported phrases

- `嘿 Siri，问纳博特`
- `嘿 Siri，问纳博特 你好`

## Expected behavior

- Missing prompt should trigger a spoken follow-up question
- Inline prompt should try to pass the text directly into the bridge
- Successful replies should be spoken back to the user
- Missing config, auth failures, timeout, or offline states should produce actionable spoken errors

## Non-goals for v1

- `HomePod` stable multi-turn conversational behavior
- `小爱同学` or `天猫精灵` runtime integration
- car head unit integration

Those surfaces are kept as future ingress adapters only.

