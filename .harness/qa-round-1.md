# QA 报告 — 第 1 轮

## 总体判定
**通过**

## 评分

| 维度 | 分数 | 权重 | 理由 |
|------|------|------|------|
| 故障检测准确性 | 7 | 高 | 已能识别 `getUpdates` 在 in-flight 状态下的长期停滞，并把轮询状态暴露出来；但健康判定仍只围绕“请求正在进行多久”展开，没有把“最近一次完成后是否持续推进”作为独立门槛。 |
| 恢复可靠性 | 7 | 高 | `poll-stalled` 能走进现有重启链路，且通道层测试覆盖了重启路径；但本轮没有在真实 stalled 链路上证明恢复成功。 |
| 误重启控制 | 7 | 中 | 90s stall 阈值和 restart lock 降低了抖动误报风险；但 stall 分支跳过了 probe-before-restart，恢复决策仍偏激进。 |
| 日志与状态可观测性 | 8 | 中 | 新增的 `TG Poll` 状态、开始/完成时间、inflight 标记和错误摘要，足以让 CLI/日志解释当前轮询是否在推进。 |
| 当前环境可验证性 | 7 | 中 | 单测与 tmux 真实 gateway smoke 都跑通了，但 smoke 只证明健康空返回持续推进，没有在本机真实链路里构造并验证 stall 恢复。 |

**加权平均：7.1 / 10**

## 硬阈值检查
- [x] 所有维度 ≥ 6：是
- [x] 加权平均 ≥ 7：是

## 发现的问题

### 一般
1. **[P2] Stall 判定只覆盖 in-flight 请求超时，未把“完成后长期无新进展”纳入健康门槛** — [`nanobot/channels/telegram.py`]( /Users/miau/Documents/nanobot/nanobot/channels/telegram.py ) 里虽然记录了 `last_poll_completed_at`，但 watchdog 只看 `_poll_inflight_started_monotonic`，见 [`telegram.py`]( /Users/miau/Documents/nanobot/nanobot/channels/telegram.py ) 的 `getUpdates` 进度记录与 `_get_poll_stall_reason`。如果轮询曾成功完成一次，但后续迟迟没有发起下一轮请求，当前逻辑仍可能把它视为健康。修复建议是把“距离上次完成的静默时长”也纳入 stall 判定，或至少在 `poll_request_inflight == false` 且完成时间过久时切到可疑状态。
1. **[P2] 真实 smoke 没有覆盖 `poll-stalled` 恢复分支** — [`build-round-1.md`]( /Users/miau/Documents/nanobot/.harness/build-round-1.md ) 证明了空闲但持续推进的健康态，但没有在真实 `nanobot:1.0` gateway 上诱发一次 stall 再验证恢复结果。`tests/channels/test_telegram_channel.py` 里的 stall 覆盖仍是合成单测，不是目标运行态的端到端证据。建议补一个可控故障注入 smoke，至少在本机链路上把恢复成功或失败跑出来一次。

## 测试操作记录

- `.venv/bin/pytest tests/channels/test_telegram_channel.py -q` -> `58 passed`
- `.venv/bin/pytest tests/cli/test_restart_command.py -q` -> `12 passed`
- 现有 `nanobot:1.0` tmux pane 原地重启 gateway 后，真实日志连续出现 `getUpdates` 完成返回 `[]` 并立即发起下一轮请求，证明健康空闲轮询没有被误判为故障。
- 停机阶段观察到一次 PTB `telegram.error.TimedOut: Pool timeout: All connections in the connection pool are occupied`，这与本次问题域一致，但本轮没有把它转成受控的 stall 注入验证。

## 给生成器的反馈

- 把 `last_poll_completed_at` 也纳入 watchdog 的健康判定，不要只靠 in-flight 请求年龄。
- 补一个真实链路的 stall 注入/恢复 smoke，确保 `poll-stalled` 不是只在单测里成立。
- 如果恢复失败路径难以在真实环境中稳定构造，至少加一个针对 `poll-stalled` 的失败分支单测，覆盖 `_restart_application` 抛错后的升级行为。
