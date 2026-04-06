import AppIntents
import BridgeCore

struct AskBridgeIntent: AppIntent {
    static let title: LocalizedStringResource = "使用纳博特"
    static let description = IntentDescription("通过 Voice Bridge 使用纳博特。")
    static var openAppWhenRun: Bool { false }

    @Parameter(title: "Prompt")
    var prompt: String?

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let sessionId = UUID().uuidString

        do {
            var currentPrompt = try await resolveInitialPrompt()

            while true {
                if BridgeConversationControl.isExitPrompt(currentPrompt) {
                    BridgeIntentResultStore.saveSuccess(
                        prompt: currentPrompt,
                        spokenText: BridgeConversationControl.endedDialog
                    )
                    return .result(dialog: "\(BridgeConversationControl.endedDialog)")
                }

                let response = try await BridgeIntentExecutor.execute(
                    prompt: currentPrompt,
                    sessionId: sessionId
                )
                BridgeIntentResultStore.saveSuccess(
                    prompt: currentPrompt,
                    spokenText: response.spokenText
                )

                if response.endConversation {
                    return .result(dialog: "\(response.spokenText)")
                }

                do {
                    currentPrompt = try await $prompt.requestValue(
                        "\(BridgeConversationControl.followUpDialog(for: response.spokenText))"
                    )
                } catch {
                    BridgeIntentResultStore.saveSuccess(
                        prompt: currentPrompt,
                        spokenText: response.spokenText
                    )
                    return .result(dialog: "\(BridgeConversationControl.endedDialog)")
                }
            }
        } catch {
            let message = BridgeIntentExecutor.fallbackMessage(for: error)
            BridgeIntentResultStore.saveFailure(
                prompt: BridgeConversationControl.normalizePrompt(prompt ?? ""),
                message: message
            )
            return .result(dialog: "\(message)")
        }
    }

    private func resolveInitialPrompt() async throws -> String {
        if let prompt, !BridgeConversationControl.normalizePrompt(prompt).isEmpty {
            return prompt
        }
        return try await $prompt.requestValue("\(BridgeConversationControl.initialPromptDialog)")
    }
}
