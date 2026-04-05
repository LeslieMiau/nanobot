import Combine
import Foundation

public enum BridgeRuntimeError: Error, Sendable, Equatable {
    case missingConfiguration
    case invalidResponse
    case network(String)
    case auth(String)
    case timeout
}

public protocol BridgeBackend: Sendable {
    func send(request: BridgeRequest, config: BridgeConfig) async throws -> BridgeResponse
}

@MainActor
public final class BridgeAppState: ObservableObject {
    @Published public private(set) var config: BridgeConfig?
    @Published public private(set) var latestResponse: BridgeResponse?
    @Published public private(set) var recentHistory: [BridgeHistoryItem] = []
    @Published public private(set) var isSending = false
    @Published public private(set) var lastErrorMessage: String?

    private let configStore: BridgeConfigStore

    public init(configStore: BridgeConfigStore = BridgeConfigStore()) {
        self.configStore = configStore
        self.config = configStore.load()
    }

    public func updateConfig(_ config: BridgeConfig) {
        self.config = config
        configStore.save(config)
    }

    public func loadStoredConfig() {
        config = configStore.load()
    }

    public func send(prompt: String) async -> BridgeResponse? {
        guard let config else {
            lastErrorMessage = "Configure the bridge first."
            recordFailure(prompt: prompt, errorMessage: lastErrorMessage ?? "Missing configuration")
            return nil
        }

        isSending = true
        defer { isSending = false }

        let request = BridgeRequest(
            backend: config.backendKind,
            speaker: BridgeDefaults.siriSpeaker,
            sessionId: BridgeSessionID.make(),
            prompt: prompt,
            sourcePlatform: .siri,
            sourceDeviceType: .phone
        )

        do {
            let response = try await NanobotBackend().send(request: request, config: config)
            lastErrorMessage = nil
            record(prompt: prompt, response: response)
            return response
        } catch {
            let message = BridgeIntentExecutor.fallbackMessage(for: error)
            lastErrorMessage = message
            recordFailure(prompt: prompt, errorMessage: message)
            return nil
        }
    }

    public func record(prompt: String, response: BridgeResponse) {
        recentHistory.insert(
            BridgeHistoryItem(prompt: prompt, reply: response.reply, errorMessage: nil),
            at: 0
        )
        recentHistory = Array(recentHistory.prefix(20))
        latestResponse = response
    }

    public func recordFailure(prompt: String, errorMessage: String) {
        recentHistory.insert(
            BridgeHistoryItem(prompt: prompt, reply: nil, errorMessage: errorMessage),
            at: 0
        )
        recentHistory = Array(recentHistory.prefix(20))
    }
}
