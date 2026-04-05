# Voice Bridge v1

## 愿景
把 `nanobot` 演进为一个可扩展的语音入口层：先让 `iPhone Siri` 稳定地把一句话转成文本，经由统一的 `Voice Bridge` 路由到 `nanobot /chat`，再把回复播报给用户；同时从一开始就把架构设计成可迁移到独立新仓，并可扩展到 `HomePod`、`小爱同学`、`天猫精灵`、手机、音箱和车机等未来入口。

## 功能列表
1. **iPhone Siri 文本入口** — 通过 `App Intent` 支持 `嘿 Siri，问纳博特` 和 `嘿 Siri，问纳博特 你好` 两种调用方式。
   - 验收：缺少参数时 Siri 会追问 `你想问纳博特什么？`，提供文本后会播报 nanobot 返回内容，而不是只说“完成”。
   - 实施发现：真实 Xcode `App Shortcuts` metadata 校验不接受自由 `String` 参数的 inline phrase，因此当前可交付的 v1 合同先收敛为 `嘿 Siri，问纳博特` + follow-up 收集；`嘿 Siri，问纳博特 你好` 仍作为后续探索项保留。
2. **Bridge 到 nanobot `/chat` 的统一转发** — 所有 v1 Siri 请求都经由统一 Bridge Core 规范化后再调用 `POST /chat`。
   - 验收：桥接层始终发送 `{"text":"<prompt>","speaker":"siri-iphone"}`，并正确解析 `reply` 与 `end_conversation`。
3. **App 内手动调试面板** — 提供最小 SwiftUI 界面配置 `baseURL` / `apiKey`、发送手动 prompt、查看最近回复。
   - 验收：无需 Siri 也能完成一次 `你好` 的 `/chat` 调用，并在 UI 中看到回复或错误。
4. **未来入口与后端的架构预留** — 明确保留 `HomePod`、`小爱同学`、`天猫精灵`、车机等 ingress 以及 `openclaw` 等 backend 的扩展位。
   - 验收：Bridge Core 类型和文档能清楚表达这些预留位，但不伪装成 v1 已经实现。

## 技术栈
- iOS 客户端：SwiftUI
- Siri 入口：App Intents / App Shortcuts
- Bridge Core：Swift 原生类型与 URLSession 网络层
- 测试：XCTest（以及当前可用的 Swift Package / focused bridge tests）
- 后端契约：现有 `nanobot /chat` HTTP API

## 架构
### 三层结构
- `Ingress adapters`
  - v1 只实现 `iPhone Siri`
  - 未来预留 `HomePod`、`小爱同学`、`天猫精灵`、手机/音箱、车机等入口
- `Voice Bridge core`
  - 统一处理配置、请求建模、会话、错误映射、回复格式化与后端路由
- `Backends`
  - v1 只启用 `nanobot`
  - `openclaw` 和其他后端只保留扩展接口

### 统一内部协议
- 统一采用文本回合协议，不把原始音频作为桥接层标准输入
- 最小协议对象：
  - `BridgeRequest`
    - `backend`
    - `speaker`
    - `sessionId`
    - `prompt`
    - `sourcePlatform`
    - `sourceDeviceType`
  - `BridgeResponse`
    - `reply`
    - `endConversation`
    - `displayText`
    - `spokenText`

### 可拆仓边界
- 所有 iOS 代码、文档、测试都放在 `ios/VoiceBridge/` 自含子树内
- 该子树不得直接依赖 `nanobot` Python 代码、仓库根脚本或相对路径资源
- 与主仓库的唯一运行时耦合是公开 HTTP API：`POST /chat`

## 评估标准
- 功能性（高）：`iPhone Siri -> App Intent -> Bridge -> /chat -> Siri 播报` 是否真正跑通
- 可迁移性（高）：`ios/VoiceBridge/` 是否能整体迁移到独立新仓
- 可扩展性（高）：未来新增 ingress/backend 是否只需适配层增量而非重写核心协议
- 稳定性（中）：超时、401、无网络、长回复、无效 JSON 是否都能给出可播报错误
- 可测试性（中）：是否同时具备手动 app 验证、Siri 验证和 focused bridge tests

## 约束
- v1 的正式成功标准只覆盖 `iPhone Siri`，不覆盖 `HomePod`
- v1 只启用 `nanobot /chat`
- 当前机器缺少完整 Xcode / iOS SDK，因此真机构建和 Siri 运行时验收是环境 gate
- 当前桥接层坚持文本协议优先，不把音频流作为 v1 标准接口

## 完成定义
- `iPhone Siri` 至少有一条成功语音路径
- Bridge Core 能稳定直连 `nanobot /chat`
- app 内手动测试可用
- `ios/VoiceBridge/` 自含且具备未来拆仓说明
- 相关测试与验收步骤可以重复执行并留有记录
