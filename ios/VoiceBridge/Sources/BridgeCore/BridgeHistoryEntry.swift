import Foundation

public struct BridgeHistoryEntry: Identifiable, Codable, Equatable, Sendable {
    public let id: UUID
    public let timestamp: Date
    public let prompt: String
    public let reply: String?
    public let backend: BridgeBackendKind
    public let sourcePlatform: BridgeSourcePlatform
    public let sourceDeviceType: BridgeSourceDeviceType
    public let errorMessage: String?

    public init(
        id: UUID = UUID(),
        timestamp: Date = Date(),
        prompt: String,
        reply: String?,
        backend: BridgeBackendKind,
        sourcePlatform: BridgeSourcePlatform,
        sourceDeviceType: BridgeSourceDeviceType,
        errorMessage: String?
    ) {
        self.id = id
        self.timestamp = timestamp
        self.prompt = prompt
        self.reply = reply
        self.backend = backend
        self.sourcePlatform = sourcePlatform
        self.sourceDeviceType = sourceDeviceType
        self.errorMessage = errorMessage
    }
}
