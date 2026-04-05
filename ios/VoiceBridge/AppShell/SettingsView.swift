import BridgeCore
import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var state: BridgeAppState
    @State private var baseURL = BridgeDefaults.manualDefaultURL
    @State private var apiKey = ""
    @State private var saveStatus = "Not saved"
    @State private var lastIntentRecord: BridgeIntentRecord?

    var body: some View {
        Form {
            Section("Bridge Config") {
                TextField("Base URL", text: $baseURL)
                    .accessibilityIdentifier("settings.baseURLField")
                SecureField("API Key", text: $apiKey)
                    .accessibilityIdentifier("settings.apiKeyField")
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
                .accessibilityIdentifier("settings.saveButton")
                Text(saveStatus)
                    .accessibilityIdentifier("settings.saveStatus")
            }

            Section("v1 Scope") {
                Text("Official v1 ingress: iPhone Siri")
                Text("Reserved ingress only: HomePod, 小爱同学, 天猫精灵, car head units")
                Text("Official v1 backend: nanobot /chat")
            }

            Section("Last Siri Intent") {
                if let record = lastIntentRecord {
                    Text(record.prompt)
                        .accessibilityIdentifier("settings.lastIntentPrompt")
                    Text(record.outcome)
                        .accessibilityIdentifier("settings.lastIntentOutcome")
                    Text(record.succeeded ? "Success" : "Failure")
                        .accessibilityIdentifier("settings.lastIntentStatus")
                } else {
                    Text("No Siri intent recorded")
                        .accessibilityIdentifier("settings.lastIntentOutcome")
                }
            }
        }
        .task {
            await state.loadStoredConfig()
            if let current = state.config {
                baseURL = current.baseURL
                apiKey = current.apiKey
            }
            lastIntentRecord = BridgeIntentResultStore.load()
        }
        .onAppear {
            lastIntentRecord = BridgeIntentResultStore.load()
        }
    }
}
