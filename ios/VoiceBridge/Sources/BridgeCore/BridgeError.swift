import Foundation

public enum BridgeError: Error, Equatable, Sendable {
    case missingConfiguration(field: String)
    case invalidBaseURL(String)
    case unauthorized
    case timeout
    case networkFailure(String)
    case invalidResponse
    case backendFailure(statusCode: Int)
    case unsupportedBackend(BridgeBackendKind)

    public var userMessage: String {
        switch self {
        case let .missingConfiguration(field):
            switch field {
            case "serverURL":
                return "请先在应用中配置服务器地址。"
            case "apiKey":
                return "请先在应用中配置 API 密钥。"
            default:
                return "请先补全应用配置。"
            }
        case let .invalidBaseURL(value):
            return "服务器地址无效：\(value)"
        case .unauthorized:
            return "无法连接 nanobot，请检查 API 密钥是否正确。"
        case .timeout:
            return "nanobot 响应超时，请稍后再试。"
        case let .networkFailure(message):
            return "网络请求失败：\(message)"
        case .invalidResponse:
            return "nanobot 返回了无法解析的数据。"
        case let .backendFailure(statusCode):
            return "nanobot 请求失败，状态码 \(statusCode)。"
        case let .unsupportedBackend(kind):
            return "当前版本暂不支持后端：\(kind.rawValue)"
        }
    }
}
