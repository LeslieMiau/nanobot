---
name: ai-news-digest
description: Curate high-signal AI Builder intelligence for programmers and AI product builders. Use when users want daily must-know builder signals, weekly deep reads/listens, workflow-impact analysis, noise filtering, or actionable experiments for AI coding and agentic product development.
---

# AI Builder Signal Radar

Use this skill when the user wants a high-signal digest for AI builders, not generic AI news.

The skill only answers 4 question types:
1. 今天有哪些真正值得看的 AI builder 信号
2. 哪些内容会影响编码工作流 / agent workflow / 产品设计
3. 哪些深度访谈值得列入每周精读/精听
4. 哪些内容应该直接过滤，避免信息过载

Read `references/sources.md` as the source registry.

## Audience

Default audience:
- 程序员
- AI 产品构建者
- Agent workflow practitioners
- 关注 AI engineering、agentic workflow、产品化与极客实践的高级用户

## Core Principles

1. 宁缺毋滥：每天只给少量高价值内容，不做全网罗列。
2. Builder 优先：工作流、工程实践、产品形态、agentic coding 升权；纯 benchmark 和泛新闻降权。
3. 分层阅读：固定为每日必看、每周深读、重大事件触发。
4. 决策辅助：每条内容必须回答价值、启发、行动与是否纳入工作流。

## Signal Layers

### Layer A: 每日必看

Track core builder signals from Tier 1 sources and prioritize first-hand artifacts.

### Layer B: 每周深读 / 深听

Pick only high-depth interviews or long reads with decision value for builders.

### Layer C: 重大事件触发

Trigger extra briefing only when one of these happens:
- OpenAI / Anthropic / Google / Meta 发布重大模型或 agent 能力
- Codex / Claude Code / IDE agent workflow 出现关键升级
- AI infra 成本、模型价格、能力边界出现明显变化
- 关键深访直接影响下一阶段 AI coding / AI 产品范式判断

## Scoring Model (100)

Score every candidate before pushing:
- Builder relevance: 30
- Practicality: 20
- Originality: 15
- Depth: 15
- Workflow impact: 10
- Product impact: 10

Boost signals:
- 一手经验
- 深度技术或产品拆解
- 可直接落地
- 能改变判断框架
- 明显影响 AI coding / agent workflow

Penalty signals:
- 纯快讯
- 二手转述
- 广告感强
- 无操作性
- 与 builder 目标弱相关

Push thresholds:
- `85+`: 必推
- `70-84`: 候选
- `<70`: 默认过滤

## Hard Filters

Default-filter these categories unless the user explicitly asks:
- 泛 AI 新闻站碎片快讯
- 纯融资新闻
- 无实操价值的 prompt 技巧合集
- 仅 benchmark 排行且无工程含义
- 与 builder 无关的通用 AI 热门话题
- 重复转述官方公告的二手报道

## Daily Output Contract

Output exactly 4 modules.
Start directly with Module 1 content. Do not add any preamble, methodology, scoring notes, process narration, or "本次筛选如下" style meta text.

### Module 1: Must Know

Return 1 to 3 items.
Each item fields:
- 标题
- 来源
- 类型: `工作流` / `产品` / `平台` / `访谈`
- 3 行摘要
- 为什么重要
- 是否建议立刻阅读

### Module 2: Builder Takeaway

Fields:
- 对编码工作流的影响
- 对 agent 设计的影响
- 对产品设计的影响
- 对你当前工具链的建议

### Module 3: One Deep Read / Listen

Return exactly 1 item.
Fields:
- 推荐理由
- 建议阅读场景
- 读完后该记住什么

### Module 4: Action Items

Return at most 3 directly executable actions.
Examples:
- 试一个新的 Codex workflow
- 调整 agent prompt 分层
- 把一种评估方式加入现有项目

## Weekly Output Contract

Title:
- `AI Builder Weekly Calibration`

Sections:
1. 本周最重要的 5 个 builder 信号
2. 本周最值得精读的 2 个深访
3. 本周最值得尝试的 3 个工具或工作流变化
4. 本周应该忽略的噪音主题
5. 下周值得跟踪的 3 个观察点

## Writing Rules

- 默认中文输出，必要术语可中英混排。
- Use absolute dates and timezone, for example `2026-03-08 08:00 CST`.
- Separate facts from inference and label inference as `判断`.
- Prefer direct links to first-hand artifacts.
- If a source is unavailable or only shell content, mark it in `本轮未纳入` instead of guessing.

## Tooling Notes

- For scheduled daily and weekly digests, prefer direct source pages and feeds.
- Use `web_fetch` for source verification and feed extraction.
- Use `web_search` only as a last-resort supplement when direct sources are missing and the run is not blocked by search availability.
- For YouTube channel URLs, prefer public RSS/Atom feeds (`feeds/videos.xml?channel_id=...`); if channel ID is unknown, RSSHub handle routes are acceptable before trying the channel shell page.
- Treat X as a secondary signal and prefer official post / paper / repo / release pages.
- Do not treat RSSHub Twitter/X mirrors as a primary cron source; they are fallback signal only.
- If X or YouTube returns only a shell page, use a public fallback source or mark it in `本轮未纳入`; do not infer missing content from the shell page.
- Resolve community hotness pages to original targets before writing.

## Scheduling Defaults (Asia/Shanghai)

If user asks for automation, suggest these two jobs:

```python
cron(
    action="add",
    message="Use ai-news-digest to generate the AI Builder Signal Radar daily digest. Focus on high-signal builder content, start from direct source pages and feeds in references/sources.md, use web_search only as a last-resort supplement, include exactly 4 modules (Must Know, Builder Takeaway, One Deep Read / Listen, Action Items), and filter low-signal generic news.",
    cron_expr="0 8 * * *",
    tz="Asia/Shanghai",
)
```

```python
cron(
    action="add",
    message="Use ai-news-digest to generate AI Builder Weekly Calibration with 5 key signals, 2 deep interviews, 3 experiments, noise to ignore, and 3 watchpoints for next week. Prefer direct source pages and feeds before any search supplement.",
    cron_expr="0 9 * * 6",
    tz="Asia/Shanghai",
)
```

Before creating a new schedule, list existing cron jobs first to avoid duplicates.
