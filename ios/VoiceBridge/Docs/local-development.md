# Local Development

## Environment gate

V1 iOS validation expects a full Xcode installation.

Current local machine notes:

- `xcode-select -p` may point to Command Line Tools only
- `xcodebuild -showsdks` requires a full Xcode toolchain
- simulator tooling is only available with Xcode installed

If Xcode is missing, treat this as an environment blocker, not an app bug.

## What can be verified early

- Swift source structure
- bridge request/response models
- backend client behavior in unit tests
- self-contained repo layout

## What needs full Xcode

- app target build
- App Intents and Siri phrase registration
- simulator or device validation

## Practical rule

Do not let the absence of Xcode erase the bridge architecture work. Record the gate clearly and continue with self-contained source scaffolding.

