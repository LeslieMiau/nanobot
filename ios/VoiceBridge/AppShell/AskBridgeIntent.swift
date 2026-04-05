import AppIntents

struct AskBridgeIntent: AppIntent {
    static var title: LocalizedStringResource = "Ask Nanobot"
    static var description = IntentDescription("Ask Nanobot through the Voice Bridge.")

    @Parameter(title: "Prompt", requestValueDialog: IntentDialog("你想问纳博特什么？"))
    var prompt: String

    static var parameterSummary: some ParameterSummary {
        Summary("Ask Nanobot \(\.$prompt)")
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
