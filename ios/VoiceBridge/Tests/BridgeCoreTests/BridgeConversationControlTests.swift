import Testing
@testable import BridgeCore

struct BridgeConversationControlTests {
    @Test
    func normalizesPromptBeforeExitDetection() {
        #expect(BridgeConversationControl.normalizePrompt("  再见。  ") == "再见")
        #expect(BridgeConversationControl.isExitPrompt("退出！"))
        #expect(BridgeConversationControl.isExitPrompt(" 不用了 "))
        #expect(!BridgeConversationControl.isExitPrompt("再见一下这个函数"))
    }

    @Test
    func followUpDialogIncludesReplyAndPrompt() {
        #expect(
            BridgeConversationControl.followUpDialog(for: "你好。")
                == "你好 还想继续问什么？想结束就说结束。"
        )
        #expect(
            BridgeConversationControl.followUpDialog(for: " ")
                == BridgeConversationControl.followUpPromptSuffix
        )
    }
}
