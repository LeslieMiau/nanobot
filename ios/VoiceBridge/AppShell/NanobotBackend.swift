import Foundation

public struct NanobotBackend: BridgeBackend {
    public init() {}

    public func send(request: BridgeRequest, config: BridgeConfig) async throws -> BridgeResponse {
        let endpoint = config.baseURL.appendingPathComponent("chat")
        var urlRequest = URLRequest(url: endpoint)
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.setValue("Bearer \(config.apiKey)", forHTTPHeaderField: "Authorization")

        let payload = NanobotRequestBody(text: request.prompt, speaker: request.speaker)
        urlRequest.httpBody = try JSONEncoder().encode(payload)

        do {
            let (data, response) = try await URLSession.shared.data(for: urlRequest)
            guard let httpResponse = response as? HTTPURLResponse else {
                throw BridgeRuntimeError.invalidResponse
            }

            guard (200..<300).contains(httpResponse.statusCode) else {
                if httpResponse.statusCode == 401 {
                    throw BridgeRuntimeError.auth("nanobot returned 401")
                }
                throw BridgeRuntimeError.network("nanobot returned HTTP \(httpResponse.statusCode)")
            }

            do {
                let decoded = try JSONDecoder().decode(NanobotResponseBody.self, from: data)
                return BridgeResponse(
                    reply: decoded.reply,
                    endConversation: decoded.endConversation ?? false,
                    displayText: decoded.reply,
                    spokenText: BridgeMessagePolicy.spokenText(for: decoded.reply)
                )
            } catch {
                throw BridgeRuntimeError.invalidResponse
            }
        } catch let error as URLError {
            if error.code == .timedOut {
                throw BridgeRuntimeError.timeout
            }
            throw BridgeRuntimeError.network(error.localizedDescription)
        } catch {
            throw BridgeRuntimeError.network(error.localizedDescription)
        }
    }
}

private struct NanobotRequestBody: Encodable {
    let text: String
    let speaker: String
}

private struct NanobotResponseBody: Decodable {
    let reply: String
    let endConversation: Bool?

    enum CodingKeys: String, CodingKey {
        case reply
        case endConversation = "end_conversation"
    }
}
