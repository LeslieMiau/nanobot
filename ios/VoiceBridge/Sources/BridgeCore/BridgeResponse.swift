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
