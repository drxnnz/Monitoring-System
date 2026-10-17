from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import os
import re
from urllib.parse import quote_plus, urlparse
import feedparser
import requests

PHT = timezone(timedelta(hours=8))
STATE_PATH = "state.json"
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
GH_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

# Dagdag para sa Facebook Messenger Integration
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "").strip()
ADMIN_PSID = os.getenv("ADMIN_PSID", "").strip()

USER_AGENT = "FreeMonitor/1.0 (personal project; contact: configure-in-repo)"
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
      title = d.get("title", "Unknown game")
      deal_id = d.get("dealID")
      if not deal_id:
        continue
      url = f"https://www.cheapshark.com/redirect?dealID={quote_plus(deal_id)}"
      store_id = "Steam"
      found.append({
          "id": "game:" + stable_id(deal_id),
          "category": "🎮 GAME DEAL",
          "title": title,
          "body": (
              f"Store ID {store_id} · ${original:.2f} → ${current:.2f} USD ·"
              f" {savings:.1f}% off · Steam rating:"
              f" {d.get('steamRatingText') or 'not listed'}"
          ),
          "url": url,
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
          end.strftime("%b %d, %Y %H:%M PHT") if end else "deadline not listed"
      )
      found.append({
          "id": "epic:" + stable_id(title + str(end)),
          "category": "🆓 EPIC FREE-TO-KEEP",
          "title": title,
          "body": (
              "Claim free and keep permanently · Claim window ends:"
              f" {deadline}"
          ),
          "url": link,
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
        created = repo.get("created_at", "")[:10]
        found.append({
            "id": "ghrepo:" + stable_id(full_name),
            "category": "🧩 NEW GITHUB PROJECT",
            "title": full_name,
            "body": (
                f"{desc[:220]} · ⭐ {stars:,} stars · created {created} ·"
                " "
                f"{repo.get('license', {}).get('spdx_id') if repo.get('license') else 'license not detected'}"
            ),
            "url": repo.get(
                "html_url", f"https://github.com/{full_name}"
            ),
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
        "category": "🚀 GITHUB RELEASE",
        "title": f"{name} · {tag}",
        "body": (
            data.get("name")
            or data.get("body")
            or "New release published today."
        ).strip()[:220],
        "url": data.get("html_url", f"https://github.com/{name}/releases"),
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
  for query in queries:
    for entry in google_news_rss(query)[:12]:
      try:
        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        publisher_url = (entry.get("source") or {}).get("href", "") or link
        summary = re.sub(r"<[^>]+>", " ", entry.get("summary", ""))
        summary = re.sub(r"\s+", " ", html.unescape(summary)).strip()
        published = None
        if entry.get("published_parsed"):
          import calendar

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
        relevant = any(
            k in low
            for k in [
                "suspend",
                "walang pasok",
                "class cancellation",
                "flood",
                "flooding",
                "typhoon",
                "tropical cyclone",
                "rainfall warning",
                "heavy rain",
                "severe weather",
                "signal no.",
                "storm signal",
                "disaster alert",
            ]
        )
        if not relevant:
          continue
        found.append({
            "id": "local:" + stable_id(link + title),
            "category": "📢 LOCAL / WEATHER ALERT",
            "title": title[:180],
            "body": (
                summary
                or "Open the linked source for the announcement details."
            )[:260],
            "url": link,
        })
      except Exception:
        continue
  unique = {}
  for item in found:
    unique[item["id"]] = item
  return list(unique.values())[:8]


def telegram_send(message):
  if not TOKEN or not CHAT_ID:
    print(
        "[WARN] Telegram secrets are missing; report will only appear in"
        " workflow logs."
    )
    return False
  url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
  try:
    r = SESSION.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return True
  except Exception as e:
    print(f"[ERROR] Telegram send failed: {e}")
    return False


def strip_html(text):
  """Remove simple HTML tags so Messenger gets clean plain text."""
  text = re.sub(r"<[^>]+>", "", text)
  return html.unescape(text).strip()


def facebook_messenger_send(message):
  if not PAGE_ACCESS_TOKEN or not ADMIN_PSID:
    print(
        "[WARN] Facebook Messenger secrets (PAGE_ACCESS_TOKEN or ADMIN_PSID)"
        " are missing. Skip Messenger send."
    )
    return False

  # Messenger does not support HTML — send plain text only.
  # Hard limit is ~2000 chars; stay safely under it.
  plain = strip_html(message)
  if len(plain) > 1900:
    plain = plain[:1850] + "\n\n... (truncated, see Telegram/GitHub for full)"

  url = (
      "https://graph.facebook.com/v18.0/me/messages"
      f"?access_token={PAGE_ACCESS_TOKEN}"
  )
  payload = {
      "recipient": {"id": ADMIN_PSID},
      "message": {"text": plain},
      "messaging_type": "UPDATE",
  }
  headers = {"Content-Type": "application/json"}
  try:
    r = SESSION.post(url, json=payload, headers=headers, timeout=TIMEOUT)
    if r.status_code >= 400:
      # Log the actual Facebook error body so we can debug token/PSID issues
      print(f"[ERROR] Facebook Messenger HTTP {r.status_code}: {r.text}")
      return False
    print("Naipadala na ang alert sa Facebook Messenger!")
    return True
  except Exception as e:
    print(f"[ERROR] Facebook Messenger send failed: {e}")
    return False


def main():
  seen = load_state()
  all_items = []
  for fetcher in (
      fetch_cheapshark,
      fetch_epic_free_games,
      fetch_github_projects,
      fetch_local_alerts,
  ):
    try:
      all_items.extend(fetcher())
    except Exception as e:
      print(f"[WARN] {fetcher.__name__} failed: {e}")

  fresh = []
  for item in all_items:
    if item["id"] not in seen:
      fresh.append(item)
      seen.add(item["id"])

  save_state(seen)
  fresh = fresh[:MAX_ITEMS_PER_RUN]

  if not fresh:
    print(f"No new qualifying items at {now_pht().isoformat()}")
    return

  lines = [
      f"🔎 FREE MONITOR · {now_pht().strftime('%d %b %Y, %I:%M %p PHT')}"
  ]
  current_category = None
  for item in fresh:
    if item["category"] != current_category:
      current_category = item["category"]
      lines.append("")
      lines.append(current_category)
    lines.append(f"\n<b>{esc(item['title'])}</b>")
    lines.append(esc(item["body"]))
    lines.append(esc(item["url"]))
  message = "\n".join(lines)
  if len(message) > 3900:
    message = (
        message[:3850]
        + "\n\nMore findings may be available in the GitHub Actions log."
    )

  # I-send sa Telegram at Facebook Messenger nang sabay
  telegram_send(message)
  facebook_messenger_send(message)


if __name__ == "__main__":
  main()
