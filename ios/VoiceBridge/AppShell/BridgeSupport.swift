import BridgeCore
import Foundation

public enum BridgeDefaults {
    public static let assistantName = "纳博特"
    public static let siriPromptDialog = "你想问纳博特什么？"
    public static let manualDefaultURL = "http://127.0.0.1:8900"
    public static let missingConfigMessage = "请先在应用中配置服务器地址和 API 密钥。"
    public static let configStorageKey = "voicebridge.config"
    public static let intentResultStorageKey = "voicebridge.intent-result"
}

struct BridgeIntentRecord: Codable {
    let prompt: String
    let outcome: String
    let succeeded: Bool
    let timestamp: Date
}

enum BridgeIntentResultStore {
    static func load(defaults: UserDefaults = .standard) -> BridgeIntentRecord? {
        guard let data = defaults.data(forKey: BridgeDefaults.intentResultStorageKey) else {
            return nil
        }
        return try? JSONDecoder().decode(BridgeIntentRecord.self, from: data)
    }

    static func saveSuccess(
        prompt: String,
        spokenText: String,
        defaults: UserDefaults = .standard
    ) {
        save(
            BridgeIntentRecord(
                prompt: prompt,
                outcome: spokenText,
                succeeded: true,
                timestamp: Date()
            ),
            defaults: defaults
        )
    }

    static func saveFailure(
        prompt: String,
        message: String,
        defaults: UserDefaults = .standard
    ) {
        save(
            BridgeIntentRecord(
                prompt: prompt,
                outcome: message,
                succeeded: false,
                timestamp: Date()
            ),
            defaults: defaults
        )
    }

    static func clear(defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: BridgeDefaults.intentResultStorageKey)
    }

    private static func save(_ record: BridgeIntentRecord, defaults: UserDefaults) {
        let data = try? JSONEncoder().encode(record)
        defaults.set(data, forKey: BridgeDefaults.intentResultStorageKey)
    }
}

enum BridgeLaunchConfiguration {
    private static let enabledKey = "VOICEBRIDGE_UI_TEST_MODE"
    private static let baseURLKey = "VOICEBRIDGE_UI_TEST_BASE_URL"
    private static let apiKeyKey = "VOICEBRIDGE_UI_TEST_API_KEY"
    private static let resetConfigKey = "VOICEBRIDGE_UI_TEST_RESET_CONFIG"
    private static let resetIntentResultKey = "VOICEBRIDGE_UI_TEST_RESET_INTENT_RESULT"

    static func primeUserDefaults() {
        let environment = ProcessInfo.processInfo.environment
        guard environment[enabledKey] == "1" else { return }

        let defaults = UserDefaults.standard
        if environment[resetConfigKey] == "1" {
            defaults.removeObject(forKey: BridgeDefaults.configStorageKey)
        }
        if environment[resetIntentResultKey] == "1" {
            BridgeIntentResultStore.clear(defaults: defaults)
        }

        guard
            let baseURL = environment[baseURLKey],
            let apiKey = environment[apiKeyKey],
            !baseURL.isEmpty,
            !apiKey.isEmpty
        else {
            return
        }

        let config = BridgeConfig(
            backendKind: .nanobot,
            baseURL: baseURL,
            apiKey: apiKey
        )
        let data = try? JSONEncoder().encode(config)
        defaults.set(data, forKey: BridgeDefaults.configStorageKey)
    }
}
