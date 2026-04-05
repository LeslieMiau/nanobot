# 冲刺合约 — 第 1 轮

## 构建范围
本轮将实现的功能列表：
- 功能 #1: 仓库基线保持绿灯并可重复验证
- 功能 #3: `.harness/` 工作区与状态文件初始化
- 功能 #6: 明确记录 Xcode / iOS SDK 环境 gate
- 功能 #7: 建立自含的 `ios/VoiceBridge/` 子树骨架
- 功能 #11-18: 建立 BridgeCore 的核心协议类型与 nanobot backend 骨架
- 功能 #49-50: 为桥接层请求/响应与错误映射建立 focused tests

## 成功标准
### 功能 #1: 基线绿灯
- [ ] `bash init.sh` 在本轮代码改动后依然通过
- [ ] 本轮新增或修正的 focused tests 可以重复运行
- [ ] `PROGRESS.md` 记录本轮基线验证结果

### 功能 #3: Harness 工作区
- [ ] `.harness/spec.md`、`.harness/contract.md`、`.harness/status.json` 已存在并反映当前任务
- [ ] `.gitignore` 已忽略 `.harness/`
- [ ] 后续 round 可以直接复用这些文件继续推进

### 功能 #6: 环境 gate
- [ ] 当前机器的 Xcode / SDK 缺失状态已写入 `PROGRESS.md` 和 `.harness/status.json`
- [ ] 文档不会把 Xcode 缺失误报成代码故障

### 功能 #7: 自含子树
- [ ] `ios/VoiceBridge/` 已建立自含目录结构
- [ ] 该子树不依赖 Python runtime 文件
- [ ] 子树内含迁移说明或边界说明

### 功能 #11-18: BridgeCore 协议与 nanobot backend
- [ ] 已有 `BackendKind`、`SourcePlatform`、`SourceDeviceType`、`BridgeRequest`、`BridgeResponse`、`BridgeConfig`
- [ ] 已有统一的 backend protocol 和 `NanobotBackend` 骨架
- [ ] `/chat` 请求和响应映射已经可以被测试验证

### 功能 #49-50: Focused tests
- [ ] 至少覆盖 `/chat` 编码、`reply/end_conversation` 解码、错误映射或长回复策略中的核心路径
- [ ] 当前环境下可运行的 Swift 或 focused tests 已执行并记录

## 验证方式
- 运行 `bash init.sh`
- 运行 focused Python tests 保持仓库基线
- 运行当前环境可用的 Swift/bridge tests；若受限于缺少完整 Xcode，则至少验证 Swift Package 或可执行的 bridge-core 测试路径
- 通过代码结构检查 `ios/VoiceBridge/` 是否仍自含

## 评估器确认
- [x] 范围合理，本轮可完成
- [x] 成功标准可测试、无歧义
- [x] 验证方式在当前工具条件下可行

评估器备注：本轮优先建立可迁移骨架和可测试的桥接核心，不把完整 iOS 真机构建当作隐性已完成项；如无完整 Xcode，必须显式记录为环境 gate。
