public struct OpenClawBackend: BridgeBackend, Sendable {
    public init() {}

    public func send(request: BridgeRequest) async throws -> BridgeResponse {
        throw BridgeError.unsupportedBackend(.openclaw)
    }
}
