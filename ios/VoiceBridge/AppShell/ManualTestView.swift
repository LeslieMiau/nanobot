import SwiftUI

struct ManualTestView: View {
    @EnvironmentObject var state: BridgeAppState
    @State private var prompt = "你好"
    @State private var response = "尚未收到回复"

    var body: some View {
        Form {
            Section("Manual Smoke Test") {
                TextField("Prompt", text: $prompt)
                    .accessibilityIdentifier("manual.promptField")
                Button(state.isSending ? "Sending..." : "Send to nanobot") {
                    Task { @MainActor in
                        if let bridgeResponse = await state.send(prompt: prompt) {
                            response = bridgeResponse.displayText
                        } else if let errorMessage = state.lastErrorMessage {
                            response = errorMessage
                        } else {
                            response = "Configure the bridge first."
                        }
                    }
                }
                .disabled(state.isSending)
                .accessibilityIdentifier("manual.sendButton")
            }

            Section("Latest Reply") {
                Text(response)
                    .accessibilityIdentifier("manual.statusText")
                if let latest = state.latestResponse {
                    Text(latest.displayText)
                        .accessibilityIdentifier("manual.latestReply")
                }
                if let errorMessage = state.lastErrorMessage {
                    Text(errorMessage)
                        .accessibilityIdentifier("manual.latestError")
                }
            }
        }
    }
}
