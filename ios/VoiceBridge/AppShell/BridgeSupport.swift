import BridgeCore
import Foundation

public enum BridgeDefaults {
    public static let assistantName = "纳博特"
    public static let siriPromptDialog = "你想问纳博特什么？"
    public static let manualDefaultURL = "http://127.0.0.1:8900"
    public static let missingConfigMessage = "请先在应用中配置服务器地址和 API 密钥。"
    public static let configStorageKey = "voicebridge.config"
}

enum BridgeLaunchConfiguration {
    private static let enabledKey = "VOICEBRIDGE_UI_TEST_MODE"
    private static let baseURLKey = "VOICEBRIDGE_UI_TEST_BASE_URL"
    private static let apiKeyKey = "VOICEBRIDGE_UI_TEST_API_KEY"
    private static let resetConfigKey = "VOICEBRIDGE_UI_TEST_RESET_CONFIG"

    static func primeUserDefaults() {
        let environment = ProcessInfo.processInfo.environment
        guard environment[enabledKey] == "1" else { return }

        let defaults = UserDefaults.standard
        if environment[resetConfigKey] == "1" {
            defaults.removeObject(forKey: BridgeDefaults.configStorageKey)
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
