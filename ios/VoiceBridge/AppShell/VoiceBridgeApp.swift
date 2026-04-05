import SwiftUI

@main
struct VoiceBridgeApp: App {
    @StateObject private var state = BridgeAppState()

    init() {
        BridgeLaunchConfiguration.primeUserDefaults()
    }

    var body: some Scene {
        WindowGroup {
            VoiceBridgeRootView()
                .environmentObject(state)
        }
    }
}
