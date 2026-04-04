# HomePod Mini 语音控制 Nanobot

通过 HomePod Mini 与 Nanobot 进行语音对话：用 Siri 提问，听 Nanobot 回答。

## 架构概览

```
语音输入: HomePod → Siri → Apple Shortcut → HTTP POST /v1/voice/ask → Nanobot → 返回文本
语音输出（基础）: Shortcut "Speak Text" → Siri 朗读回答
语音输出（增强）: Nanobot → HomePod Channel → TTS → AirPlay → HomePod 播放
```

## 前提条件

- Nanobot 运行在与 HomePod Mini **同一局域网** 内
- iPhone/iPad 已配对 HomePod Mini
- Nanobot 已安装 `aiohttp`：`pip install 'nanobot-ai[api]'`

## Phase 1: API 配置

### 1.1 编辑 config.json

```json
{
  "api": {
    "host": "0.0.0.0",
    "port": 8900,
    "apiKey": "your-secret-key-here",
    "tts": {
      "provider": "openai",
      "voice": "alloy",
      "model": "tts-1"
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `host` | 设为 `0.0.0.0` 以允许局域网访问 |
| `apiKey` | Bearer token 鉴权，**强烈建议** 在绑定 `0.0.0.0` 时设置 |
| `tts.provider` | `openai` 或 `groq`，TTS API key 自动从对应 LLM provider 继承 |
| `tts.voice` | OpenAI 语音：alloy, echo, fable, onyx, nova, shimmer |

### 1.2 启动 API 服务

```bash
nanobot api --host 0.0.0.0 --port 8900
```

### 1.3 验证

```bash
# 测试鉴权
curl http://192.168.x.x:8900/health

# 测试语音问答（替换 IP 和 key）
curl -X POST http://192.168.x.x:8900/v1/voice/ask \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-key-here" \
  -d '{"text": "今天天气怎么样？", "session_id": "homepod"}'

# 测试 TTS
curl -X POST http://192.168.x.x:8900/v1/audio/speech \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-key-here" \
  -d '{"input": "你好，我是 Nanobot"}' \
  --output test.mp3
```

## Phase 2: 创建 Siri Shortcut

在 iPhone 上打开 **Shortcuts** 应用，创建新 Shortcut：

### 基础版：Siri 朗读回答

1. **Shortcut 名称**: `Ask Nanobot`（这也是 Siri 触发短语）
2. 添加动作 **Dictate Text** — 录入用户的问题
3. 添加动作 **Get Contents of URL**:
   - URL: `http://192.168.x.x:8900/v1/voice/ask`
   - Method: `POST`
   - Headers:
     - `Content-Type`: `application/json`
     - `Authorization`: `Bearer your-secret-key-here`
   - Request Body (JSON):
     ```json
     {"text": "Dictated Text", "session_id": "homepod"}
     ```
     （将 `Dictated Text` 替换为上一步的变量）
4. 添加动作 **Get Dictionary Value**: Key = `text`
5. 添加动作 **Speak Text** — 朗读返回的文本

### 高级版：高质量 TTS 语音

将步骤 4-5 替换为：

4. 添加动作 **Get Dictionary Value**: Key = `text`
5. 添加动作 **Get Contents of URL** (POST to `/v1/audio/speech`):
   - Body: `{"input": "Dictionary Value"}`
6. 添加动作 **Play Sound** — 播放返回的音频

### 使用方式

对 HomePod 说：

> "Hey Siri, Ask Nanobot"

Siri 会让你说出问题，然后朗读 Nanobot 的回答。

### 多轮对话

Shortcut 中的 `session_id: "homepod"` 保持会话上下文。同一个 session_id 的请求共享对话历史。

## Phase 3: AirPlay 主动推送（可选）

让 Nanobot **主动** 通过 HomePod 播放语音（如定时播报、通知）。

### 3.1 安装依赖

```bash
pip install 'nanobot-ai[homepod]'
```

### 3.2 配置 HomePod Channel

在 `config.json` 中添加：

```json
{
  "channels": {
    "homepod": {
      "enabled": true,
      "deviceName": "客厅 HomePod",
      "ttsProvider": "openai",
      "ttsVoice": "nova",
      "ttsModel": "tts-1",
      "allowFrom": ["*"]
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `deviceName` | HomePod 在 Home app 中显示的名称。留空则自动选择第一个设备 |
| `ttsProvider` | `openai` 或 `groq` |
| `ttsVoice` | TTS 语音名称 |

### 3.3 使用场景

启用 HomePod channel 后，以下功能的输出可以通过 HomePod 播放：

- **Cron 定时任务**：如每早 8:00 播报天气和日程
- **Agent 主动通知**：任务完成、异常告警等
- **其他 channel 转发**：将特定消息路由到 HomePod

### 3.4 首次配对

首次连接 HomePod 时，pyatv 可能需要配对。运行 `nanobot gateway` 后查看日志获取配对指引。

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| Shortcut 超时 | 增大 `api.timeout`；检查 LLM provider 连通性 |
| 401 Unauthorized | 检查 Shortcut 中的 `Authorization` header 是否正确 |
| 找不到 HomePod | 确保同一局域网，无 AP 隔离；尝试重启 HomePod |
| TTS 无声 | 检查 TTS provider API key；用 `/v1/audio/speech` 手动测试 |
| 回答过长 Siri 念不完 | 改用高级版 TTS 方案或在 agent prompt 中限制回答长度 |

## API 端点参考

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/voice/ask` | POST | 语音问答，返回纯文本 `{"text": "..."}` |
| `/v1/audio/speech` | POST | 文本转语音，返回 audio/mpeg |
| `/v1/chat/completions` | POST | OpenAI 兼容完整 API |
| `/v1/models` | GET | 可用模型列表 |
| `/health` | GET | 健康检查（无需鉴权） |
