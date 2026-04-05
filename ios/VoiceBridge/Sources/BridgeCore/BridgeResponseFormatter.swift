import Foundation

public enum BridgeResponseFormatter {
    public static let defaultSpokenCharacterLimit = 240
    public static let defaultOverflowSuffix = "完整回复已保存在纳博特应用中。"

    public static func format(
        reply: String,
        endConversation: Bool,
        spokenCharacterLimit: Int = defaultSpokenCharacterLimit,
        overflowSuffix: String = defaultOverflowSuffix
    ) -> BridgeResponse {
        let trimmedReply = reply.trimmingCharacters(in: .whitespacesAndNewlines)
        let spokenText: String

        if trimmedReply.count > spokenCharacterLimit {
            let prefix = String(trimmedReply.prefix(spokenCharacterLimit))
                .trimmingCharacters(in: .whitespacesAndNewlines)
            spokenText = prefix + " " + overflowSuffix
        } else {
            spokenText = trimmedReply
        }

        return BridgeResponse(
            reply: trimmedReply,
            endConversation: endConversation,
            displayText: trimmedReply,
            spokenText: spokenText
        )
    }
}
