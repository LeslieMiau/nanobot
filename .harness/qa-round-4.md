# QA 报告 — 第 4 轮

## 总体判定
**模拟器 Siri 的系统级触发是生效的，但它仍不能替代自定义 Voice Bridge Siri 入口的真机验收。**

这轮补的是一个之前没有分清的边界：`XCUISiriService` 能不能在模拟器里真正帮我们验证 `AskBridgeIntent`。  
现在有了清晰的对照结果：

1. 手动 `/chat` 链路继续通过
2. Siri 控制组 `Open Safari` 通过
3. Voice Bridge 支持短语 `问纳博特` -> `你好` 仍然没有执行到 app intent

因此，结论不是“模拟器 Siri 坏了”，而是“模拟器 Siri 只能证明 Siri 本身在工作，不能作为自定义 Voice Bridge 语音入口的验收替代品”。

## 评分

| 维度 | 分数 (1-10) | 权重 | 理由 |
|------|------------|------|------|
| 架构清晰度 | 8 | 高 | 新增 intent-result 探针没有破坏 `AppShell` / `BridgeCore` 边界。 |
| 可迁移性 | 8 | 高 | 所有探针与 UI tests 仍在 `ios/VoiceBridge/` 自含子树内。 |
| 工程完整性 | 9 | 中 | 现在既有手动 smoke，也有 Siri 控制组和 custom intent 探针。 |
| 当前环境可验证性 | 9 | 高 | 已经明确证明 simulator Siri 的边界，而不是停留在猜测。 |
| v1 目标完成度 | 6 | 高 | 物理 iPhone Siri 验收仍缺失。 |

**加权平均：8.0 / 10**

## 硬阈值检查
- [x] 所有维度 ≥ 6：是
- [x] 加权平均 ≥ 7：是

## 发现的问题

### 严重（阻塞最终完成）
1. **模拟器 Siri 不足以验证自定义 Voice Bridge Siri 调用**  
   - 证据：`Open Safari` 通过，但 `问纳博特` -> `你好` 没有写入 intent-result probe。  
   - 修复建议：不要再把模拟器 Siri 当作 v1 终验路径，下一步应转回物理 iPhone Siri。

2. **物理 iPhone Siri 验收仍缺失**  
   - 修复建议：在能连接 iPhone 的那台 Mac 上运行 `VoiceBridge`，验证 `嘿 Siri，问纳博特` 的 follow-up 流程。

### 一般（不阻塞当前轮次）
1. **当前 Siri 探针依赖一个调试可见的 intent-result 存储点**  
   - 修复建议：保留这个探针作为开发/QA 设施；如果以后要收紧用户界面，可把它隐藏到 debug-only 页签，但不要删掉验证能力。

## 测试操作记录
- `bash ~/.codex/scripts/global-init.sh`
- `bash init.sh`
- `cd ios/VoiceBridge && swift test`
- `cd ios/VoiceBridge && xcodebuild -project VoiceBridge.xcodeproj -scheme VoiceBridge -destination 'platform=iOS Simulator,name=iPhone 16' -derivedDataPath /tmp/voicebridge-deriveddata-siri-probe CODE_SIGNING_ALLOWED=NO test -only-testing:VoiceBridgeUITests`

## 给生成器的反馈
- 现在不要再试图把“模拟器 Siri 成功”包装成“自定义 Voice Bridge Siri 已验证”
- 当前模拟器 coverage 已经够硬，下一步应该回到真机 iPhone Siri，而不是继续往模拟器里堆更多 Siri 花活
