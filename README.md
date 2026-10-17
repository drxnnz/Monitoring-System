# Free Monitor v2 (Telegram + Messenger)

Tuloy pa rin ang GitHub Actions monitor (every ~15 min), pero may **Messenger bot na** na may menu, pili-pili ng updates, "worth it ba?" na sagot, at mga picture.

## Ano ang bago

- **Game deals**: Orig price → discount → final price, may ≈₱ conversion, Steam rating, lowest-ever price, at rules-based verdict (🔥 Sulit na sulit / 👍 Sulit / 🤔 / ⏳).
- **Pictures**: Steam header, Epic art, GitHub preview card, at og:image/feed image para sa memos.
- **Messenger bot**: Get Started → automatic na lahat ng updates (walang quiz/settings) → menu na may 📰 Ano update? / 🆓 Libreng games / 🏫 May pasok?. Tanungin mo: "worth it ba ang Hollow Knight?"
- **24h rule workaround**: Pwede lang mag-push ang bot within 24h ng huli mong chat. Kapag lampas na, iniipon ang updates; i-type mo lang ang "update" para makuha lahat ng na-miss.
- **Bug fixes**: hindi na nawawala ang item kapag pumalya ang send (ire-retry next run), Epic partial discounts hindi na kasama, dealID hindi na double-encoded, "hi" hindi na nagma-match sa "this"/"which".

## Setup

### 1. Telegram (reliable push, walang 24h limit)
- GitHub Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (group/channel na pinag-bro-broadcast, optional na; pwede ang marami, hiwalay ng comma: `-1003581254205,123456789`).
- **Telegram bot na sumasagot sa kahit sino**: ilagay din ang `TELEGRAM_BOT_TOKEN` sa **Render env vars**. Kusang magre-register ng webhook (`/telegram`) ang server pag nag-start, gamit ang `RENDER_EXTERNAL_URL` na nilalagay mismo ng Render. Optional: `TELEGRAM_WEBHOOK_SECRET` (random letters/numbers) para sigurado na Telegram lang ang makakatawag.
- Commands: `/start`, `/updates`, `/free`, `/worth <game>`, `/settings`, `/stop`. Pwede rin i-type lang: "worth it ba ang Hades?"
- Sa group: naka-on ang privacy mode ng bots, kaya commands (`/worth Hades`) at mga buttons lang ang nakikita niya. Para mabasa ang normal na chat, BotFather → `/setprivacy` → Disable.
- Kailangan ang Upstash (step 2) para maalala ng bot ang pinili ng bawat user.

### 2. Upstash Redis (free) — para magkasama ang bot at monitor
1. Gumawa ng free database sa upstash.com.
2. Kopyahin ang **REST URL** at **REST TOKEN**.
3. Ilagay sa GitHub Secrets: `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`.

### 3. I-host ang webhook (`messenger_bot.py`)
GitHub Actions **hindi** makakapag-host ng webhook. Kailangan ng web service (hal. Render free web service):
- Build: `pip install -r requirements.txt`
- Start: `gunicorn messenger_bot:app`
- Env vars: `PAGE_ACCESS_TOKEN`, `VERIFY_TOKEN`, `APP_SECRET` (Meta app secret), `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`

### 4. Meta app
1. Webhook callback: `https://<host>/webhook`, verify token = `VERIFY_TOKEN`.
2. Subscribe sa fields: `messages`, `messaging_postbacks`.
3. I-subscribe ang Page sa app.
4. **Importante**: kapag nasa *Development mode* ang app, mga may role lang (admin/tester) ang makakausap ng bot. Para sa ibang tao, kailangan i-Live (may App Review para sa `pages_messaging`).
5. Run once: `PAGE_ACCESS_TOKEN=... python setup_messenger.py` (Get Started button + menu).

### 5. Actions secrets
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `PAGE_ACCESS_TOKEN`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`. (`ADMIN_PSID` optional na lang. Optional din: `KEEPALIVE_URL` = URL ng Render service mo, para ma-ping ng monitor at hindi masyadong natutulog.)

### Single-chat mode (mas magaan, hindi nagfi-freeze)
Kung isang chat/group lang ang gagamit: `TELEGRAM_CHAT_ID` = chat id na yun, tapos `TG_SINGLE_CHAT=1` sa **Render env vars** at sa **GitHub Secrets**. Yun lang ang sasagutin ng bot, walang per-user subscriptions o onboarding. Sa Render, Start Command: `gunicorn messenger_bot:app --threads 4 --timeout 90`.

## BulSU memos na may picture

Hindi puwedeng i-scrape nang maayos ang Facebook posts. Dalawang option:
1. Kung may RSS ang BulSU website, ilagay ang URL sa `sources.json`.
2. Gumamit ng RSS generator (hal. rss.app, FetchRSS) para sa public Facebook page, tapos ilagay ang feed URL sa `sources.json`. Kukunin ng monitor ang picture mula sa feed o sa og:image ng link. (Third-party ito at may limits ang free plan.)

## Mga limitasyon (honest)

- Ang "worth it?" ay rules-based (reviews + price history + discount), **hindi** AI at hindi personal na opinyon.
- Presyo ay galing CheapShark (USD); ang ₱ ay approximate lang. Iba ang actual Steam PH price.
- Messenger: walang libreng push lampas 24h. Telegram ang reliable para sa urgent alerts.
- Hindi pa na-test sa live APIs (Meta, CheapShark, Upstash). I-check ang logs sa unang run.

## Test (offline)
`python tests/test_logic.py`
