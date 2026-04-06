# QA 报告 — 第 3 轮

## 总体判定
**通过当前轮次，且模拟器侧的手动链路已经足够扎实**

这一轮补齐了此前缺的“真正用户操作”证据：不是只看 build 或单测，而是让 XCTest 在 iPhone 模拟器里启动 app、切 tab、点按钮，并等待真实 `/chat` reply 出现。  
因此，当前剩余的不确定性已经进一步收敛到两件事：

1. 物理 iPhone Siri 语音触发
2. Apple 不支持的 free-form inline App Shortcut phrase

## 评分

| 维度 | 分数 (1-10) | 权重 | 理由 |
|------|------------|------|------|
| 架构清晰度 | 8 | 高 | 新增 UI test hooks 没有破坏 `AppShell` / `BridgeCore` 边界。 |
| 可迁移性 | 8 | 高 | UI test 和 launch seeding 仍然都位于 `ios/VoiceBridge/` 自含子树内。 |
| 工程完整性 | 9 | 中 | 现在同时具备 Swift Package tests、iOS simulator unit tests、以及 simulator UI smoke tests。 |
| 当前环境可验证性 | 9 | 高 | 当前机器已能覆盖构建、安装、启动、手动 UI 操作到真实 `/chat`。 |
| v1 目标完成度 | 6 | 高 | Siri 语音入口仍缺真机验证，但非语音链路已基本坐实。 |

**加权平均：8.0 / 10**

## 硬阈值检查
- [x] 所有维度 ≥ 6：是
- [x] 加权平均 ≥ 7：是

## 发现的问题

### 严重（阻塞最终完成）
1. **物理 iPhone Siri 验收仍缺失**  
   - 修复建议：连接到当前这台 Mac 的真机 iPhone，安装 app，并验证 `嘿 Siri，问纳博特` follow-up 流程。

2. **free-form inline App Shortcut phrase 仍不可用**  
   - 修复建议：继续将该问题视为平台限制，不要在代码里反复尝试规避；如要支持 one-shot inline 文本，需要改产品方案或等待不同的 Apple 支持路径。

### 一般（不阻塞当前轮次）
1. **UI smoke 依赖本地 nanobot `/chat` 服务已运行**  
   - 修复建议：保留当前真后端 smoke；若以后需要更稳定的 CI 版本，再单独增加 mock backend 模式，但不要替代现有 E2E smoke。

## 测试操作记录
- `curl -X POST http://127.0.0.1:8900/chat ...`
- `cd ios/VoiceBridge && xcodegen generate`
- `cd ios/VoiceBridge && xcodebuild -project VoiceBridge.xcodeproj -scheme VoiceBridge -destination 'platform=iOS Simulator,name=iPhone 16' CODE_SIGNING_ALLOWED=NO test -only-testing:VoiceBridgeUITests`
- `bash init.sh`

## 给生成器的反馈
- 当前模拟器 coverage 已经够用，不要再把时间花在“更多模拟器花活”上
- 下一轮如果继续，应该直接瞄准真机 Siri，而不是再增加一层新的测试脚手架
