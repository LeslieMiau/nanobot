import AppIntents

struct AskBridgeIntent: AppIntent {
    static var title: LocalizedStringResource = "问纳博特"
    static var description = IntentDescription("通过 Voice Bridge 问纳博特。")

    @Parameter(title: "Prompt", requestValueDialog: IntentDialog(BridgeDefaults.siriPromptDialog))
    var prompt: String

    static var parameterSummary: some ParameterSummary {
        Summary("问纳博特 \(\.$prompt)")
    }

    func perform() async throws -> some IntentResult {
        do {
            let response = try await BridgeIntentExecutor.execute(prompt: prompt)
            return .result(dialog: IntentDialog(response.spokenText))
        } catch {
            return .result(dialog: IntentDialog(BridgeIntentExecutor.fallbackMessage(for: error)))
        }
    }
}
