import Foundation

public enum BridgeBackendKind: String, Codable, CaseIterable, Sendable {
    case nanobot
    case openclaw
}

public enum BridgeSourcePlatform: String, Codable, CaseIterable, Sendable {
    case siri
    case homepod
    case xiaoai
    case tmallgenie
    case carplay
    case custom
}

public enum BridgeSourceDeviceType: String, Codable, CaseIterable, Sendable {
    case phone
    case speaker
    case carHeadUnit
    case custom
}

public struct BridgeRequest: Codable, Sendable, Equatable {
    public var backend: BridgeBackendKind
    public var speaker: String
    public var sessionId: String
    public var prompt: String
    public var sourcePlatform: BridgeSourcePlatform
    public var sourceDeviceType: BridgeSourceDeviceType

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

public struct BridgeResponse: Codable, Sendable, Equatable {
    public var reply: String
    public var endConversation: Bool
    public var displayText: String
    public var spokenText: String

    public init(reply: String, endConversation: Bool, displayText: String? = nil, spokenText: String? = nil) {
        self.reply = reply
        self.endConversation = endConversation
        self.displayText = displayText ?? reply
        self.spokenText = spokenText ?? reply
    }
}

public struct BridgeConfig: Sendable, Equatable {
    public var backendKind: BridgeBackendKind
    public var baseURL: URL
    public var apiKey: String

    public init(backendKind: BridgeBackendKind, baseURL: URL, apiKey: String) {
        self.backendKind = backendKind
        self.baseURL = baseURL
        self.apiKey = apiKey
    }
}

public struct BridgeHistoryItem: Identifiable, Sendable, Equatable {
    public let id: UUID
    public let timestamp: Date
    public let prompt: String
    public let reply: String?
    public let errorMessage: String?

    public init(id: UUID = UUID(), timestamp: Date = Date(), prompt: String, reply: String?, errorMessage: String?) {
        self.id = id
        self.timestamp = timestamp
        self.prompt = prompt
        self.reply = reply
        self.errorMessage = errorMessage
    }
}

