# Voice Bridge Architecture

## Overview

The bridge uses three layers:

1. `Ingress adapters`
2. `Voice Bridge core`
3. `Backends`

## Ingress adapters

Ingress adapters are responsible for platform-specific wake-up, permissions, STT/TTS behavior, and device session handling.

Reserved future adapters:

- `iPhone Siri`
- `HomePod`
- `小爱同学`
- `天猫精灵`
- car head units
- other phone or speaker surfaces

## Voice Bridge core

Core owns the platform-neutral contract:

- `BridgeRequest`
- `BridgeResponse`
- `BridgeRuntime`
- request normalization
- response formatting
- error mapping
- local history recording

Core should not know about raw audio streams or platform-specific voice UX details.

The checked-in implementation currently lives under `Sources/BridgeCore/` as a Swift package target so the contract can be tested before full Xcode is available.

## Backends

V1 backend:

- `nanobot`

Reserved future backend:

- `openclaw`

The bridge should be able to route by backend kind without changing the Siri-facing API.

`AppShell/` is intentionally a thin layer over `BridgeCore`; it should not carry its own divergent bridge protocol or backend transport stack.
