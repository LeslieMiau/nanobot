import Foundation
import Testing
@testable import BridgeCore

private struct InMemoryConfigStore: BridgeConfigStore, Sendable {
    var config: BridgeConfig?

    func load() -> BridgeConfig? {
        config
    }

    func save(_ config: BridgeConfig) {}
}

struct BridgeRuntimeTests {
    @Test
    func trimsHistoryToMostRecentTwentyEntries() async {
        let store = BridgeHistoryStore(capacity: 20)

        for index in 0 ..< 25 {
            await store.append(
                BridgeHistoryEntry(
                    prompt: "prompt-\(index)",
                    reply: "reply-\(index)",
                    backend: .nanobot,
                    sourcePlatform: .siri,
                    sourceDeviceType: .phone,
                    errorMessage: nil
                )
            )
        }

        let entries = await store.allEntries()
        #expect(entries.count == 20)
        #expect(entries.first?.prompt == "prompt-24")
        #expect(entries.last?.prompt == "prompt-5")
    }

    @Test
    func recordsFailureInHistoryWhenBackendThrows() async throws {
        let runtime = BridgeRuntime(
            configStore: InMemoryConfigStore(
                config: BridgeConfig(
                    backendKind: .nanobot,
                    baseURL: "http://127.0.0.1:8900",
                    apiKey: "nb-test"
                )
            ),
            historyStore: BridgeHistoryStore(),
            session: MockURLSession(nextResult: .failure(URLError(.notConnectedToInternet)))
        )

        do {
            _ = try await runtime.send(prompt: "你好")
            Issue.record("Expected runtime send to throw a network failure")
        } catch let error as BridgeError {
            switch error {
            case let .networkFailure(message):
                #expect(!message.isEmpty)
            default:
                Issue.record("Expected networkFailure, got \(error)")
            }
        }

        let history = await runtime.history()
        #expect(history.count == 1)
        #expect(history[0].prompt == "你好")
        #expect(history[0].errorMessage?.contains("网络请求失败") == true)
    }
}
