# 构建报告 — 第 3 轮

## 完成的变更
- 为 `VoiceBridge` 增加了模拟器可用的 UI 自动化入口：
  - 启动时支持从 launch environment 注入 `baseURL` / `apiKey`
  - `ManualTestView` / `SettingsView` 增加稳定的 accessibility identifiers
  - 新增 `XcodeUITests/VoiceBridgeUITests.swift`
  - `project.yml` 新增 `VoiceBridgeUITests` target 并接入 scheme
- 保持 `BridgeCore` 和 Siri/App Intent 主路径不变，没有重新打开核心协议或后端实现范围

## 与上轮的差异
- 第 2 轮主要证明“app 能 build、能在 simulator 装起来”
- 第 3 轮进一步证明“app 在 simulator 里能通过 UI 自动化打到真实 `/chat` 并显示 reply”

## Git 提交
- 本轮待提交 checkpoint包含：
  - UI test launch seeding
  - accessibility identifiers
  - iOS UI test target 与测试文件
  - 最新 harness/progress 记录

## 自评
- 这一轮最大的价值是把验证从“源码和构建”推进到了“模拟器里的真实用户操作”
- 这让后续真机 Siri 验收只剩系统语音入口本身，不再混着手动页或后端链路的不确定性

## 已知限制
- UI smoke 覆盖的是 `Manual Test` 页，不是 Siri 语音入口
- 当前仍没有物理 iPhone destination
- `问纳博特 {prompt}` 仍然不是可注册的 App Shortcut phrase

## 运行方式
- `curl -X POST http://127.0.0.1:8900/chat ...`
- `cd ios/VoiceBridge && xcodegen generate`
- `cd ios/VoiceBridge && xcodebuild -project VoiceBridge.xcodeproj -scheme VoiceBridge -destination 'platform=iOS Simulator,name=iPhone 16' CODE_SIGNING_ALLOWED=NO test -only-testing:VoiceBridgeUITests`
- `bash init.sh`
