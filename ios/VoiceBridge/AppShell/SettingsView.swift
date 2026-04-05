import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var state: BridgeAppState
    @State private var baseURL = "http://127.0.0.1:8900"
    @State private var apiKey = ""
    @State private var saveStatus = "Not saved"

    var body: some View {
        Form {
            Section("Bridge Config") {
                TextField("Base URL", text: $baseURL)
                SecureField("API Key", text: $apiKey)
                Button("Save") {
                    if let url = URL(string: baseURL) {
                        state.updateConfig(BridgeConfig(backendKind: .nanobot, baseURL: url, apiKey: apiKey))
                        saveStatus = "Saved locally"
                    } else {
                        saveStatus = "Invalid base URL"
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
        .onAppear {
            if let current = state.config {
                baseURL = current.baseURL.absoluteString
                apiKey = current.apiKey
            } else {
                state.loadStoredConfig()
                if let current = state.config {
                    baseURL = current.baseURL.absoluteString
                    apiKey = current.apiKey
                }
            }
        }
    }
}
