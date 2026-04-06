import Foundation
import Testing
@testable import BridgeCore

final class MockURLSession: URLSessioning, @unchecked Sendable {
    var nextResult: Result<(Data, URLResponse), Error>
    private(set) var lastRequest: URLRequest?

    init(nextResult: Result<(Data, URLResponse), Error>) {
        self.nextResult = nextResult
    }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        lastRequest = request
        return try nextResult.get()
    }
}

struct NanobotBackendTests {
    @Test
    func encodesChatRequestWithSpeakerAndBearerToken() async throws {
        let session = MockURLSession(
            nextResult: .success((
                Data(#"{"reply":"你好。","end_conversation":false}"#.utf8),
                HTTPURLResponse(
                    url: URL(string: "http://127.0.0.1:8900/chat")!,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: nil
                )!
            ))
        )
        let config = BridgeConfig(
            backendKind: .nanobot,
            baseURL: "http://127.0.0.1:8900",
            apiKey: "nb-test"
        )
        let backend = NanobotBackend(config: config, session: session)
        let request = BridgeRequest(
            backend: .nanobot,
            speaker: "siri-iphone",
            sessionId: "session-1",
            prompt: "你好",
            sourcePlatform: .siri,
            sourceDeviceType: .phone
        )

        _ = try await backend.send(request: request)

        #expect(session.lastRequest?.url?.absoluteString == "http://127.0.0.1:8900/chat")
        #expect(session.lastRequest?.httpMethod == "POST")
        #expect(session.lastRequest?.value(forHTTPHeaderField: "Authorization") == "Bearer nb-test")
        #expect(session.lastRequest?.value(forHTTPHeaderField: "Content-Type") == "application/json")

        let payload = try JSONSerialization.jsonObject(
            with: try #require(session.lastRequest?.httpBody),
            options: []
        ) as? [String: String]
        #expect(payload?["text"] == "你好")
        #expect(payload?["speaker"] == "siri-iphone")
    }

    @Test
    func decodesReplyAndEndConversation() async throws {
        let session = MockURLSession(
            nextResult: .success((
                Data(#"{"reply":"测试通过","end_conversation":true}"#.utf8),
                HTTPURLResponse(
                    url: URL(string: "http://127.0.0.1:8900/chat")!,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: nil
                )!
            ))
        )
        let backend = NanobotBackend(
            config: BridgeConfig(backendKind: .nanobot, baseURL: "http://127.0.0.1:8900", apiKey: "nb-test"),
            session: session
        )
        let request = BridgeRequest(
            backend: .nanobot,
            speaker: "siri-iphone",
            sessionId: "session-2",
            prompt: "测试",
            sourcePlatform: .siri,
            sourceDeviceType: .phone
        )

        let response = try await backend.send(request: request)

        #expect(response.reply == "测试通过")
        #expect(response.endConversation)
        #expect(response.displayText == "测试通过")
        #expect(response.spokenText == "测试通过")
    }

    @Test
    func mapsUnauthorizedToBridgeError() async throws {
        let session = MockURLSession(
            nextResult: .success((
                Data(),
                HTTPURLResponse(
                    url: URL(string: "http://127.0.0.1:8900/chat")!,
                    statusCode: 401,
                    httpVersion: nil,
                    headerFields: nil
                )!
            ))
        )
        let backend = NanobotBackend(
            config: BridgeConfig(backendKind: .nanobot, baseURL: "http://127.0.0.1:8900", apiKey: "nb-test"),
            session: session
        )
        let request = BridgeRequest(
            backend: .nanobot,
            speaker: "siri-iphone",
            sessionId: "session-3",
            prompt: "测试",
            sourcePlatform: .siri,
            sourceDeviceType: .phone
        )

        await #expect(throws: BridgeError.unauthorized) {
            _ = try await backend.send(request: request)
        }
    }

    @Test
    func mapsTimeoutToBridgeError() async throws {
        let session = MockURLSession(nextResult: .failure(URLError(.timedOut)))
        let backend = NanobotBackend(
            config: BridgeConfig(backendKind: .nanobot, baseURL: "http://127.0.0.1:8900", apiKey: "nb-test"),
            session: session
        )
        let request = BridgeRequest(
            backend: .nanobot,
            speaker: "siri-iphone",
            sessionId: "session-4",
            prompt: "测试",
            sourcePlatform: .siri,
            sourceDeviceType: .phone
        )

        await #expect(throws: BridgeError.timeout) {
            _ = try await backend.send(request: request)
        }
    }

    @Test
    func mapsMalformedJsonToInvalidResponse() async throws {
        let session = MockURLSession(
            nextResult: .success((
                Data(#"{"reply":42}"#.utf8),
                HTTPURLResponse(
                    url: URL(string: "http://127.0.0.1:8900/chat")!,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: nil
                )!
            ))
        )
        let backend = NanobotBackend(
            config: BridgeConfig(backendKind: .nanobot, baseURL: "http://127.0.0.1:8900", apiKey: "nb-test"),
            session: session
        )
        let request = BridgeRequest(
            backend: .nanobot,
            speaker: "siri-iphone",
            sessionId: "session-5",
            prompt: "测试",
            sourcePlatform: .siri,
            sourceDeviceType: .phone
        )

        await #expect(throws: BridgeError.invalidResponse) {
            _ = try await backend.send(request: request)
        }
    }
}
