# Repository Instructions

- 在本仓库中，每次新增一个功能后，先完成对应测试并确认通过，再自动提交一次 commit。
- 在本仓库中，进行较大代码变更前，必须先输出并确认执行计划（plan），再开始编码。
- 在本仓库中，启动 `nanobot gateway` 前必须先确认当前机器仅有 0 或 1 个 gateway 进程；若发现多个实例，先停止多余实例后再启动，确保全程仅运行一个实例。

## Token Cost Guardrail

- 开始新任务前，先做一次轻量 token 风险预检；低风险和中风险任务直接继续，不要默认启用 `token-guard`。
- 只有在出现明显高风险 token 模式时，才升级使用 `token-guard`，尤其是：
  - 长会话后接新的复杂任务
  - 仓库级或多文件扫描
  - 多步工具循环
  - 大量 Bash、Web 或工具输出可能继续回流上下文
  - 提示词里反复携带冗长规则或背景
  - 暴露过多 MCP / 工具
  - 会话中途切换模型、thinking mode 或工具策略
  - 要求穷举式或超长输出
- 如果用户明确要求使用 `token-guard`，或发送以下控制命令，直接调用 `token-guard`：
  - `TokenGuard: on`
  - `TokenGuard: off`
  - `TokenGuard: strict`
  - `TokenGuard: relaxed`
  - `TokenBudget: <N>k`
- 如果预检结果为高风险或极高风险，先调用 `token-guard`，再决定是否继续原任务。
