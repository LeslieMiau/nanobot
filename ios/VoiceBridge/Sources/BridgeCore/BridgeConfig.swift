import Foundation

public struct BridgeConfig: Codable, Equatable, Sendable {
    public let backendKind: BridgeBackendKind
    public let baseURL: String
    public let apiKey: String

    public init(
        backendKind: BridgeBackendKind,
        baseURL: String,
        apiKey: String
    ) {
        self.backendKind = backendKind
        self.baseURL = baseURL
        self.apiKey = apiKey
    }

    public func validatedBaseURL() throws -> URL {
        let trimmed = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw BridgeError.missingConfiguration(field: "serverURL")
        }
        guard let url = URL(string: trimmed), let scheme = url.scheme, !scheme.isEmpty else {
            throw BridgeError.invalidBaseURL(trimmed)
        }
        return url
    }

    public func validatedAPIKey() throws -> String {
        let trimmed = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw BridgeError.missingConfiguration(field: "apiKey")
        }
        return trimmed
    }
}
