public protocol BridgeBackend: Sendable {
    func send(request: BridgeRequest) async throws -> BridgeResponse
}
