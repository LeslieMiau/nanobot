---
name: weekly-review
description: Generate a structured weekly review from agent activity history, session logs, and cost data.
metadata: {"nanobot":{"emoji":"📋"}}
---

# Weekly Review Generator

Generate a structured weekly retrospective summarizing what happened during the past week.

## When to use (trigger phrases)

Use this skill when the user asks any of:
- "生成本周复盘" / "本周总结" / "weekly review"
- "这周做了什么" / "回顾一下这周"
- "generate weekly summary"
- "weekly report"

## How to generate

### Step 1: Collect data

Run the data collection script to extract structured info from the workspace:

```bash
python skills/weekly-review/scripts/collect_data.py --workspace . --days 7
```

Adjust `--days` if the user requests a different time range (e.g., "最近两周" → `--days 14`).

### Step 2: Generate the review

Parse the JSON output from Step 1 and generate a well-structured Markdown review with these sections:

```markdown
# 周复盘 YYYY-MM-DD ~ YYYY-MM-DD

## 📌 本周概要
<!-- 2-3 句话总结本周主要活动 -->

## ✅ 完成任务
<!-- 从 history_entries 中提取关键事项，按主题分组 -->
- ...

## 💬 关键对话
<!-- 从 session_stats 中识别最活跃的对话，简要描述内容 -->
- ...

## 📊 数据统计
- 活跃会话: X 个
- 消息总数: X 条
- 活跃渠道: Telegram, CLI, ...
- 常用工具: web_search (X次), exec (X次), ...
- API 调用: X 次，花费 $X.XX
  - 模型分布: claude-opus (X次), gpt-4o (X次), ...

## 🔮 下周建议
<!-- 根据本周活动模式，给出 2-3 条建议 -->
```

### Step 3: Save the review (optional)

If the user wants to save the review:

```bash
mkdir -p reviews
```

Write the review to `reviews/YYYY-WXX.md` (ISO week number).

## Scheduling via cron

To set up automatic weekly reviews (e.g., every Friday at 18:00):

```
cron(action="add", message="生成本周复盘并发送给我", cron_expr="0 18 * * 5", tz="Asia/Shanghai")
```

## Notes

- The data collection script reads from `memory/HISTORY.md`, `sessions/*.jsonl`, and `observability/cost_ledger.jsonl`
- If any data source is empty or missing, skip that section gracefully
- Keep the review concise — aim for readability, not exhaustiveness
- Use Chinese by default; switch to English if the user's message is in English
