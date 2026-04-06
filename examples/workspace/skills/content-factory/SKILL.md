---
name: content-factory
description: Produce multi-platform content packs for Weibo and Xiaohongshu with image-card-first workflows, TradingCat IP prompts, prompt confirmation before generation, and future-ready slots for Douyin and X.
---

# Content Factory

Use this skill when the user wants platform-ready content for Weibo, Xiaohongshu, and future social channels, especially when the content should be visual, meme-aware, and ready for image generation after prompt confirmation.

Read these references when needed:
- `references/tradingcat.md` for the default mascot/IP and consistent role-play visuals
- `references/platforms.md` for platform-specific content adaptation
- `references/confirmation-flow.md` for the staged prompt confirmation workflow

## Goal

Produce a full content pack that is ready to be manually published and visually expanded into cards.

Every run should leave the user with:
- One clear topic angle
- One Xiaohongshu card plan
- One Weibo adaptation
- Per-card overlay text
- Per-card TradingCat role design
- Per-card English image prompt
- A staged image queue awaiting user confirmation
- A workspace file saved under `content_queue/`

## Default Domain

Default to these domains unless the user explicitly changes direction:
- Investing
- Funds
- Wealth management
- AI products and tools

## Style Rules

1. Default tone: `internet-friend roast`, not lecture mode.
2. Prefer a tiny relatable scene over a big abstract conclusion.
3. One joke / one label / one persona per card.
4. Image-first, text-second. Do not write long essays unless the user asks.
5. Avoid empty大道理, generic empathy, and AI-sounding summaries.
6. Do not promise returns or give direct buy/sell instructions.
7. Write in Chinese unless the user asks otherwise.

## Topic Selection

When the user has not picked a topic yet, propose 3 small-cut angles that feel instantly recognizable.

Prefer shapes like:
- `你是哪一种选手`
- `最扎心的4个字`
- `别装了 说的就是你`
- `山顶资本 / 回本就卖 / 热点韭菜王`
- `一个小动作暴露一种亏钱习惯`

## Output Contract

Save the result to:

`content_queue/YYYY-MM-DD-slug.md`

Use this structure:

```markdown
# 主题

## 选题定位
- 目标平台:
- 目标受众:
- 内容目标:
- 核心角度:

## 一句话钩子

## 小红书封面
- 标题:
- 副标题:

## 小红书图卡
### P1
- 图上文字:
- TradingCat 角色:
- Prompt:

### P2
...

## 微博正文

## 微博配图改写

## Douyin adaptation

## X adaptation

## 可延展选题
1.
2.
3.
```

Also include a short top section with:
- Absolute date
- Topic pillar
- Reuse status
- Per-card image status: `pending` / `generated` / `skipped`

## Platform Guidance

### Xiaohongshu

- Default unit is a card, not a long paragraph.
- One card should carry one punchline.
- Use recognizable labels, self-roast, and comment-bait.
- Prioritize `认领感` over completeness.

### Weibo

- Lead with the sharpest label or punchline.
- Compress into repostable short lines.
- Image groups are preferred over long explanation.

### Douyin

- Only output adaptation notes in v1.
- Focus on short spoken beats and faster setup/payoff.

### X

- Only output adaptation notes in v1.
- Focus on thread or meme-post style adaptation.

## Recommended Workflow

1. Read `CONTENT_FACTORY.md` in the workspace if it exists.
2. Confirm or infer the topic pillar and target platform.
3. Generate the content pack with card-by-card overlays.
4. For each card, generate a TradingCat role description and an English image prompt.
5. Stage each prompt with `image_generate(action="stage", ...)`.
6. Do not call `image_generate(action="generate", ...)` until the user confirms the current prompt.
7. Save the content pack under `content_queue/`.
8. In the final reply, summarize the angle and show the current pending image prompt state.

## Prompt Confirmation Rules

- The user must review prompts before generation.
- Use the built-in image confirmation commands:
  - `/image-confirm`
  - `/image-edit <feedback>`
  - `/image-skip`
- After the user confirms one card, continue to the next staged card.
- Never generate all cards at once by default.

## Daily Batch Mode

If the user wants recurring production, create 3 candidates first, then expand one selected topic into a card-based pack.

Before creating a new schedule, list existing cron jobs first to avoid duplicates.
