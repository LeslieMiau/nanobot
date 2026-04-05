import BridgeCore
import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var state: BridgeAppState
    @State private var baseURL = BridgeDefaults.manualDefaultURL
    @State private var apiKey = ""
    @State private var saveStatus = "Not saved"

    var body: some View {
        Form {
            Section("Bridge Config") {
                TextField("Base URL", text: $baseURL)
                SecureField("API Key", text: $apiKey)
                Button("Save") {
                    Task {
                        await state.updateConfig(
                            BridgeConfig(
                                backendKind: .nanobot,
                                baseURL: baseURL,
                                apiKey: apiKey
                            )
                        )
                        saveStatus = "Saved locally"
                    }
                }
                Text(saveStatus)
            }

            Section("v1 Scope") {
                Text("Official v1 ingress: iPhone Siri")
                Text("Reserved ingress only: HomePod, 小爱同学, 天猫精灵, car head units")
                Text("Official v1 backend: nanobot /chat")
            }
        }
        .task {
            await state.loadStoredConfig()
            if let current = state.config {
                baseURL = current.baseURL
                apiKey = current.apiKey
            }
        }
    }
}
