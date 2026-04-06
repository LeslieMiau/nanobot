import BridgeCore
import Foundation

public struct BridgeIntentExecutor {
    private static let runtime = BridgeRuntime(
        configStore: UserDefaultsBridgeConfigStore(),
        session: URLSession.shared
    )

    public static func execute(prompt: String) async throws -> BridgeResponse {
        try await runtime.send(prompt: prompt)
    }

    public static func fallbackMessage(for error: Error) -> String {
        (error as? BridgeError)?.userMessage ?? "发生了未预期的 Voice Bridge 错误。"
    }
}
