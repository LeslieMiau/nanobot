import Foundation

public struct BridgeResponse: Equatable, Sendable {
    public let reply: String
    public let endConversation: Bool
    public let displayText: String
    public let spokenText: String

    public init(
        reply: String,
        endConversation: Bool,
        displayText: String,
        spokenText: String
    ) {
        self.reply = reply
        self.endConversation = endConversation
        self.displayText = displayText
        self.spokenText = spokenText
    }
}

public enum BridgeConversationControl {
    public static let initialPromptDialog = "你想问纳博特什么？"
    public static let followUpPromptSuffix = "还想继续问什么？想结束就说结束。"
    public static let maxSiriTurnCount = 6
    public static let turnLimitSuffix = "这轮先到这里。想继续的话，请再次说让纳博特回答。"
    public static let localExitPhrases: Set<String> = [
        "结束",
        "退出",
        "再见",
        "不用了",
        "不用",
        "停止",
    ]
    public static let endedDialog = "好的，本轮对话结束。"

    private static let trimCharacterSet = CharacterSet.whitespacesAndNewlines
        .union(.punctuationCharacters)
        .union(CharacterSet(charactersIn: "，。！？；：（）【】《》“”‘’、"))

    public static func normalizePrompt(_ raw: String) -> String {
        raw.trimmingCharacters(in: trimCharacterSet)
    }

    public static func isExitPrompt(_ raw: String) -> Bool {
        localExitPhrases.contains(normalizePrompt(raw))
    }

    public static func shouldEndLocally(_ raw: String) -> Bool {
        let normalized = normalizePrompt(raw)
        return normalized.isEmpty || localExitPhrases.contains(normalized)
    }

    public static func followUpDialog(for spokenText: String) -> String {
        let trimmedReply = normalizePrompt(spokenText)
        if trimmedReply.isEmpty {
            return followUpPromptSuffix
        }
        return "\(trimmedReply) \(followUpPromptSuffix)"
    }

    public static func turnLimitDialog(after spokenText: String) -> String {
        let trimmedReply = normalizePrompt(spokenText)
        if trimmedReply.isEmpty {
            return turnLimitSuffix
        }
        return "\(trimmedReply) \(turnLimitSuffix)"
    }
}
