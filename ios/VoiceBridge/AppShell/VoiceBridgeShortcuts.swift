import AppIntents

struct VoiceBridgeShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: AskBridgeIntent(),
            phrases: [
                "使用\(.applicationName)",
                "在\(.applicationName)中提问",
                "让\(.applicationName)回答"
            ],
            shortTitle: "使用纳博特",
            systemImageName: "waveform"
        )
    }
}
