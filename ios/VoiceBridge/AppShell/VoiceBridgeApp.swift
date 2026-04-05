import SwiftUI

@main
struct VoiceBridgeApp: App {
    @StateObject private var state = BridgeAppState()

    var body: some Scene {
        WindowGroup {
            VoiceBridgeRootView()
                .environmentObject(state)
        }
    }
}
