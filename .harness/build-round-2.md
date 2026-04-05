# 构建报告 — 第 2 轮

## 完成的变更
- 把 Voice Bridge 从“可 typecheck 的 AppShell 源码”推进到了“可真实 iOS 构建的 app 工程”：
  - 新增 `ios/VoiceBridge/project.yml`
  - 生成并纳管 `ios/VoiceBridge/VoiceBridge.xcodeproj`
  - 新增 `ios/VoiceBridge/XcodeTests/VoiceBridgeAppTests.swift`
- 修复了真实 Xcode/iOS 构建暴露出的两个问题：
  - `AskBridgeIntent` 的静态描述属性改为 `static let`，通过 Swift 6 并发安全检查
  - `VoiceBridgeShortcuts` 改为只注册 `问\(.applicationName)`，移除非法的自由 `String` phrase 插值
- 把文档同步到当前真实能力：
  - `local-development.md` 现在记录完整 Xcode 与 simulator 验证路径
  - `siri-validation.md` 现在明确说明 v1 正式支持的是 follow-up Siri phrase，不再把 inline `String` phrase 写成已实现能力

## 与上轮的差异
- 第 1 轮只能证明 `BridgeCore` 和 `AppShell` 在当前环境内“可测试/可 typecheck”
- 第 2 轮已经证明：
  - 完整 Xcode 16.4 可用
  - iOS simulator runtime 可用
  - `VoiceBridge` app target 能真实 build
  - `VoiceBridgeTests` 能在 iPhone simulator 上真实执行

## Git 提交
- 上轮已存在的 checkpoint：
  - `d11359c` harness: initialize voice bridge v1 plan
  - `ed44073` feat(voice-bridge): scaffold app shell and docs
  - `eb023ed` feat(voice-bridge): add bridge core scaffold
  - `2f8eb72` docs(voice-bridge): align package architecture notes
  - `90cd221` fix(voice-bridge): typecheck app shell intents
- 当前待提交 checkpoint：
  - Xcode project generation path
  - iOS simulator build/test evidence
  - Siri phrase limitation documentation

## 自评
- 这一轮最大的增量不是“多写了文件”，而是把 Voice Bridge 从抽象设计推进到了真正经过 Apple build pipeline 的形态
- 同时也拿到了一个更硬的产品结论：free-form `String` 的 inline Siri phrase 不是我们实现漏了，而是当前 App Shortcuts metadata 本身不允许这样注册

## 已知限制
- 仍然没有物理 iPhone destination，因此 iPhone Siri 的语音级验收还没完成
- v1 当前只支持 `嘿 Siri，问纳博特` + follow-up 问句，不支持注册 `问纳博特 {prompt}` 这一类自由文本 App Shortcut phrase

## 运行方式
- `cd ios/VoiceBridge && xcodegen generate`
- `cd ios/VoiceBridge && xcodebuild -project VoiceBridge.xcodeproj -scheme VoiceBridge -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build`
- `cd ios/VoiceBridge && xcodebuild -project VoiceBridge.xcodeproj -scheme VoiceBridge -destination 'platform=iOS Simulator,name=iPhone 16' CODE_SIGNING_ALLOWED=NO test`
- `cd ios/VoiceBridge && swift test`
- `bash init.sh`
