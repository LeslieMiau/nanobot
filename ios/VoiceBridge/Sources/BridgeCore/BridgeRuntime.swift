import Foundation

public actor BridgeRuntime {
    private let configStore: BridgeConfigStore
    private let historyStore: BridgeHistoryStore
    private let session: URLSessioning

    public init(
        configStore: BridgeConfigStore,
        historyStore: BridgeHistoryStore = BridgeHistoryStore(),
        session: URLSessioning
    ) {
        self.configStore = configStore
        self.historyStore = historyStore
        self.session = session
    }

    public func currentConfig() -> BridgeConfig? {
        configStore.load()
    }

    public func save(config: BridgeConfig) {
        configStore.save(config)
    }

    public func history() async -> [BridgeHistoryEntry] {
        await historyStore.allEntries()
    }

    public func send(
        prompt: String,
        speaker: String = "siri-iphone",
        sourcePlatform: BridgeSourcePlatform = .siri,
        sourceDeviceType: BridgeSourceDeviceType = .phone,
        sessionId: String = UUID().uuidString
    ) async throws -> BridgeResponse {
        guard let config = configStore.load() else {
            throw BridgeError.missingConfiguration(field: "serverURL")
        }

        let request = BridgeRequest(
            backend: config.backendKind,
            speaker: speaker,
            sessionId: sessionId,
            prompt: prompt,
            sourcePlatform: sourcePlatform,
            sourceDeviceType: sourceDeviceType
        )

        do {
            let backend = try makeBackend(config: config)
            let response = try await backend.send(request: request)
            await historyStore.append(
                BridgeHistoryEntry(
                    prompt: prompt,
                    reply: response.reply,
                    backend: config.backendKind,
                    sourcePlatform: sourcePlatform,
                    sourceDeviceType: sourceDeviceType,
                    errorMessage: nil
                )
            )
            return response
        } catch let error as BridgeError {
            await historyStore.append(
                BridgeHistoryEntry(
                    prompt: prompt,
                    reply: nil,
                    backend: config.backendKind,
                    sourcePlatform: sourcePlatform,
                    sourceDeviceType: sourceDeviceType,
                    errorMessage: error.userMessage
                )
            )
            throw error
        }
    }

    private func makeBackend(config: BridgeConfig) throws -> any BridgeBackend {
        switch config.backendKind {
        case .nanobot:
            return NanobotBackend(config: config, session: session)
        case .openclaw:
            return OpenClawBackend()
        }
    }
}
