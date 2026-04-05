import XCTest

@MainActor
final class VoiceBridgeUITests: XCTestCase {
    private let apiKey = "nb-3b7d4b91132c9bb850c2646f92860dc8"

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testManualSmokeFlowDisplaysBackendReply() {
        let app = XCUIApplication()
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_MODE"] = "1"
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_RESET_CONFIG"] = "1"
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_BASE_URL"] = "http://127.0.0.1:8900"
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_API_KEY"] = apiKey
        app.launch()

        let testTab = app.tabBars.buttons["Test"]
        XCTAssertTrue(testTab.waitForExistence(timeout: 10))
        testTab.tap()

        let sendButton = app.buttons["manual.sendButton"]
        XCTAssertTrue(sendButton.waitForExistence(timeout: 10))
        sendButton.tap()

        let latestReply = app.staticTexts["manual.latestReply"]
        XCTAssertTrue(latestReply.waitForExistence(timeout: 20))

        let placeholder = "尚未收到回复"
        let predicate = NSPredicate(format: "label != %@", placeholder)
        expectation(for: predicate, evaluatedWith: latestReply)
        waitForExpectations(timeout: 20)

        XCTAssertFalse(latestReply.label.isEmpty)
        XCTAssertFalse(app.staticTexts["manual.latestError"].exists)
    }
}
