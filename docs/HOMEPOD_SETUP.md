# HomePod Mini 语音控制 Nanobot

通过 HomePod Mini 与 Nanobot 进行多轮语音对话。

## 架构

```
HomePod → Siri → iPhone 快捷指令 → HTTP POST /v1/voice/ask → Nanobot
                                  ← {"reply": "...", "end_conversation": false}
                                  → Speak Text → HomePod 播放
                                  → 循环：继续对话直到 end_conversation=true
```

## 第一步：启动 API 服务

### 1.1 编辑 `~/.nanobot/config.json`

```json
{
  "api": {
    "host": "0.0.0.0",
    "port": 8900,
    "apiKey": "你的密钥"
  }
}
```

### 1.2 启动

```bash
# 前台运行
nanobot serve -v

# 或后台运行（推荐）
tmux new-session -d -s nanobot-api '.venv/bin/nanobot serve -v'
```

### 1.3 验证

```bash
curl http://192.168.x.x:8900/health
# → {"status": "ok"}

curl -X POST http://192.168.x.x:8900/v1/voice/ask \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 你的密钥" \
  -d '{"text": "你好", "speaker": "test"}'
# → {"reply": "...", "end_conversation": false}
```

如果你想按固定节点逐段排查，仓库里也提供了自动诊断脚本：

```bash
python3 scripts/verify_homepod_e2e.py
```

它会自动验证：
- API 监听与 `/health`
- `/v1/voice/ask` 返回 `reply`
- `shortcuts run '测试助手'` 是否真正打到服务端
- 当前库中的 `测试助手` / `纳博特` 是否还是预期动作数

设备侧排查时，可以单独开一个日志观察窗口：

```bash
python3 scripts/verify_homepod_e2e.py watch --speaker homepod
```

## 第二步：导入快捷指令

推荐直接使用仓库里已经生成好的快捷指令文件：

- [测试助手](../测试助手.shortcut)：先验证 API 是否可达
- [纳博特](../纳博特.shortcut)：日常对话入口，推荐绑定 Siri
- 如果你更想自己搭动作，继续阅读下面的手工步骤

建议顺序：

1. 在 iPhone 上打开仓库页面，先导入 [测试助手](../测试助手.shortcut)
2. 运行一次，确认会先弹出 reply 文本并朗读返回结果
3. 删除或重命名旧的交互快捷指令，例如 `问机器人`、`嘿助手`
4. 再导入 [纳博特](../纳博特.shortcut)
5. 对 HomePod 说：`嘿 Siri, 运行纳博特`

如果你想完全手工搭建，继续看下面的动作拆解。

## 第三步：在 iPhone 上手工创建快捷指令

> 必须在 **iPhone** 上创建，不是 Mac。HomePod 通过 iPhone 运行快捷指令。

打开「快捷指令」App → 右上角 `+` → 按以下步骤添加动作：

### 动作 1：文本

搜索「文本」，添加「文本」动作。内容填写你的 API 地址：

```
http://192.168.x.x:8900
```

长按这个动作 → 「重新命名」→ 改名为 `服务器地址`

### 动作 2：要求输入

搜索「要求输入」，添加。设置：
- 提示语：`你想问什么？`
- 输入类型：`文本`

### 动作 3：获取 URL 内容

搜索「获取 URL 内容」，添加。设置：

- URL 栏：点击输入框 → 选择变量 `服务器地址` → 然后手动追加 `/v1/voice/ask`
  - 最终显示为：`[服务器地址]/v1/voice/ask`
- 点击「显示更多」：
  - 方法：`POST`
  - 头部：添加 2 个
    - `Content-Type` → `application/json`
    - `Authorization` → `Bearer 你的密钥`
  - 请求体：`JSON`
    - 添加字段 `text`（文本）→ 值选择变量 `要求输入的结果`
    - 添加字段 `speaker`（文本）→ 值填 `homepod`

### 动作 4：获取字典值

搜索「从字典中获取值」，添加。设置：
- 键：`reply`

### 动作 5：朗读文本

搜索「朗读文本」，添加。
- 勾选「等待完成」

### 保存

- 快捷指令名称：`纳博特`（使用像专有名词的名字，避免 `嘿...`、`问...`、`助手`、`机器人` 这类高冲突词）
- 点完成

### 测试

直接点击运行按钮测试。输入"你好"，应该先看到 reply 弹窗，再听到 Nanobot 的回答被朗读出来。

## 第四步：绑定 HomePod

### 4.1 启用 Personal Content

在 iPhone 上：
1. 打开「家庭」App
2. 点右上角 `...` → 「家庭设置」
3. 找到你的用户 → 点击进入
4. 启用「个人请求」/ Personal Requests
5. 选择你的 iPhone 作为设备

### 4.2 对 HomePod 说

```
"嘿 Siri, 运行纳博特"
```

Siri 会问「你想问什么？」，说出你的问题，等待回答。

## 进阶：多轮对话版本

如果你想支持多轮对话（不需要每次重新喊 Siri），在上面的基础上修改：

1. 在「朗读文本」后面添加「获取字典值」→ 键 `end_conversation`（从步骤 3 的结果获取）
2. 添加「如果」→ 条件：`end_conversation` 等于 `1`
   - 是：添加「什么也不做」
   - 否：回到步骤 2（要求输入），用「重复」动作包裹步骤 2-5
3. 用「重复」动作包裹，重复 20 次（防止无限循环）

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| Siri 自己回答了 | 删除或重命名旧条目，只保留 `纳博特`，并说："嘿 Siri, **运行**纳博特" |
| 快捷指令没反应 | 先在 iPhone 上手动运行测试，确认是否弹出 reply 文本；如果 API 已收到请求但没有语音，多半是系统音量/朗读设置问题 |
| 网络请求失败 | 确认 iPhone 和服务器在同一局域网，无 AP 隔离 |
| HomePod 不触发 | 检查「家庭」App → 个人请求是否已开启 |
| 401 错误 | 检查 Authorization header 中的 API key |
| 超时 | 增大 `api.timeout` 配置，默认 120 秒 |

## API 参考

### POST /v1/voice/ask

请求：
```json
{"text": "你的问题", "speaker": "homepod"}
```

响应：
```json
{"reply": "纯文本回答", "end_conversation": false}
```

### POST /v1/audio/speech

请求：
```json
{"input": "要转语音的文本", "voice": "alloy", "model": "tts-1"}
```

响应：`audio/mpeg` 字节流

### GET /health

响应：`{"status": "ok"}`（无需鉴权）
