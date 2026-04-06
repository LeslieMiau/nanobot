import SwiftUI

struct VoiceBridgeRootView: View {
    var body: some View {
        TabView {
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape") }
            ManualTestView()
                .tabItem { Label("Test", systemImage: "waveform") }
            HistoryView()
                .tabItem { Label("History", systemImage: "clock") }
        }
    }
}

