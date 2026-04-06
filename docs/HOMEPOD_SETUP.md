# HomePod Mini 语音控制 Nanobot

本轮正式交付的是 HomePod 实用链路：

- 先说一次 `嘿 Siri，运行纳博特`
- 进入快捷指令后连续多轮聊天
- 直到你明确结束前，不需要每句重新唤起

当前验收目标不是“一句话直达”。也就是说，`嘿 Siri，纳博特你好` 这种 iPhone Siri App Intent 路线不在本轮交付范围内。

## 当前架构

```text
HomePod -> Siri -> iPhone 快捷指令 -> POST /chat -> Nanobot
                                       <- {"reply": "...", "end_conversation": false}
                                       -> Speak Text
                                       -> 继续下一轮 Dictate Text
```

关键点：

- `测试助手.shortcut` 仍然是单轮诊断入口
- `纳博特.shortcut` 现在会在启动时生成一个本次运行专用的 `session_id`
- 这次运行里的每一轮都会复用同一个 `session_id`
- 重新唤起 `纳博特` 时会生成新的 `session_id`，不会串到上一次上下文

## 当前交付边界

- 已交付：`嘿 Siri，运行纳博特` 后连续对话
- 未承诺：一句话直达触发 Nanobot
- 已保留：旧的 `{"text":"...","speaker":"..."}` 客户端仍可继续使用

## 第一步：启动 API 服务

编辑 `~/.nanobot/config.json`：

```json
{
  "api": {
    "host": "0.0.0.0",
    "port": 8900,
    "apiKey": "你的密钥"
  }
}
```

启动：

```bash
nanobot serve -v
```

基础验证：

```bash
curl http://192.168.x.x:8900/health
# -> {"status": "ok"}

curl -X POST http://192.168.x.x:8900/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 你的密钥" \
  -d '{"text":"你好","speaker":"homepod"}'
# -> {"reply":"...","end_conversation":false}
```

如果你想直接跑仓库自带诊断：

```bash
python3 scripts/verify_homepod_e2e.py
```

## 第二步：导入快捷指令

推荐直接导入仓库中的成品：

- [测试助手](../测试助手.shortcut)：单轮连通性诊断
- [纳博特](../纳博特.shortcut)：连续对话入口

建议顺序：

1. 先导入 [测试助手](../测试助手.shortcut)
2. 手动运行一次，确认会弹出 reply 文本并朗读
3. 再导入 [纳博特](../纳博特.shortcut)
4. 对 HomePod 说：`嘿 Siri，运行纳博特`

## 第三步：实际使用

### 3.1 开始对话

对 HomePod 说：

```text
嘿 Siri, 运行纳博特
```

进入快捷指令后，系统会进入一轮 `Dictate Text -> POST /chat -> Speak Text` 的循环。

这就是本轮交付的“唤起一次后连续聊”。

### 3.2 连续追问

第一次回复播报完成后，直接继续说下一句即可。

不需要再次说：

```text
嘿 Siri，运行纳博特
```

### 3.3 结束对话

以下任一情况都会结束当前循环：

- 你说了本地退出词，例如：`结束`、`退出`、`再见`
- 你在 Dictate Text 步骤里取消输入
- 你没有提供有效输入
- 服务端返回 `end_conversation=true`

### 3.4 开始新会话

再次说一次：

```text
嘿 Siri，运行纳博特
```

新的一次运行会生成新的 `session_id`，因此会自然隔离上一轮上下文，不需要额外清理接口。

## 第四步：手动排查

如果 HomePod 端效果异常，先按下面顺序排查：

1. 运行 [测试助手](../测试助手.shortcut) 看单轮请求是否正常
2. 确认 `纳博特.shortcut` 是最新导入版本
3. 确认 iPhone 与服务端在同一局域网
4. 确认 HomePod 的“个人请求”已开启

观察服务端日志：

```bash
python3 scripts/verify_homepod_e2e.py watch --speaker homepod
```

## 常见问题

| 问题 | 处理方式 |
|------|----------|
| Siri 自己回答了 | 说完整命令：`嘿 Siri，运行纳博特`，不要把 Nanobot 问题直接说在唤起句里 |
| 只能单轮 | 删除旧版 `纳博特` 后重新导入当前 `纳博特.shortcut` |
| 没法退出 | 试 `结束`、`退出`、`再见`，或者直接取消 Dictate Text |
| 新一轮串了旧上下文 | 重新完整唤起一次 `纳博特`，确认不是在上一轮循环里继续追问 |
| 网络失败 | 先用 [测试助手](../测试助手.shortcut) 和 `curl /chat` 验证局域网访问 |

## API 参考

### POST /chat

兼容旧请求：

```json
{"text":"你的问题","speaker":"homepod"}
```

本轮新增的多轮请求：

```json
{"text":"你的问题","speaker":"homepod","session_id":"20260406183000123"}
```

路由规则：

- 优先使用 `session_id` 作为当前快捷指令运行内的上下文键
- 如果没有 `session_id`，回退到 `speaker`
- `speaker` 继续保留给旧快捷指令和日志定位

响应：

```json
{"reply":"纯文本回答","end_conversation":false}
```

### POST /v1/voice/ask

兼容旧入口，也支持可选 `session_id`：

```json
{"text":"你的问题","speaker":"homepod","session_id":"20260406183000123"}
```

### GET /health

响应：

```json
{"status":"ok"}
```
