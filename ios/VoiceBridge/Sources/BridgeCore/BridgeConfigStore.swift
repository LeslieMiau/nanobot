import Foundation

public protocol BridgeConfigStore: Sendable {
    func load() -> BridgeConfig?
    func save(_ config: BridgeConfig)
}

public struct UserDefaultsBridgeConfigStore: BridgeConfigStore, @unchecked Sendable {
    private let defaults: UserDefaults
    private let storageKey: String

    public init(defaults: UserDefaults = .standard, storageKey: String = "voicebridge.config") {
        self.defaults = defaults
        self.storageKey = storageKey
    }

    public func load() -> BridgeConfig? {
        guard let data = defaults.data(forKey: storageKey) else {
            return nil
        }
        return try? JSONDecoder().decode(BridgeConfig.self, from: data)
    }

    public func save(_ config: BridgeConfig) {
        let data = try? JSONEncoder().encode(config)
        defaults.set(data, forKey: storageKey)
    }
}
