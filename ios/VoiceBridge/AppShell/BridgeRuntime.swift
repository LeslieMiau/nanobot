import BridgeCore
import Combine
import Foundation

@MainActor
public final class BridgeAppState: ObservableObject {
    @Published public private(set) var config: BridgeConfig?
    @Published public private(set) var latestResponse: BridgeResponse?
    @Published public private(set) var recentHistory: [BridgeHistoryEntry] = []
    @Published public private(set) var isSending = false
    @Published public private(set) var lastErrorMessage: String?

    private let runtime: BridgeRuntime

    public init(
        runtime: BridgeRuntime = BridgeRuntime(
            configStore: UserDefaultsBridgeConfigStore(),
            session: URLSession.shared
        )
    ) {
        self.runtime = runtime
    }

    public func updateConfig(_ config: BridgeConfig) async {
        self.config = config
        await runtime.save(config: config)
        recentHistory = await runtime.history()
    }

    public func loadStoredConfig() async {
        config = await runtime.currentConfig()
        recentHistory = await runtime.history()
    }

    public func send(prompt: String) async -> BridgeResponse? {
        isSending = true
        defer { isSending = false }

        let request = BridgeRequest(
            backend: .nanobot,
            speaker: "siri-iphone",
            sessionId: UUID().uuidString,
            prompt: prompt,
            sourcePlatform: .siri,
            sourceDeviceType: .phone
        )

        do {
            let response = try await runtime.send(
                prompt: request.prompt,
                speaker: request.speaker,
                sourcePlatform: request.sourcePlatform,
                sourceDeviceType: request.sourceDeviceType,
                sessionId: request.sessionId
            )
            lastErrorMessage = nil
            latestResponse = response
            config = await runtime.currentConfig()
            recentHistory = await runtime.history()
            return response
        } catch let error as BridgeError {
            lastErrorMessage = error.userMessage
            config = await runtime.currentConfig()
            recentHistory = await runtime.history()
            return nil
        } catch {
            let message = BridgeIntentExecutor.fallbackMessage(for: error)
            lastErrorMessage = message
            config = await runtime.currentConfig()
            recentHistory = await runtime.history()
            return nil
        }
    }
}
