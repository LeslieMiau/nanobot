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

    @Test
    func localEndAndTurnLimitDialogsArePredictable() {
        #expect(BridgeConversationControl.shouldEndLocally(" "))
        #expect(BridgeConversationControl.shouldEndLocally("结束"))
        #expect(!BridgeConversationControl.shouldEndLocally("继续说这个问题"))
        #expect(
            BridgeConversationControl.turnLimitDialog(after: "你好。")
                == "你好 这轮先到这里。想继续的话，请再次说让纳博特回答。"
        )
        #expect(
            BridgeConversationControl.turnLimitDialog(after: " ")
                == BridgeConversationControl.turnLimitSuffix
        )
    }
}
