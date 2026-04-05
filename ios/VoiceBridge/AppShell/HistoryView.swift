import SwiftUI

struct HistoryView: View {
    @EnvironmentObject var state: BridgeAppState

    var body: some View {
        List(state.recentHistory) { item in
            VStack(alignment: .leading, spacing: 6) {
                Text(item.prompt).font(.headline)
                if let reply = item.reply {
                    Text(reply).font(.subheadline)
                }
                if let errorMessage = item.errorMessage {
                    Text(errorMessage).font(.footnote)
                }
            }
        }
    }
}
