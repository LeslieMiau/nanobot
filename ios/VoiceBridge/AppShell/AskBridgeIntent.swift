import AppIntents

struct AskBridgeIntent: AppIntent {
    static let title: LocalizedStringResource = "问纳博特"
    static let description = IntentDescription("通过 Voice Bridge 问纳博特。")

    @Parameter(title: "Prompt", requestValueDialog: "你想问纳博特什么？")
    var prompt: String

    func perform() async throws -> some IntentResult {
        do {
            let response = try await BridgeIntentExecutor.execute(prompt: prompt)
            return .result(dialog: "\(response.spokenText)")
        } catch {
            return .result(dialog: "\(BridgeIntentExecutor.fallbackMessage(for: error))")
        }
    }
}
