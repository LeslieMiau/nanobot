import AppIntents
import BridgeCore

struct AskBridgeIntent: AppIntent {
    static let title: LocalizedStringResource = "使用纳博特"
    static let description = IntentDescription("通过 Voice Bridge 使用纳博特。")
    static var openAppWhenRun: Bool { false }

    @Parameter(title: "Prompt")
    var prompt: String?

    @Parameter(title: "Follow Up 1")
    var followUp1: String?

    @Parameter(title: "Follow Up 2")
    var followUp2: String?

    @Parameter(title: "Follow Up 3")
    var followUp3: String?

    @Parameter(title: "Follow Up 4")
    var followUp4: String?

    @Parameter(title: "Follow Up 5")
    var followUp5: String?

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let sessionId = UUID().uuidString

        do {
            var lastPrompt = ""
            var lastSpokenText = ""

            for turnIndex in 0 ..< BridgeConversationControl.maxSiriTurnCount {
                let currentPrompt: String
                do {
                    currentPrompt = try await resolvePrompt(
                        at: turnIndex,
                        previousSpokenText: lastSpokenText
                    )
                } catch {
                    BridgeIntentResultStore.saveSuccess(
                        prompt: lastPrompt,
                        spokenText: BridgeConversationControl.endedDialog
                    )
                    return .result(dialog: "\(BridgeConversationControl.endedDialog)")
                }
                lastPrompt = currentPrompt

                if BridgeConversationControl.shouldEndLocally(currentPrompt) {
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
                lastSpokenText = response.spokenText

                if response.endConversation {
                    BridgeIntentResultStore.saveSuccess(
                        prompt: currentPrompt,
                        spokenText: response.spokenText
                    )
                    return .result(dialog: "\(response.spokenText)")
                }

                if turnIndex == BridgeConversationControl.maxSiriTurnCount - 1 {
                    let finalDialog = BridgeConversationControl.turnLimitDialog(after: response.spokenText)
                    BridgeIntentResultStore.saveSuccess(
                        prompt: currentPrompt,
                        spokenText: finalDialog
                    )
                    return .result(dialog: "\(finalDialog)")
                }

                BridgeIntentResultStore.saveSuccess(
                    prompt: currentPrompt,
                    spokenText: response.spokenText
                )
            }

            let fallbackDialog = BridgeConversationControl.turnLimitDialog(after: lastSpokenText)
            BridgeIntentResultStore.saveSuccess(prompt: lastPrompt, spokenText: fallbackDialog)
            return .result(dialog: "\(fallbackDialog)")
        } catch {
            let message = BridgeIntentExecutor.fallbackMessage(for: error)
            BridgeIntentResultStore.saveFailure(
                prompt: BridgeConversationControl.normalizePrompt(prompt ?? ""),
                message: message
            )
            return .result(dialog: "\(message)")
        }
    }

    private func resolvePrompt(at turnIndex: Int, previousSpokenText: String) async throws -> String {
        switch turnIndex {
        case 0:
            return try await resolveTurn(
                existingValue: prompt,
                dialog: BridgeConversationControl.initialPromptDialog
            ) {
                try await $prompt.requestValue("\(BridgeConversationControl.initialPromptDialog)")
            }
        case 1:
            return try await resolveTurn(
                existingValue: followUp1,
                dialog: BridgeConversationControl.followUpDialog(for: previousSpokenText)
            ) {
                try await $followUp1.requestValue(
                    "\(BridgeConversationControl.followUpDialog(for: previousSpokenText))"
                )
            }
        case 2:
            return try await resolveTurn(
                existingValue: followUp2,
                dialog: BridgeConversationControl.followUpDialog(for: previousSpokenText)
            ) {
                try await $followUp2.requestValue(
                    "\(BridgeConversationControl.followUpDialog(for: previousSpokenText))"
                )
            }
        case 3:
            return try await resolveTurn(
                existingValue: followUp3,
                dialog: BridgeConversationControl.followUpDialog(for: previousSpokenText)
            ) {
                try await $followUp3.requestValue(
                    "\(BridgeConversationControl.followUpDialog(for: previousSpokenText))"
                )
            }
        case 4:
            return try await resolveTurn(
                existingValue: followUp4,
                dialog: BridgeConversationControl.followUpDialog(for: previousSpokenText)
            ) {
                try await $followUp4.requestValue(
                    "\(BridgeConversationControl.followUpDialog(for: previousSpokenText))"
                )
            }
        default:
            return try await resolveTurn(
                existingValue: followUp5,
                dialog: BridgeConversationControl.followUpDialog(for: previousSpokenText)
            ) {
                try await $followUp5.requestValue(
                    "\(BridgeConversationControl.followUpDialog(for: previousSpokenText))"
                )
            }
        }
    }

    private func resolveTurn(
        existingValue: String?,
        dialog: String,
        request: () async throws -> String
    ) async throws -> String {
        let normalizedExisting = BridgeConversationControl.normalizePrompt(existingValue ?? "")
        if !normalizedExisting.isEmpty {
            return normalizedExisting
        }

        let requestedValue = try await request()
        return BridgeConversationControl.normalizePrompt(requestedValue)
    }
}
