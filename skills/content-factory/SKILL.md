---
name: content-factory
description: Turn a chosen topic pillar into a publish-ready multi-platform content pack for Weibo and Xiaohongshu, with reusable hooks, drafts, tags, visuals, and a saved workspace file.
---

# Content Factory

Use this skill when the user wants to turn a chosen topic into content that can be manually published across multiple platforms.

This skill is optimized for these topic pillars:
- AI investment research workflows
- Trading, strategy, options, and automation
- Funds and wealth management
- AI products, tools, and practical ideas

## Goal

Produce a complete content pack, not just a single draft.

Every run should leave the user with:
- One clear topic angle
- One Xiaohongshu draft
- One Weibo draft
- Supporting hooks, tags, and visual suggestions
- A workspace file saved under `content_queue/`

## Content Rules

1. Optimize for `attention + trust + future monetization`, not empty engagement.
2. Prefer framework, workflow, checklist, case study, and experiment content over raw market calls.
3. Do not promise returns or give direct buy/sell instructions.
4. Keep claims concrete. If using market or product facts, separate facts from opinion.
5. Write in Chinese unless the user asks otherwise.

## Topic Selection

When the user has not picked a specific topic yet, propose 3 candidate angles using this filter:
- Can this attract the right followers?
- Can this later lead to templates, tools, consulting, or paid content?
- Can this be turned into a repeatable series?

Prefer topics with one of these shapes:
- `How I do X`
- `3 mistakes / 5 checks / 1 framework`
- `Before vs after using AI`
- `A repeatable weekly workflow`
- `A strategy breakdown without hype`

## Output Contract

Save the result to:

`content_queue/YYYY-MM-DD-slug.md`

Use this structure:

```markdown
# 主题

## 选题定位
- 目标平台:
- 目标受众:
- 内容目标: 涨粉 / 建立信任 / 引流 / 转化
- 核心角度:

## 一句话观点

## 小红书标题候选
1.
2.
3.

## 小红书正文

## 微博正文

## 配图建议
1.
2.
3.

## 标签建议

## 评论区/私信引导

## 可延展选题
1.
2.
3.
```

Also include a short top section with:
- Absolute date
- Topic pillar
- Reuse status: `new` or `series`

## Platform Guidance

### Xiaohongshu

- Open with a strong hook in the first 1 to 2 lines.
- Make it sound like lived experience, not a generic article.
- Use short paragraphs.
- Prefer structure such as `问题 -> 做法 -> 结果 -> 提醒`.
- Strong fit for checklists, systems, templates, and "I changed my process" posts.

### Weibo

- Lead with one clear opinion or observation.
- Keep it compact and high-density.
- Use 3 to 5 short points when useful.
- End with a question, takeaway, or light CTA.

## Recommended Workflow

1. Read `CONTENT_FACTORY.md` in the workspace if it exists.
2. Confirm or infer the topic pillar and desired outcome.
3. Generate the full content pack.
4. Save it under `content_queue/`.
5. In the final reply, summarize the angle and point the user to the saved file.

## Daily Batch Mode

If the user wants recurring production, create 3 candidate topics first, then expand only the selected one.

For a daily scheduled job, use wording like:

```python
cron(
    action="add",
    message="Use the content-factory skill. Based on CONTENT_FACTORY.md, generate 3 content candidates for today in Chinese, optimized for follower growth and future monetization. Then expand the strongest candidate into a full Xiaohongshu + Weibo content pack and save it under content_queue/ with today's date.",
    cron_expr="0 9 * * *",
    tz="Asia/Shanghai",
)
```

Before creating a new schedule, list existing cron jobs first to avoid duplicates.
