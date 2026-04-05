import Foundation

public struct BridgeIntentExecutor {
    public static func execute(prompt: String) async throws -> BridgeResponse {
        let store = BridgeConfigStore()
        guard let config = store.load() else {
            throw BridgeRuntimeError.missingConfiguration
        }

        let request = BridgeRequest(
            backend: config.backendKind,
            speaker: BridgeDefaults.siriSpeaker,
            sessionId: BridgeSessionID.make(),
            prompt: prompt,
            sourcePlatform: .siri,
            sourceDeviceType: .phone
        )
        return try await NanobotBackend().send(request: request, config: config)
    }

    public static func fallbackMessage(for error: Error) -> String {
        switch error {
        case BridgeRuntimeError.missingConfiguration:
            return "Configure the bridge first."
        case BridgeRuntimeError.invalidResponse:
            return "Nanobot returned an invalid response."
        case BridgeRuntimeError.timeout:
            return "Nanobot timed out."
        case let BridgeRuntimeError.network(message):
            return "Network error: \(message)"
        case let BridgeRuntimeError.auth(message):
            return "Authentication error: \(message)"
        default:
            return "Unexpected bridge error."
        }
    }
}
