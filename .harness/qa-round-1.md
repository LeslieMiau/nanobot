# QA 报告 — 第 1 轮

## 总体判定
**通过**

相对于第 1 轮 `contract.md` 中约定的构建范围，本轮实现和验证已经达到通过标准。  
但相对于完整的 Voice Bridge v1 目标，仍然存在一个未解决的外部环境 gate：当前机器没有完整 Xcode / iOS SDK，因此还不能完成 iPhone Siri / App Intent 的真机运行时验收。

## 评分

| 维度 | 分数 (1-10) | 权重 | 理由 |
|------|------------|------|------|
| 架构清晰度 | 8 | 高 | `ios/VoiceBridge/` 已拆成 `AppShell`、`BridgeCore`、`Docs` 三层，且 `AppShell` 已回收为依赖 `BridgeCore` 的薄层，不再复制协议和 transport。 |
| 可迁移性 | 8 | 高 | `README`、架构文档和代码边界都强调了可拆仓目标；当前运行时耦合集中在 `POST /chat`。 |
| 工程完整性 | 7 | 中 | `BridgeCore` 已有 Swift Package、focused tests、history/config/runtime 等核心骨架；但还没有完整 Xcode project 或真机构建产物。 |
| 当前环境可验证性 | 8 | 高 | `swift test`、`swiftui/appintents import`、`AppShell` typecheck、`bash init.sh` 都已通过，足以证明当前机器上可验证的部分是通的。 |
| v1 目标完成度 | 5 | 高 | 真正的 iPhone Siri / App Intent 运行时闭环尚未完成，原因是本机缺少完整 Xcode / iOS SDK；这不是代码层面的直接失败，但会阻止整体验收。 |

**加权平均：7.2 / 10**

## 硬阈值检查
- [ ] 所有维度 ≥ 6：否
- [x] 加权平均 ≥ 7：是

## 发现的问题

### 严重（阻塞完整通过）
1. **完整 Xcode / iOS SDK 缺失，导致 iPhone Siri 真机验收无法执行** — 当前 `xcode-select -p` 指向 `/Library/Developer/CommandLineTools`，`xcodebuild -showsdks` 失败，`xcrun simctl list devices available` 失败，机器上也没有 `Xcode.app`。  
   - 修复建议：安装完整 Xcode，并将 `xcode-select` 指向对应的 `Xcode.app/Contents/Developer`，然后继续做 app build、设备部署、Siri/App Intent 真机验证。

### 一般（不阻塞本轮 contract）
1. **AppShell 目前只有静态 typecheck 证据，还没有真实 App target 构建证据** — 现在能证明 `SwiftUI`/`AppIntents` 可 import，且 `AppShell/*.swift` 能在 macOS SDK 下 typecheck，但这还不是完整 iOS app build。  
   - 修复建议：在完整 Xcode 环境补齐后，增加 Xcode project 或等价构建入口，并跑一次真实 app build。

## 测试操作记录
- `cd ios/VoiceBridge && swift test`
- `swift -e 'import Foundation; print("foundation-ok")'`
- `swift -e 'import SwiftUI; print("swiftui-ok")'`
- `swift -e 'import AppIntents; print("appintents-ok")'`
- `cd ios/VoiceBridge && swiftc -typecheck -parse-as-library -sdk "$(xcrun --show-sdk-path --sdk macosx)" -I .build/arm64-apple-macosx/debug/Modules AppShell/*.swift`
- `xcode-select -p`
- `xcodebuild -showsdks`
- `xcrun simctl list devices available`
- `bash init.sh`

## 给生成器的反馈
- 不要再重构 BridgeCore / AppShell 的边界，当前最重要的是保住现有的薄壳结构。
- 下一轮应聚焦环境段：完整 Xcode、iOS build、真机 Siri 验收，而不是继续增加新的桥接抽象。
- 在完整 Xcode 到位前，可以继续补文档或 build 入口，但不要把缺失的真机运行时证据包装成“已完成”。
