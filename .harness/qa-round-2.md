# QA 报告 — 第 2 轮

## 总体判定
**通过当前轮次，但 Voice Bridge v1 仍未整体验收完成**

和第 1 轮相比，这一轮已经越过了“没有完整 Xcode”的环境 gate：app 工程可以生成，iOS simulator build 能通过，iOS-targeted XCTest 也能通过。  
当前剩余问题不再是“代码能不能 build”，而是：

1. 物理 iPhone Siri 语音验收还没有做
2. 产品规格里假设的 inline free-text Siri phrase，在真实 App Shortcuts metadata 规则下不可用

## 评分

| 维度 | 分数 (1-10) | 权重 | 理由 |
|------|------------|------|------|
| 架构清晰度 | 8 | 高 | `AppShell` / `BridgeCore` / `Docs` 的边界仍然清晰，新增 Xcode 工程没有把边界打乱。 |
| 可迁移性 | 8 | 高 | `project.yml`、`XcodeTests/` 和 `VoiceBridge.xcodeproj` 都留在 `ios/VoiceBridge/` 子树内，拆仓边界仍然稳定。 |
| 工程完整性 | 8 | 中 | 现在既有 Swift Package tests，也有真实 iOS simulator build/test 入口，工程完整性明显提升。 |
| 当前环境可验证性 | 9 | 高 | 完整 Xcode、simulator runtime、`xcodebuild build/test`、`swift test`、`bash init.sh` 都可运行。 |
| v1 目标完成度 | 5 | 高 | 当前正式 Siri 合同只剩 follow-up 路径，且缺少物理 iPhone Siri 语音验收；因此不能把 v1 说成已完成。 |

**加权平均：7.6 / 10**

## 硬阈值检查
- [ ] 所有维度 ≥ 6：否
- [x] 加权平均 ≥ 7：是

## 发现的问题

### 严重（阻塞完整通过）
1. **真实 iPhone Siri 语音验收仍缺失** — 当前 `xcrun xcdevice list` 只看到 simulator 和 `My Mac`，没有可部署的物理 iPhone destination。  
   - 修复建议：连接并信任一台 iPhone，完成 app 安装和 `嘿 Siri，问纳博特` 的真实语音回合验收。

2. **`问纳博特 {prompt}` 这种 free-form inline App Shortcut phrase 不能按原规格落地** — 真实 `ExtractAppIntentsMetadata` 校验拒绝了 `String` 参数插值，只允许 `AppEntity` / `AppEnum` 这类类型出现在 phrase 元数据里。  
   - 修复建议：把 v1 Siri 合同收敛到 follow-up phrase；若一定需要 one-shot inline 文本，需要另找 Apple 支持的参数化路径或重新定义参数类型。

### 一般（不阻塞当前轮次 build/test）
1. **当前 simulator 验证覆盖的是 build/test，不是 Siri 语音本身**  
   - 修复建议：保留当前 simulator 验证作为工程门槛，再补物理 iPhone Siri 语音验证作为最终验收。

## 测试操作记录
- `xcode-select -p`
- `xcodebuild -showsdks`
- `xcrun simctl list devices available`
- `xcrun xcdevice list`
- `cd ios/VoiceBridge && xcodegen generate`
- `cd ios/VoiceBridge && xcodebuild -project VoiceBridge.xcodeproj -scheme VoiceBridge -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build`
- `cd ios/VoiceBridge && xcodebuild -project VoiceBridge.xcodeproj -scheme VoiceBridge -destination 'platform=iOS Simulator,name=iPhone 16' CODE_SIGNING_ALLOWED=NO test`
- `cd ios/VoiceBridge && swift test`
- `bash init.sh`

## 给生成器的反馈
- 当前 priority 已经不再是“继续补静态 scaffold”，而是转向真实设备验收与产品合同收敛
- 不要再试图把自由 `String` inline phrase 硬塞进 App Shortcut metadata；这已经被真实 Xcode 构建证据否掉了
- 下一轮应该在物理 iPhone 到位后，围绕 `问纳博特` follow-up 路径做真机 Siri 验收，而不是再扩写文档或抽象
