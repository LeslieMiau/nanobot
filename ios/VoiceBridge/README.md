# Voice Bridge

`Voice Bridge` is a self-contained iOS subtree for turning voice ingress into a normalized text-turn bridge.

## Purpose

This subtree is intentionally designed to be movable into a dedicated repository later. Everything under `ios/VoiceBridge/` should stay independent of the Python runtime at the repo root.

## v1 scope

- Officially supported ingress: `iPhone Siri`
- Officially supported backend: `nanobot /chat`
- Future ingress reservations only: `HomePod`, `小爱同学`, `天猫精灵`, car head units, and other device surfaces
- Future backend reservations only: `openclaw` and other assistant backends

## Layout

- `Package.swift` - local Swift package manifest used to validate BridgeCore without full Xcode
- `Sources/BridgeCore/` - platform-neutral bridge contract, backend routing, reply formatting, history, config storage, and nanobot transport
- `Tests/BridgeCoreTests/` - focused tests for `/chat` encoding/decoding, error mapping, truncation, and history retention
- `AppShell/` - SwiftUI app shell, Siri/App Intent entry points, and thin adapters that depend on `BridgeCore`
- `XcodeTests/` - iOS-targeted XCTest smoke coverage for app-facing helpers
- `XcodeUITests/` - simulator UI smoke coverage for the manual prompt -> `/chat` path
- `Docs/` - local development, Xcode gate notes, Siri validation guidance, and future extension notes

## Migration rule

When this subtree is moved to a new repository, the runtime contract should stay the same:

- ingress adapters normalize device-specific voice input into text
- Bridge Core routes text turns to a backend
- backends return normalized reply payloads

The goal is to make the subtree portable without rewriting the bridge contract or Siri entry points.
