import AppIntents

struct VoiceBridgeShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        [
            AppShortcut(
                intent: AskBridgeIntent(),
                phrases: [
                    "问纳博特",
                    "问纳博特 \(\.$prompt)"
                ],
                shortTitle: "Ask Nanobot",
                systemImageName: "waveform"
            )
        ]
    }
}

