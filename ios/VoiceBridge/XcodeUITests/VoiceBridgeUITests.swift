import XCTest

@MainActor
final class VoiceBridgeUITests: XCTestCase {
    private let apiKey = "nb-3b7d4b91132c9bb850c2646f92860dc8"
    private let defaultBaseURL = "http://127.0.0.1:8900"

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func allowSystemAlertsIfPresent() {
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let alert = springboard.alerts.firstMatch
        guard alert.waitForExistence(timeout: 1) else { return }

        for label in ["允许", "Allow", "好", "OK"] {
            let button = alert.buttons[label]
            if button.exists {
                button.tap()
                return
            }
        }
    }

    private var configuredBaseURL: String {
        if let value = ProcessInfo.processInfo.environment["VOICEBRIDGE_TEST_BASE_URL"], !value.isEmpty {
            return value
        }
        if
            let value = Bundle(for: Self.self).object(forInfoDictionaryKey: "VOICEBRIDGE_TEST_BASE_URL") as? String,
            !value.isEmpty,
            !value.contains("$(")
        {
            return value
        }
        return defaultBaseURL
    }

    func testManualSmokeFlowDisplaysBackendReply() {
        let app = XCUIApplication()
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_MODE"] = "1"
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_RESET_CONFIG"] = "1"
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_RESET_INTENT_RESULT"] = "1"
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_BASE_URL"] = configuredBaseURL
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_API_KEY"] = apiKey
        app.launch()

        let testTab = app.tabBars.buttons["Test"]
        XCTAssertTrue(testTab.waitForExistence(timeout: 10))
        testTab.tap()

        let sendButton = app.buttons["manual.sendButton"]
        XCTAssertTrue(sendButton.waitForExistence(timeout: 10))
        sendButton.tap()
        allowSystemAlertsIfPresent()

        let latestReply = app.staticTexts["manual.latestReply"]
        guard latestReply.waitForExistence(timeout: 20) else {
            let statusText = app.staticTexts["manual.statusText"]
            let latestError = app.staticTexts["manual.latestError"]
            let statusValue = statusText.waitForExistence(timeout: 1) ? statusText.label : "<missing>"
            let errorValue = latestError.waitForExistence(timeout: 1) ? latestError.label : "<missing>"
            XCTFail(
                """
                manual.latestReply did not appear on device
                baseURL=\(configuredBaseURL)
                statusText=\(statusValue)
                latestError=\(errorValue)
                """
            )
            return
        }

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
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_BASE_URL"] = configuredBaseURL
        app.launchEnvironment["VOICEBRIDGE_UI_TEST_API_KEY"] = apiKey
        app.launch()
        sleep(5)
        XCUIDevice.shared.press(.home)

        XCUIDevice.shared.siriService.activate(voiceRecognitionText: "使用纳博特")
        sleep(3)
        XCUIDevice.shared.siriService.activate(voiceRecognitionText: "你好")
        sleep(5)
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
