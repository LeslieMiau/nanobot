public struct BridgeRequest: Codable, Equatable, Sendable {
    public let backend: BridgeBackendKind
    public let speaker: String
    public let sessionId: String
    public let prompt: String
    public let sourcePlatform: BridgeSourcePlatform
    public let sourceDeviceType: BridgeSourceDeviceType

    public init(
        backend: BridgeBackendKind,
        speaker: String,
        sessionId: String,
        prompt: String,
        sourcePlatform: BridgeSourcePlatform,
        sourceDeviceType: BridgeSourceDeviceType
    ) {
        self.backend = backend
        self.speaker = speaker
        self.sessionId = sessionId
        self.prompt = prompt
        self.sourcePlatform = sourcePlatform
        self.sourceDeviceType = sourceDeviceType
    }
}
