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

1. Gather today's hot items by default. Use Asia/Shanghai as the reporting date unless the user specifies another timezone.
2. Prefer high-quality first-hand sources over quantity. Official blogs, official X posts, official YouTube uploads, original papers, and the original article itself outrank reposts, summaries, and aggregator commentary.
3. Prefer items published on the current calendar date. If an item was published earlier, include it only when it is clearly trending today on Hacker News or the named X accounts, and label it as `旧文今日热议`.
4. Verify with primary sources first:
- Official blog posts
- Official YouTube channel uploads or release videos
- Original X posts from the listed accounts
5. Use Hacker News to detect what the technical community is amplifying today, but do not treat HN discussion alone as the source of truth. When HN links to a third-party article, cite the original article first and HN second.
6. Keep only important items. Ignore repetitive engagement bait, generic opinions, reposts, screenshots of posts, and minor product chatter without substance.
7. If a claim cannot be verified from a source you can fetch, say so explicitly instead of guessing.

## Importance Filter

Include an item only if both conditions hold:
- It is hot today in Asia/Shanghai date terms, or it is explicitly marked `旧文今日热议`
- It satisfies at least one of the importance conditions below

Importance conditions:
- New model, product, benchmark, API, pricing, policy, funding, or org change
- Credible forward-looking comment from one of the named people that shifts expectations
- Strong community signal on Hacker News around an AI technical release, paper, or tool
- Security, safety, legal, or platform change likely to affect builders or users

Prefer 3 to 5 items total. Fewer is better than padding. If there are fewer than 3 genuinely important items, return fewer items and explicitly say `今天重要新内容偏少`.

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
- 热度归因: why this counts as hot today, for example HN front page / official same-day release / named-account same-day post

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
- Do not pad the briefing with older items just to reach a quota.
- Prefer the original source link over mirrors, summaries, or social reposts.

## Tooling Notes

- Prefer `web_search` to discover the latest relevant source URLs.
- Prefer `web_fetch` on the final source URLs you cite.
- For X-heavy topics, search by account name plus topic instead of relying on memory.
- For official labs, check both blog and YouTube when launches may have video demos.
- For Hacker News, focus on front-page AI items and use it as a same-day prioritization signal.

## Daily 08:00 Delivery

If the user asks to receive this automatically every morning, schedule it with `cron` using Asia/Shanghai time:

```python
cron(
    action="add",
    message="Use the ai-news-digest skill to compile today's hot AI articles and posts in Asia/Shanghai time from Andrej Karpathy, 宝玉, Sam Altman, official OpenAI/Anthropic/Gemini X+YouTube+blogs, and Hacker News hot topics. Prioritize high-quality first-hand sources over quantity. Prefer same-day items; include older items only if they are clearly trending today and label them 旧文今日热议. Send a concise Chinese briefing with original source links, absolute timestamps, hotness attribution, and a short final takeaway.",
    cron_expr="0 8 * * *",
    tz="Asia/Shanghai",
)
```

Before creating a new schedule, list existing cron jobs first to avoid duplicates.
