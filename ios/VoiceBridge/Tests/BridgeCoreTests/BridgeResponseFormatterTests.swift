import Testing
@testable import BridgeCore

struct BridgeResponseFormatterTests {
    @Test
    func keepsShortReplyUntouched() {
        let response = BridgeResponseFormatter.format(reply: "你好。", endConversation: false, spokenCharacterLimit: 10)

        #expect(response.reply == "你好。")
        #expect(response.displayText == "你好。")
        #expect(response.spokenText == "你好。")
    }

    @Test
    func truncatesLongSpokenReplyButKeepsDisplayText() {
        let longReply = String(repeating: "今", count: 300)
        let response = BridgeResponseFormatter.format(reply: longReply, endConversation: false, spokenCharacterLimit: 32)

        #expect(response.displayText == longReply)
        #expect(response.spokenText.count > 32)
        #expect(response.spokenText.contains("完整回复已保存在纳博特应用中"))
        #expect(response.reply == longReply)
    }
}
