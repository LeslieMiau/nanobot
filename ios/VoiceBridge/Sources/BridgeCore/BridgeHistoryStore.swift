public actor BridgeHistoryStore {
    private let capacity: Int
    private var entries: [BridgeHistoryEntry]

    public init(capacity: Int = 20, entries: [BridgeHistoryEntry] = []) {
        self.capacity = capacity
        self.entries = Array(entries.prefix(capacity))
    }

    public func append(_ entry: BridgeHistoryEntry) {
        entries.insert(entry, at: 0)
        if entries.count > capacity {
            entries = Array(entries.prefix(capacity))
        }
    }

    public func allEntries() -> [BridgeHistoryEntry] {
        entries
    }
}
