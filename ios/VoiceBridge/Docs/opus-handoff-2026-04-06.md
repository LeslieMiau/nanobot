# VoiceBridge Siri Handoff

## Goal

Stabilize the `iPhone Siri -> App Intent -> VoiceBridge -> nanobot /chat -> Siri spoken reply` flow in `ios/VoiceBridge/`.

This handoff is for the state as of `2026-04-06`.

## Current status

What is confirmed working:

- The iOS app builds and installs on a real iPhone.
- The real-device manual smoke path works:
  - app launches
  - config is injected
  - app calls `nanobot /chat`
  - reply renders on-device
- Siri trigger phrases are now action-oriented and shipped in App Intents metadata:
  - `使用纳博特`
  - `在纳博特中提问`
  - `让纳博特回答`
- Manual spoken Siri invocations now reach nanobot. This is proven by live backend logs with `speaker=siri-iphone`.

What is still broken:

- Siri does not reliably speak the backend reply back to the user.
- XCTest Siri automation still cannot prove custom App Shortcut execution on-device, even though built-in Siri control works.
- The latest manual voice runs also exposed a separate backend/provider issue:
  - OpenAI OAuth quota/rate-limit errors are now appearing during Siri-triggered requests.

## Latest relevant commits

- `6672142 fix(voice-bridge): declare siri dialog return contract`
- `718fcfc fix(voice-bridge): avoid contact-like siri phrases`
- `0a656bf fix(voice-bridge): refresh app shortcuts on launch`
- `a29c5d9 fix(voice-bridge): diagnose real-device network path`
- `942f95d fix(voice-bridge): unblock real-device smoke path`

## Files most relevant to continue from

- [AskBridgeIntent.swift](/Users/miau/Documents/nanobot/.claude/worktrees/objective-hoover/ios/VoiceBridge/AppShell/AskBridgeIntent.swift)
- [VoiceBridgeShortcuts.swift](/Users/miau/Documents/nanobot/.claude/worktrees/objective-hoover/ios/VoiceBridge/AppShell/VoiceBridgeShortcuts.swift)
- [VoiceBridgeApp.swift](/Users/miau/Documents/nanobot/.claude/worktrees/objective-hoover/ios/VoiceBridge/AppShell/VoiceBridgeApp.swift)
- [BridgeIntentExecutor.swift](/Users/miau/Documents/nanobot/.claude/worktrees/objective-hoover/ios/VoiceBridge/AppShell/BridgeIntentExecutor.swift)
- [VoiceBridgeUITests.swift](/Users/miau/Documents/nanobot/.claude/worktrees/objective-hoover/ios/VoiceBridge/XcodeUITests/VoiceBridgeUITests.swift)
- [siri-validation.md](/Users/miau/Documents/nanobot/.claude/worktrees/objective-hoover/ios/VoiceBridge/Docs/siri-validation.md)
- [PROGRESS.md](/Users/miau/Documents/nanobot/.claude/worktrees/objective-hoover/PROGRESS.md)

## Verified evidence

### 1. Real-device manual app path is good

Real-device UI smoke passed with:

```bash
xcodebuild -project ios/VoiceBridge/VoiceBridge.xcodeproj \
  -scheme VoiceBridge \
  -destination 'id=00008130-001924C20E98001C' \
  -destination-timeout 180 \
  -derivedDataPath /tmp/VoiceBridge-device-ui-smoke-15-derived \
  -resultBundlePath /tmp/VoiceBridge-device-ui-smoke-15.xcresult \
  -allowProvisioningUpdates \
  DEVELOPMENT_TEAM=3G64PGKF3G \
  VOICEBRIDGE_TEST_BASE_URL='http://192.168.3.79:8900' \
  test \
  -only-testing:VoiceBridgeUITests/VoiceBridgeUITests/testManualSmokeFlowDisplaysBackendReply
```

Result:

- `Test Case '-[VoiceBridgeUITests.VoiceBridgeUITests testManualSmokeFlowDisplaysBackendReply]' passed`

### 2. Built-in Siri automation is good on the same physical device

Real-device control probe passed with:

```bash
xcodebuild ... \
  -only-testing:VoiceBridgeUITests/VoiceBridgeUITests/testSimulatorSiriCanOpenSafari
```

Result:

- `Activate Siri with voice recognition text: Open Safari`
- test passed on the physical iPhone

Conclusion:

- `XCUISiriService` itself is not broken on this device.

### 3. Custom App Shortcut automation is still not provable with XCTest

Real-device custom Siri test repeatedly failed with:

- `settings.lastIntentOutcome` stayed `No Siri intent recorded`
- no new Voice Bridge-triggered `/chat` request was observed for those automated runs

This remained true after:

- calling `VoiceBridgeShortcuts.updateAppShortcutParameters()` on app launch
- switching phrases away from `问纳博特`
- waiting after launch
- backgrounding the app before Siri activation

Conclusion:

- treat XCTest Siri automation as insufficient proof for this custom App Shortcut on this device

### 4. Manual spoken Siri trigger does reach nanobot

These log lines prove the manual Siri invocation is hitting nanobot:

```text
2026-04-06 16:40:11.046 | INFO | nanobot.api.server:handle_voice_ask:232 - Voice ask speaker=siri-iphone text=你好
2026-04-06 16:40:15.617 | INFO | nanobot.agent.loop:_process_message:658 - Response to api:user: 你好。
```

This means:

- Siri phrase -> App Intent -> VoiceBridge -> `/chat` is working at least sometimes

### 5. Latest manual runs hit provider quota/rate-limit errors

Newest logs:

```text
2026-04-06 16:49:19.165 | INFO     | nanobot.api.server:handle_voice_ask:232 - Voice ask speaker=siri-iphone text=你好
2026-04-06 16:49:21.173 | WARNING  | nanobot.providers.base:_run_with_retry:427 - LLM transient error (attempt 1/3), retrying in 1s: error calling openai oauth: chatgpt usage quota exceeded or rate limit triggered. please try again later.
2026-04-06 16:49:23.816 | WARNING  | nanobot.providers.base:_run_with_retry:427 - LLM transient error (attempt 2/3), retrying in 2s: error calling openai oauth: chatgpt usage quota exceeded or rate limit triggered. please try again later.
2026-04-06 16:49:27.275 | WARNING  | nanobot.providers.base:_run_with_retry:427 - LLM transient error (attempt 3/3), retrying in 4s: error calling openai oauth: chatgpt usage quota exceeded or rate limit triggered. please try again later.
2026-04-06 16:49:32.714 | ERROR    | nanobot.agent.loop:_run_agent_loop:445 - LLM returned error: Error calling OpenAI OAuth: ChatGPT usage quota exceeded or rate limit triggered. Please try again later.
2026-04-06 16:49:32.716 | INFO     | nanobot.agent.loop:_process_message:658 - Response to api:user: Error calling OpenAI OAuth: ChatGPT usage quota exceeded or rate limit triggered. Please try again later.
```

And again:

```text
2026-04-06 16:51:35.969 | INFO     | nanobot.api.server:handle_voice_ask:232 - Voice ask speaker=siri-iphone text=你好
2026-04-06 16:51:37.490 | WARNING  | nanobot.providers.base:_run_with_retry:427 - LLM transient error (attempt 1/3), retrying in 1s: error calling openai oauth: chatgpt usage quota exceeded or rate limit triggered. please try again later.
2026-04-06 16:51:39.991 | WARNING  | nanobot.providers.base:_run_with_retry:427 - LLM transient error (attempt 2/3), retrying in 2s: error calling openai oauth: chatgpt usage quota exceeded or rate limit triggered. please try again later.
```

This is a separate current blocker from the Siri intent plumbing.

## Important behavior changes already made

### App Shortcut phrase redesign

Old trigger phrase:

- `问纳博特`

Problem:

- Siri parsed it like “ask a person named 纳博特”, and the user saw:
  - `我在你的通讯录中没有找到纳博特`

Current trigger phrases:

- `使用纳博特`
- `在纳博特中提问`
- `让纳博特回答`

These are present in the built metadata at:

- `/tmp/VoiceBridge-device-siri-4-derived/Build/Products/Debug-iphoneos/VoiceBridge.app/Metadata.appintents/root.ssu.yaml`

### App Shortcut refresh

`VoiceBridgeApp` now calls:

```swift
VoiceBridgeShortcuts.updateAppShortcutParameters()
```

on launch, to force App Shortcut metadata refresh.

### Intent return type fix

`AskBridgeIntent.perform()` now returns:

```swift
some IntentResult & ProvidesDialog
```

instead of plain `some IntentResult`.

Reason:

- the intent always returns `.result(dialog: ...)`
- the old type declaration was inconsistent with that behavior

After this fix:

- real-device build still succeeds
- updated app was reinstalled to the iPhone

## Probable issue decomposition for Opus

There are now two separate issues. Do not conflate them.

### Issue A: Siri reply-path / App Intent presentation behavior

Evidence:

- manual Siri trigger reaches nanobot
- backend can produce a reply
- user still heard generic Siri failure text such as `出错了，请重试`

Possible focus areas:

- whether `.result(dialog: ...)` is sufficient here or if the intent should return a different capability mix
- whether the intent needs a different result type contract beyond `ProvidesDialog`
- whether the fallback/provider error path is causing Siri to suppress the spoken dialog
- whether the app/intent should donate or otherwise expose the shortcut differently for more stable Siri behavior

### Issue B: Backend provider quota/rate limit

Evidence:

- latest manual runs now fail in backend logs with:
  - `ChatGPT usage quota exceeded or rate limit triggered`

Possible focus areas:

- OAuth token/account quota status
- provider retry/fallback behavior for Siri-triggered requests
- whether Siri should receive a cleaner user-facing error instead of generic system failure

## Suggested next actions

1. Reproduce manually on the iPhone with the latest installed app:
   - `嘿 Siri，使用纳博特`
   - answer `你好`

2. While reproducing, tail:
   - `/tmp/nanobot-api.log`

3. Split diagnosis:
   - if request never hits backend: still a trigger/intent issue
   - if request hits backend and reply succeeds: focus on Siri dialog return path
   - if request hits backend and provider errors: fix quota/fallback path first

4. If continuing code work in App Intent:
   - start from [AskBridgeIntent.swift](/Users/miau/Documents/nanobot/.claude/worktrees/objective-hoover/ios/VoiceBridge/AppShell/AskBridgeIntent.swift)
   - then inspect [BridgeIntentExecutor.swift](/Users/miau/Documents/nanobot/.claude/worktrees/objective-hoover/ios/VoiceBridge/AppShell/BridgeIntentExecutor.swift)
   - then re-check the exact speech contract in [siri-validation.md](/Users/miau/Documents/nanobot/.claude/worktrees/objective-hoover/ios/VoiceBridge/Docs/siri-validation.md)

## Current workspace state

- Worktree: `/Users/miau/Documents/nanobot/.claude/worktrees/objective-hoover`
- Branch: `claude/objective-hoover`
- At time of writing, this branch contains the latest checkpoints above and is intended to be resumed from here.
