import AppIntents

struct VoiceBridgeShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: AskBridgeIntent(),
            phrases: [
                "问\(.applicationName)"
            ],
            shortTitle: "问纳博特",
            systemImageName: "waveform"
        )
    }
}
