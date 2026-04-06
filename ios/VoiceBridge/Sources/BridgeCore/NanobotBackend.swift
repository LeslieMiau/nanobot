import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public struct NanobotBackend: BridgeBackend, Sendable {
    private struct ChatPayload: Codable {
        let text: String
        let speaker: String
    }

    private struct ChatResponse: Decodable {
        let reply: String
        let endConversation: Bool

        enum CodingKeys: String, CodingKey {
            case reply
            case endConversation = "end_conversation"
        }
    }

    private let config: BridgeConfig
    private let session: URLSessioning
    private let jsonEncoder = JSONEncoder()
    private let jsonDecoder = JSONDecoder()

    public init(config: BridgeConfig, session: URLSessioning) {
        self.config = config
        self.session = session
    }

    public func send(request: BridgeRequest) async throws -> BridgeResponse {
        guard request.backend == .nanobot else {
            throw BridgeError.unsupportedBackend(request.backend)
        }

        let urlRequest = try makeURLRequest(for: request)

        do {
            let (data, response) = try await session.data(for: urlRequest)
            guard let httpResponse = response as? HTTPURLResponse else {
                throw BridgeError.invalidResponse
            }

            switch httpResponse.statusCode {
            case 200 ..< 300:
                let payload = try jsonDecoder.decode(ChatResponse.self, from: data)
                return BridgeResponseFormatter.format(
                    reply: payload.reply,
                    endConversation: payload.endConversation
                )
            case 401:
                throw BridgeError.unauthorized
            default:
                throw BridgeError.backendFailure(statusCode: httpResponse.statusCode)
            }
        } catch let error as BridgeError {
            throw error
        } catch let error as URLError {
            if error.code == .timedOut {
                throw BridgeError.timeout
            }
            throw BridgeError.networkFailure(error.localizedDescription)
        } catch is DecodingError {
            throw BridgeError.invalidResponse
        } catch {
            throw BridgeError.networkFailure(error.localizedDescription)
        }
    }

    public func makeURLRequest(for request: BridgeRequest) throws -> URLRequest {
        var url = try config.validatedBaseURL()
        if url.lastPathComponent != "chat" {
            url.append(path: "chat")
        }

        var urlRequest = URLRequest(url: url)
        urlRequest.timeoutInterval = 8  // Siri kills intents after ~10s
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.setValue("Bearer \(try config.validatedAPIKey())", forHTTPHeaderField: "Authorization")
        urlRequest.httpBody = try jsonEncoder.encode(ChatPayload(text: request.prompt, speaker: request.speaker))
        return urlRequest
    }
}
