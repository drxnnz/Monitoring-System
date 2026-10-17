import calendar
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import os
import re
import time
from urllib.parse import quote_plus, urlparse
import feedparser
import requests

import deals
import messenger
import store
import tg
from config import KIND_PREF, MAX_PUSH_PER_USER, WINDOW_SECONDS

PHT = timezone(timedelta(hours=8))
STATE_PATH = "state.json"
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
GH_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

# Dagdag para sa Facebook Messenger Integration
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "").strip()
ADMIN_PSID = os.getenv("ADMIN_PSID", "").strip()

USER_AGENT = "FreeMonitor/2.0 (personal project; contact: configure-in-repo)"
TIMEOUT = 18
MAX_ITEMS_PER_RUN = 12

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": (
        "application/json, application/atom+xml, application/rss+xml, */*"
    ),
})


def now_pht():
  return datetime.now(PHT)


def get_json(url, headers=None, params=None):
  try:
    r = SESSION.get(url, headers=headers, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()
  except Exception as e:
    print(f"[WARN] JSON fetch failed: {url}: {e}")
    return None


def stable_id(value):
  return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:20]


def load_state():
  try:
    with open(STATE_PATH, "r", encoding="utf-8") as f:
      data = json.load(f)
      return set(data.get("seen", []))
  except Exception:
    return set()


def save_state(seen):
  with open(STATE_PATH, "w", encoding="utf-8") as f:
    json.dump({"seen": list(sorted(seen))[-5000:]}, f, indent=2)


def parse_date(value):
  if not value:
    return None
  try:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
      dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PHT)
  except Exception:
    return None


def esc(s):
  return html.escape(str(s or ""), quote=False)


def fetch_cheapshark():
  found = []
  url = "https://www.cheapshark.com/api/1.0/deals"
  params = {
      "storeID": "1",
      "pageSize": 60,
      "pageNumber": 0,
      "sortBy": "Savings",
      "desc": 1,
      "onSale": 1,
      "minimumReviewCount": 500,
      "maxAge": 24,
  }
  data = get_json(url, params=params)
  if not isinstance(data, list):
    return found
  for d in data:
    try:
      savings = float(d.get("savings", 0))
      current = float(d.get("salePrice", 0))
      original = float(d.get("normalPrice", 0))
      if savings < 80 or current < 0 or original <= 0:
        continue
      if d.get("isOnSale") != "1":
        continue
      deal_id = d.get("dealID")
      if not deal_id:
        continue

      def build(rate, d=d, deal_id=deal_id):
        # Runs only for unseen deals, so the price-history call is not
        # wasted on items we already sent.
        snap = deals.snapshot_from_list_deal(d)
        return {
            "title": snap["title"],
            "lines": deals.game_lines(snap, rate),
            "image": deals.steam_image(snap["app_id"], snap["thumb"]),
        }

      found.append({
          "id": "game:" + stable_id(deal_id),
          "kind": "game",
          "category": "🎮 GAME DEAL",
          "title": d.get("title", "Unknown game"),
          "lines": [],
          "url": deals.redirect_url(deal_id),
          "image": None,
          "meta": {"deal_id": deal_id},
          "_build": build,
      })
    except Exception:
      continue
  return found[:8]


def fetch_epic_free_games():
  found = []
  url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
  data = get_json(
      url, params={"locale": "en-US", "country": "US", "allowCountries": "US"}
  )
  try:
    elements = data["data"]["Catalog"]["searchStore"]["elements"]
  except Exception:
    print("[WARN] Epic free-games response shape changed or is unavailable.")
    return found
  now = datetime.now(timezone.utc)
  for game in elements:
    try:
      promotions = game.get("promotions") or {}
      offers = promotions.get("promotionalOffers") or []
      active = []
      for group in offers:
        for offer in group.get("promotionalOffers", []):
          # Epic encodes "100% off" as discountPercentage == 0. Skip partial
          # discounts so we only report truly free-to-keep games.
          pct = (offer.get("discountSetting") or {}).get("discountPercentage")
          if pct is not None and pct != 0:
            continue
          start = parse_date(offer.get("startDate"))
          end = parse_date(offer.get("endDate"))
          if end and end.astimezone(timezone.utc) < now:
            continue
          if start and start.astimezone(timezone.utc) > now:
            continue
          active.append((start, end))
      if not active:
        continue
      title = game.get("title") or "Epic free game"
      slug = game.get("productSlug") or game.get("urlSlug") or ""
      mappings = game.get("catalogNs", {}).get("mappings") or []
      if mappings and mappings[0].get("pageSlug"):
        slug = mappings[0]["pageSlug"]
      link = (
          f"https://store.epicgames.com/en-US/p/{slug}"
          if slug
          else "https://store.epicgames.com/en-US/free-games"
      )
      end = active[0][1]
      deadline = (
          end.strftime("%b %d, %Y %I:%M %p PHT") if end else "deadline not listed"
      )
      orig = (
          ((game.get("price") or {}).get("totalPrice") or {}).get("fmtPrice")
          or {}
      ).get("originalPrice")
      image = None
      for wanted in ("OfferImageWide", "DieselStoreFrontWide", "Thumbnail"):
        for img in game.get("keyImages") or []:
          if img.get("type") == wanted and img.get("url"):
            image = img["url"]
            break
        if image:
          break
      lines = []
      if orig:
        lines.append(f"🏷️ Dati: {orig} → ✅ LIBRE (keep forever)")
      else:
        lines.append("✅ LIBRE, keep forever")
      lines.append(f"⏰ Claim hanggang: {deadline}")
      desc = (game.get("description") or "").strip()
      if desc:
        lines.append(f"📝 {desc[:110]}{'…' if len(desc) > 110 else ''}")
      found.append({
          "id": "epic:" + stable_id(title + str(end)),
          "kind": "free",
          "category": "🆓 EPIC FREE-TO-KEEP",
          "title": title,
          "lines": lines,
          "url": link,
          "image": image,
          "meta": {},
      })
    except Exception:
      continue
  return found


def fetch_github_projects():
  found = []
  headers = {"Accept": "application/vnd.github+json"}
  if GH_TOKEN:
    headers["Authorization"] = f"Bearer {GH_TOKEN}"
  today = now_pht().date().isoformat()
  queries = [
      (
          '(AI OR LLM OR agent OR "open source alternative") created:>='
          f" {today} stars:>=30"
      ),
  ]
  for q in queries:
    data = get_json(
        "https://api.github.com/search/repositories",
        headers=headers,
        params={"q": q, "sort": "stars", "order": "desc", "per_page": 10},
    )
    if not isinstance(data, dict):
      continue
    for repo in data.get("items", []):
      try:
        full_name = repo["full_name"]
        stars = repo.get("stargazers_count", 0)
        desc = repo.get("description") or "No description provided."
        lic = (repo.get("license") or {}).get("spdx_id") or "no license"
        found.append({
            "id": "ghrepo:" + stable_id(full_name),
            "kind": "github",
            "category": "🧩 NEW GITHUB PROJECT",
            "title": full_name,
            "lines": [
                desc[:160],
                f"⭐ {stars:,} · {repo.get('language') or 'n/a'} · {lic}",
            ],
            "url": repo.get("html_url", f"https://github.com/{full_name}"),
            "image": f"https://opengraph.githubassets.com/1/{full_name}",
            "meta": {},
        })
      except Exception:
        continue

  repos = [
      "ollama/ollama",
      "open-webui/open-webui",
      "huggingface/transformers",
      "comfyanonymous/ComfyUI",
      "langflow-ai/langflow",
      "n8n-io/n8n",
      "immich-app/immich",
      "yt-dlp/yt-dlp",
  ]
  for name in repos:
    data = get_json(
        f"https://api.github.com/repos/{name}/releases/latest", headers=headers
    )
    if not isinstance(data, dict) or not data.get("tag_name"):
      continue
    published = parse_date(data.get("published_at"))
    if not published or published.date() != now_pht().date():
      continue
    tag = data.get("tag_name")
    found.append({
        "id": "ghrelease:" + stable_id(name + ":" + tag),
        "kind": "github",
        "category": "🚀 GITHUB RELEASE",
        "title": f"{name} · {tag}",
        "lines": [
            (data.get("name") or data.get("body") or "New release today.")
            .strip()[:160]
        ],
        "url": data.get("html_url", f"https://github.com/{name}/releases"),
        "image": f"https://opengraph.githubassets.com/1/{name}",
        "meta": {},
    })
  return found


def google_news_rss(query):
  url = (
      "https://news.google.com/rss/search?q="
      + quote_plus(query)
      + "&hl=en-PH&gl=PH&ceid=PH:en"
  )
  try:
    r = SESSION.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return feedparser.parse(r.content).entries
  except Exception as e:
    print(f"[WARN] RSS fetch failed for {query}: {e}")
    return []


def officialish_domain(link):
  try:
    host = (urlparse(link).hostname or "").lower()
    allowed = (
        "pagasa.dost.gov.ph",
        "ndrrmc.gov.ph",
        "ocd.gov.ph",
        "bulacan.gov.ph",
        "maloloscity.gov.ph",
        "malolos.gov.ph",
        "bsu.edu.ph",
        "bulsu.edu.ph",
        "facebook.com",
    )
    return any(host == d or host.endswith("." + d) for d in allowed)
  except Exception:
    return False


def clean_text(s):
  s = re.sub(r"<[^>]+>", " ", s or "")
  return re.sub(r"\s+", " ", html.unescape(s)).strip()


def fetch_local_alerts():
  found = []
  queries = [
      '"Malolos" "class suspension"',
      '"Malolos" "work suspension"',
      '"Bulacan State University" suspension',
      "site:pagasa.dost.gov.ph Bulacan warning OR rainfall OR typhoon",
      "Malolos Bulacan flooding alert",
  ]
  cutoff = now_pht() - timedelta(hours=30)
  keywords = [
      "suspend", "walang pasok", "class cancellation", "flood", "flooding",
      "typhoon", "tropical cyclone", "rainfall warning", "heavy rain",
      "severe weather", "signal no.", "storm signal", "disaster alert",
  ]
  for query in queries:
    for entry in google_news_rss(query)[:12]:
      try:
        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        src = entry.get("source") or {}
        publisher_url = src.get("href", "") or link
        summary = clean_text(entry.get("summary", ""))
        published = None
        if entry.get("published_parsed"):
          published = datetime.fromtimestamp(
              calendar.timegm(entry.published_parsed), timezone.utc
          ).astimezone(PHT)
        if (
            not published
            or published < cutoff
            or published.date() != now_pht().date()
        ):
          continue
        if not officialish_domain(publisher_url):
          continue
        low = (title + " " + summary).lower()
        if not any(k in low for k in keywords):
          continue
        lines = []
        if summary and summary.lower() != title.lower():
          lines.append(summary[:200])
        lines.append(
            f"🗞️ {src.get('title') or urlparse(publisher_url).hostname}"
            f" · {published.strftime('%b %d, %I:%M %p')}"
        )
        found.append({
            "id": "local:" + stable_id(link + title),
            "kind": "local",
            "category": "📢 LOCAL / WEATHER ALERT",
            "title": title[:150],
            "lines": lines,
            "url": link,
            "image": None,
            "meta": {},
        })
      except Exception:
        continue
  unique = {}
  for item in found:
    unique[item["id"]] = item
  return list(unique.values())[:8]


# ---------- curated feeds (BulSU memos, LGU pages, rss.app feeds, ...) ----------

OG_RE = [
    re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']', re.I),
]
IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)', re.I)


def og_image(page_url):
  try:
    r = SESSION.get(page_url, timeout=TIMEOUT)
    r.raise_for_status()
    for rx in OG_RE:
      m = rx.search(r.text[:200000])
      if m:
        return html.unescape(m.group(1))
  except Exception as e:
    print(f"[WARN] og:image fetch failed for {page_url}: {e}")
  return None


def entry_image(entry):
  for key in ("media_content", "media_thumbnail"):
    for m in entry.get(key) or []:
      if m.get("url"):
        return m["url"]
  for enc in entry.get("enclosures") or []:
    if str(enc.get("type", "")).startswith("image") and enc.get("href"):
      return enc["href"]
  blobs = [entry.get("summary", "")] + [
      c.get("value", "") for c in entry.get("content") or []
  ]
  for b in blobs:
    m = IMG_RE.search(b or "")
    if m:
      return html.unescape(m.group(1))
  return None


def load_sources():
  try:
    with open("sources.json", "r", encoding="utf-8") as f:
      return json.load(f).get("feeds", [])
  except Exception:
    return []


def fetch_extra_feeds():
  found = []
  for feed in load_sources():
    url = (feed.get("url") or "").strip()
    if not url:
      continue
    kind = feed.get("kind", "memo")
    label = {"memo": "📌 MEMO / ANNOUNCEMENT"}.get(kind, "📢 LOCAL UPDATE")
    cutoff = now_pht() - timedelta(days=int(feed.get("max_age_days", 3)))
    try:
      r = SESSION.get(url, timeout=TIMEOUT)
      r.raise_for_status()
      entries = feedparser.parse(r.content).entries
    except Exception as e:
      print(f"[WARN] Feed failed {url}: {e}")
      continue
    for entry in entries[:10]:
      try:
        link = entry.get("link", "")
        title = clean_text(entry.get("title", ""))[:150]
        if not link or not title:
          continue
        ts = entry.get("published_parsed") or entry.get("updated_parsed")
        if ts:
          published = datetime.fromtimestamp(
              calendar.timegm(ts), timezone.utc).astimezone(PHT)
          if published < cutoff:
            continue
        else:
          published = None
        summary = clean_text(entry.get("summary", ""))
        lines = []
        if summary and summary.lower() != title.lower():
          lines.append(summary[:220])
        stamp = published.strftime("%b %d, %I:%M %p") if published else ""
        lines.append(f"📍 {feed.get('name', 'Feed')} {('· ' + stamp) if stamp else ''}".strip())
        image = entry_image(entry)

        def build(rate, link=link, image=image):
          return {"image": image or og_image(link)}

        found.append({
            "id": "feed:" + stable_id(link),
            "kind": kind,
            "category": label,
            "title": title,
            "lines": lines,
            "url": link,
            "image": image,
            "meta": {},
            "_build": build,
        })
      except Exception:
        continue
    time.sleep(0.5)
  return found[:10]


# ---------- delivery ----------


def broadcast_ids():
  """TELEGRAM_CHAT_ID may hold several IDs separated by commas."""
  return [c.strip() for c in CHAT_ID.split(",") if c.strip()]


def telegram_broadcast(item):
  """Sends to every ID in TELEGRAM_CHAT_ID.
  True = at least one sent, False = all failed (retry next run),
  None = not configured."""
  ids = broadcast_ids()
  if not TOKEN or not ids:
    print("[WARN] TELEGRAM_CHAT_ID/TOKEN missing; no Telegram broadcast.")
    return None
  results = [tg.send_item(c, item) is True for c in ids]
  return any(results)


def push_telegram(items):
  """Everyone who chatted with the bot and picked their updates."""
  if not TOKEN:
    return
  for user in audience():
    if not user["psid"].startswith("tg:"):
      continue
    chat_id = user["psid"][3:]
    mine = [i for i in items if KIND_PREF.get(i["kind"]) in user["prefs"]]
    for item in mine:
      status = tg.send_item(chat_id, item)
      time.sleep(0.1)
      if status == "blocked":  # user blocked the bot
        user["prefs"] = []
        store.save_user(user)
        break


def audience():
  """Subscribers from the store, plus the legacy ADMIN_PSID if set."""
  users = []
  try:
    users = store.all_users()
  except Exception as e:
    print(f"[WARN] Could not load subscribers: {e}")
  admin = os.getenv("ADMIN_PSID", "").strip()
  if admin and all(u["psid"] != admin for u in users):
    u = store.get_user(admin)
    if not u["prefs"]:
      u["prefs"] = list(KIND_PREF.values())
    users.append(u)
  return users


def push_messenger(items):
  if not os.getenv("PAGE_ACCESS_TOKEN", "").strip():
    print("[WARN] PAGE_ACCESS_TOKEN missing; skipping Messenger.")
    return
  now = time.time()
  for user in audience():
    if user["psid"].startswith("tg:"):
      continue
    mine = [i for i in items if KIND_PREF.get(i["kind"]) in user["prefs"]]
    if not mine:
      continue
    psid = user["psid"]
    in_window = now - float(user.get("last_msg") or 0) < WINDOW_SECONDS
    sent = 0
    blocked = not in_window
    for item in mine:
      if not blocked and sent < MAX_PUSH_PER_USER:
        status = messenger.send_item(psid, item, messaging_type="UPDATE")
        if status == "ok":
          sent += 1
          continue
        blocked = status == "window" or blocked
      store.queue_pending(psid, item)
    left = len(mine) - sent
    if sent and left > 0:
      messenger.send_text(
          psid, f"May {left} pa na naka-queue. I-type ang “update” para makuha.",
          messaging_type="UPDATE")


def keep_awake():
  """Optional: ping the free Render service so it sleeps less."""
  url = os.getenv("KEEPALIVE_URL", "").strip()
  if url:
    try:
      SESSION.get(url, timeout=60)
    except Exception as e:
      print(f"[WARN] keepalive failed: {e}")


def main():
  keep_awake()
  seen = load_state()
  all_items = []
  for fetcher in (
      fetch_cheapshark,
      fetch_epic_free_games,
      fetch_github_projects,
      fetch_local_alerts,
      fetch_extra_feeds,
  ):
    try:
      all_items.extend(fetcher())
    except Exception as e:
      print(f"[WARN] {fetcher.__name__} failed: {e}")

  fresh = []
  ids = set()
  for item in all_items:
    if item["id"] not in seen and item["id"] not in ids:
      fresh.append(item)
      ids.add(item["id"])
  fresh = fresh[:MAX_ITEMS_PER_RUN]  # the rest stay unseen -> next run

  if not fresh:
    print(f"No new qualifying items at {now_pht().isoformat()}")
    return

  rate = deals.php_rate()
  for item in fresh:
    build = item.pop("_build", None)
    if build:
      try:
        item.update(build(rate))
      except Exception as e:
        print(f"[WARN] Could not enrich {item['id']}: {e}")

  # Telegram first. Items that failed there are NOT marked seen, so they are
  # retried next run instead of being lost.
  delivered = []
  for item in fresh:
    ok = telegram_broadcast(item)
    time.sleep(0.4)
    if ok is not False:
      delivered.append(item)

  if delivered:
    try:
      for item in delivered:
        store.push_recent(item)  # powers "Ano bago?" in both bots
    except Exception as e:
      print(f"[WARN] Could not save recent items: {e}")
    push_telegram(delivered)
    push_messenger(delivered)
  for item in delivered:
    seen.add(item["id"])
  save_state(seen)
  print(f"Delivered {len(delivered)}/{len(fresh)} new items.")


if __name__ == "__main__":
  main()
