---
name: ai-news-digest
description: Track the latest important AI news from official AI labs and community signals, with X as a secondary hotness signal; produce a concise daily digest and schedule it for 08:00 Asia/Shanghai when asked.
---

# AI News Digest

Use this skill when the user asks for latest AI news, an AI morning briefing, a daily AI digest, or wants updates from specific AI creators or official labs.

## Source List

Read [references/sources.md](references/sources.md) to get the current subscription list. Treat that file as the source registry for named people, official lab channels, and community-signal feeds.

## Workflow

1. Gather items in the reporting window, not just the calendar day. For the default morning digest at 08:00 Asia/Shanghai, the window is from the previous day 08:00 to the current day 08:00.
2. Prefer high-quality first-hand sources over quantity. Official blogs/newsrooms/research pages and RSS feeds outrank social signals. Original papers, repos, release notes, and original articles outrank reposts, summaries, and aggregator commentary.
3. Prefer items published within the active reporting window. If an item was published earlier, include it only when it is clearly trending inside the current reporting window on Hacker News or the named X accounts, and label it as `旧文本时段热议`.
4. Verify with primary sources first:
- Official blog/newsroom/research posts and RSS entries
- Original paper/repository/release note pages
- Official YouTube channel uploads or release videos
5. Use Hacker News and GitHub Trending to detect what the technical community is amplifying today, but do not treat either signal page as the source of truth. When they point to a third-party article, repository, or project page, cite the original target first and the signal page second.
6. Keep only important items. Ignore repetitive engagement bait, generic opinions, reposts, screenshots of posts, and minor product chatter without substance.
7. Only include an item when you can identify a concrete underlying artifact: a post, article, paper, release note, video, repository, or official announcement. Do not treat a category page, homepage shell, error page, or generic directory page as a valid item.
8. If a claim cannot be verified from a source you can fetch, say so explicitly instead of guessing.
9. When a source is blocked, empty, or too generic to extract concrete items, report that source as unavailable for this run instead of inventing a summary.
10. When the user asks to add or remove a subscription source, update `references/sources.md` instead of hardcoding the source list into this file.
11. For named people, include only domain-relevant statements. Ignore their posts about politics, lifestyle, personal chatter, memes, sports, or any other non-AI/non-technical topic unless the user explicitly asks for broader coverage.
12. Treat X as a secondary heat signal, not as primary truth. Do not treat `x.com/<account>` profile pages as concrete artifacts. Only use concrete post URLs, and whenever possible back them with official release/paper/repo links.

Priority order for source trust and extraction stability:
1. Official announcements and RSS feeds from labs
2. Original artifacts (paper, repository, official release page)
3. Community hotness signals (Hacker News, GitHub Trending)
4. X signals (secondary only)

## Importance Filter

Include an item only if both conditions hold:
- It is hot inside the current reporting window, or it is explicitly marked `旧文本时段热议`
- It satisfies at least one of the importance conditions below

Importance conditions:
- New model, product, benchmark, API, pricing, policy, funding, or org change
- Credible forward-looking comment from one of the named people that shifts expectations
- Strong community signal on Hacker News around an AI technical release, paper, or tool
- Security, safety, legal, or platform change likely to affect builders or users

For named people, `credible forward-looking comment` means comments about AI research, models, tooling, product direction, engineering practice, safety, regulation, or the AI industry. Do not include off-topic personal commentary.

Prefer 3 to 5 items total. Fewer is better than padding. If there are fewer than 3 genuinely important items, return fewer items and explicitly say `今天重要新内容偏少`.

## Output Format

Use this structure:

```markdown
# 今日 AI 重要资讯

## 1. 标题
- 来源: source name
- 时间: absolute date/time with timezone if available
- 统计窗口: absolute start and end time for this digest
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
- For scheduled morning digests, make the reporting window explicit, for example `统计窗口: 2026-03-07 08:00 CST -> 2026-03-08 08:00 CST`.
- Include direct source links for every item.
- Separate facts from inference. Label inference as `判断`.
- Do not pad the briefing with older items just to reach a quota.
- Prefer the original source link over mirrors, summaries, or social reposts.
- If a source fetch only returns a homepage shell, category heading, access error, or empty page, exclude it from item generation and note it under availability when relevant.
- Telegram formatting constraints (lightweight rich text): keep headings, bullets, bold text, and links only. Do not use tables or code blocks. Keep one item field per line in the fixed order shown above.

## Source Availability

If important sources are unavailable in a run, add a short section before `今日结论`:

```markdown
## 本轮未纳入
- OpenAI Site updates: 403，今天未能稳定抓到具体条目
- X accounts: 当前抓取结果是占位错误页，未纳入正文
```

This section is for transparency, not filler. Include it only when it materially explains why the digest is short.

## Tooling Notes

- Prefer `web_search` to discover the latest relevant source URLs.
- Prefer `web_fetch` on the final source URLs you cite.
- For X-heavy topics, search by account name plus topic, but treat X as signal-only and resolve to an official source whenever possible.
- For official labs, check both blog/newsroom and YouTube when launches may have video demos.
- For Hacker News and GitHub Trending, use them as same-day prioritization signals and then resolve to the original target URL before writing the digest.

## Daily 08:00 Delivery

If the user asks to receive this automatically every morning, schedule it with `cron` using Asia/Shanghai time:

```python
cron(
    action="add",
    message="Use the ai-news-digest skill to compile important AI news in the reporting window from the previous day 08:00 to the current day 08:00 Asia/Shanghai time. Prioritize official announcements and RSS feeds (OpenAI, Anthropic, Google AI) and original artifacts (papers/repos/release notes) over social chatter. Treat Hacker News and GitHub Trending as heat signals only; cite original targets first. Keep X as a secondary signal only, never use profile pages as concrete items, and include X only when backed by a concrete post or first-hand artifact. Prefer items published inside the window; include older items only when clearly trending in-window and label them 旧文本时段热议. If a source is blocked, empty, or shell-only, note it in 本轮未纳入 instead of inventing content. Send a concise Chinese briefing with explicit window, absolute timestamps, hotness attribution, and Telegram-friendly lightweight rich text (no tables, no code blocks).",
    cron_expr="0 8 * * *",
    tz="Asia/Shanghai",
)
```

Before creating a new schedule, list existing cron jobs first to avoid duplicates.
