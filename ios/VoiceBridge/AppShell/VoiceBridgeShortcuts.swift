import AppIntents

struct VoiceBridgeShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: AskBridgeIntent(),
            phrases: [
                "在\(.applicationName)中提问",
                "让\(.applicationName)回答",
                "和\(.applicationName)对话"
            ],
            shortTitle: "让纳博特回答",
            systemImageName: "waveform"
        )
    }
}
