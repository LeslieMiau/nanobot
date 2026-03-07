---
name: ai-news-digest
description: Track the latest important AI news from selected X accounts, official OpenAI/Anthropic/Gemini channels, and Hacker News hot topics; produce a concise daily digest and schedule it for 08:00 Asia/Shanghai when asked.
---

# AI News Digest

Use this skill when the user asks for latest AI news, an AI morning briefing, a daily AI digest, or wants updates from specific AI creators or official labs.

## Sources

Prioritize these sources:
- X: Andrej Karpathy, 宝玉, Sam Altman
- Official accounts and channels: OpenAI, Anthropic, Gemini on X, YouTube, and official blogs
- Hacker News front page / hottest discussions

## Workflow

1. Gather only fresh items. Prefer content from the last 24 hours for a daily briefing; expand to the last 72 hours only when the news cycle is quiet.
2. Verify with primary sources first:
- Official blog posts
- Official YouTube channel uploads or release videos
- Original X posts from the listed accounts
3. Use Hacker News to detect what the technical community is amplifying, but do not treat HN discussion alone as the source of truth.
4. Keep only important items. Ignore repetitive engagement bait, generic opinions, reposts, and minor product chatter without substance.
5. If a claim cannot be verified from a source you can fetch, say so explicitly instead of guessing.

## Importance Filter

Include an item only if at least one of these is true:
- New model, product, benchmark, API, pricing, policy, funding, or org change
- Credible forward-looking comment from one of the named people that shifts expectations
- Strong community signal on Hacker News around an AI technical release, paper, or tool
- Security, safety, legal, or platform change likely to affect builders or users

Prefer 3 to 7 items total. If there is no genuinely important update, say that the day is quiet.

## Output Format

Use this structure:

```markdown
# 今日 AI 重要资讯

## 1. 标题
- 来源: source name
- 时间: absolute date/time with timezone if available
- 要点: 1 to 2 sentences on what happened
- 为什么重要: 1 sentence on impact
- 链接: direct source URL

## 2. 标题
...

## 今日结论
- 1 to 3 bullets on the biggest pattern across today's items
```

Rules:
- Write in Chinese unless the user asks otherwise.
- Use absolute dates like `2026-03-07 08:00 CST`, not "today" or "yesterday".
- Include direct source links for every item.
- Separate facts from inference. Label inference as `判断`.

## Tooling Notes

- Prefer `web_search` to discover the latest relevant source URLs.
- Prefer `web_fetch` on the final source URLs you cite.
- For X-heavy topics, search by account name plus topic instead of relying on memory.
- For official labs, check both blog and YouTube when launches may have video demos.
- For Hacker News, focus on front-page AI items and use it as a prioritization signal.

## Daily 08:00 Delivery

If the user asks to receive this automatically every morning, schedule it with `cron` using Asia/Shanghai time:

```python
cron(
    action="add",
    message="Use the ai-news-digest skill to compile today's important AI news from Andrej Karpathy, 宝玉, Sam Altman, official OpenAI/Anthropic/Gemini X+YouTube+blogs, and Hacker News hot topics. Send a concise Chinese briefing with source links, absolute timestamps, and a short final takeaway.",
    cron_expr="0 8 * * *",
    tz="Asia/Shanghai",
)
```

Before creating a new schedule, list existing cron jobs first to avoid duplicates.
