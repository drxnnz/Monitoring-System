# Free Daily Discovery + Local Alert Monitor

A no-paid-API starter kit that runs on GitHub Actions and sends new findings to Telegram.
It runs every 15 minutes, but GitHub Actions schedules can be delayed and sources do not all update that quickly.

## What it monitors

- Game deals: CheapShark public API; filters for 80%+ discounts and substantial review counts. Prices are shown in USD because that is the API's currency. Links use CheapShark's required deal redirect.
- Epic free games: Epic's public store endpoint when available; reports current free-to-keep promotions with their claim windows.
- GitHub / AI projects: GitHub public repository search for recently created AI/open-source projects with a minimum star threshold.
- Malolos / BSU / weather: Google News RSS searches are used for discovery, then items are included only if the linked publisher domain looks like an official source. This is best-effort: Facebook-only posts and pages that block indexing may be missed. For urgent safety alerts, keep official PAGASA/LGU channels enabled separately.

No paid AI model is used. Filtering is deterministic to avoid requiring a paid LLM API. It is not guaranteed to understand every announcement or verify all claims like a human.

## 1. Create a Telegram bot

1. In Telegram, message `@BotFather`.
2. Send `/newbot` and follow the instructions.
3. Copy the bot token.
4. Open the new bot and send `/start`.
5. Get your chat ID:
   - Easiest: open `https://api.telegram.org/botYOUR_TOKEN/getUpdates` in a browser after sending `/start`.
   - Find `message.chat.id` in the JSON response.
   - Keep the token private. Do not put it in source code.

## 2. Create a public GitHub repository

1. Create a new **public** repository on GitHub, e.g. `free-monitor`.
2. Upload the contents of this ZIP while preserving the `.github/workflows/monitor.yml` path.
3. In the repository, open **Settings → Secrets and variables → Actions → New repository secret**:
   - `TELEGRAM_BOT_TOKEN` = your bot token
   - `TELEGRAM_CHAT_ID` = your chat ID
4. Open **Actions**, enable workflows if GitHub asks, and run **Free Monitor** manually once using **Run workflow**.

Why public? Standard GitHub-hosted Actions runners are free for public repositories. If you prefer a private repository, check your account's current Actions quota before enabling frequent runs.

## 3. Test it

The first run stores seen-item IDs in `state.json` and may send the current qualifying findings it discovers (up to 12 items). Subsequent runs send only unseen qualifying items.

If no new findings appear, it sends no message. You can change this in `monitor.py` if you want a daily “no updates” digest.

## Important limits

- A 15-minute schedule means the workflow checks roughly every 15 minutes, not instant alerts. GitHub may delay scheduled runs.
- CheapShark prices are generally updated around hourly and are USD, so checking every 15 minutes does not make its source data real-time.
- Game deals are filtered by discount and popularity; the free-to-keep feed is separate from free-to-play games.
- News RSS is a discovery mechanism, not an official emergency alert feed. The source-domain allowlist is intentionally strict and may miss legitimate announcements. Add verified official feeds/pages for your locality as you confirm them.
- GitHub repository search only finds projects that meet the query threshold; it will miss small projects and repositories that become popular later.
- No LLM/API key is needed. This is rules-based monitoring, not a general-purpose AI agent.
- Public repository means the workflow and `state.json` are visible. Never store bot tokens in files; use GitHub Secrets.

## Change the schedule

Edit `.github/workflows/monitor.yml`. The cron schedule `*/15 * * * *` means every 15 minutes in UTC. Do not change it unless you understand GitHub Actions schedule limits.
