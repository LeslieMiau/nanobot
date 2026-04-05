# Local Development

## Environment gate

V1 iOS validation expects a full Xcode installation.

Current validated machine notes:

- `xcode-select -p` should point to `/Applications/Xcode.app/Contents/Developer`
- `xcodebuild -showsdks` should list iOS SDKs
- `xcrun simctl list devices available` should list iPhone simulator runtimes
- the current harness has been validated with `Xcode 16.4` plus the `iOS 18.6` simulator runtime

If a machine only has Command Line Tools, treat that as an environment blocker, not an app bug.

## What can be verified early

- `swift test` in `ios/VoiceBridge/`
- `swift -e 'import SwiftUI'`
- `swift -e 'import AppIntents'`
- `swiftc -typecheck ... AppShell/*.swift` against the macOS SDK and the built `BridgeCore` module
- Swift source structure
- bridge request/response models
- backend client behavior in unit tests
- self-contained repo layout

## What needs full Xcode

- app target build
- App Intents and Siri phrase registration
- simulator or device validation
- iPhone Siri / App Intent runtime acceptance

## What still needs a physical iPhone

- real Siri voice invocation
- App Shortcut registration behavior outside the simulator build pipeline
- confirmation that spoken follow-up reaches nanobot on-device

## Practical rule

Do not let the absence of a physical device erase the bridge architecture work. Record the gate clearly and continue with buildable, testable source scaffolding.
