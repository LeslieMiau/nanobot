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
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_RESET_INTENT_RESULT"] = "1"
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

    func testSiriFollowUpPhraseStoresIntentResult() {
        let app = XCUIApplication()
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_MODE"] = "1"
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_RESET_CONFIG"] = "1"
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_RESET_INTENT_RESULT"] = "1"
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_BASE_URL"] = "http://127.0.0.1:8900"
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_API_KEY"] = apiKey
        app.launch()

        XCUIDevice.shared.siriService.activate(voiceRecognitionText: "问纳博特")
        sleep(1)
        XCUIDevice.shared.siriService.activate(voiceRecognitionText: "你好")
        app.activate()

        let settingsTab = app.tabBars.buttons["Settings"]
        XCTAssertTrue(settingsTab.waitForExistence(timeout: 10))
        settingsTab.tap()

        let intentOutcome = app.staticTexts["settings.lastIntentOutcome"]
        XCTAssertTrue(intentOutcome.waitForExistence(timeout: 20))

        let noRecord = "No Siri intent recorded"
        let predicate = NSPredicate(format: "label != %@", noRecord)
        expectation(for: predicate, evaluatedWith: intentOutcome)
        waitForExpectations(timeout: 20)

        XCTAssertFalse(intentOutcome.label.isEmpty)
    }

    func testSimulatorSiriCanOpenSafari() {
        let safari = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")
        XCUIDevice.shared.siriService.activate(voiceRecognitionText: "Open Safari")
        XCTAssertTrue(safari.wait(for: .runningForeground, timeout: 20))
    }
}
