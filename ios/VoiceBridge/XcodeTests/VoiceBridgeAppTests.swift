import XCTest
@testable import BridgeCore

final class VoiceBridgeAppTests: XCTestCase {
    func testDisplayTextPreservesLongReply() {
        let longReply = String(repeating: "测", count: 300)
        let response = BridgeResponseFormatter.format(reply: longReply, endConversation: false, spokenCharacterLimit: 32)

        XCTAssertEqual(response.displayText, longReply)
        XCTAssertTrue(response.spokenText.contains("完整回复已保存在纳博特应用中"))
    }

    func testInvalidBaseURLThrowsValidationError() {
        let config = BridgeConfig(
            backendKind: .nanobot,
            baseURL: "not-a-url",
            apiKey: "nb-test"
        )

        XCTAssertThrowsError(try config.validatedBaseURL()) { error in
            XCTAssertEqual(error as? BridgeError, .invalidBaseURL("not-a-url"))
        }
    }
}
