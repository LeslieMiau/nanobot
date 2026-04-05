import Foundation

public enum BridgeDefaults {
    public static let siriSpeaker = "siri-iphone"
    public static let siriPromptDialog = "你想问纳博特什么？"
    public static let spokenReplyLimit = 240
}

public enum BridgeSessionID {
    public static func make() -> String {
        UUID().uuidString
    }
}

public enum BridgeMessagePolicy {
    public static func spokenText(for reply: String) -> String {
        guard reply.count > BridgeDefaults.spokenReplyLimit else { return reply }
        let trimmed = String(reply.prefix(BridgeDefaults.spokenReplyLimit))
        return "\(trimmed)…完整回复已保存在纳博特应用中"
    }
}

public struct BridgeStoredConfig: Codable, Sendable, Equatable {
    public var backendKind: BridgeBackendKind
    public var baseURL: URL
    public var apiKey: String
}

public final class BridgeConfigStore {
    private let defaults: UserDefaults
    private let storageKey = "voice.bridge.config"

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    public func load() -> BridgeConfig? {
        guard
            let data = defaults.data(forKey: storageKey),
            let stored = try? JSONDecoder().decode(BridgeStoredConfig.self, from: data)
        else {
            return nil
        }
        return BridgeConfig(backendKind: stored.backendKind, baseURL: stored.baseURL, apiKey: stored.apiKey)
    }

    public func save(_ config: BridgeConfig) {
        let stored = BridgeStoredConfig(backendKind: config.backendKind, baseURL: config.baseURL, apiKey: config.apiKey)
        guard let data = try? JSONEncoder().encode(stored) else { return }
        defaults.set(data, forKey: storageKey)
    }
}

