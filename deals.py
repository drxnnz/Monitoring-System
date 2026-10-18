"""CheapShark helpers: price snapshot, 'worth it?' verdict, PHP conversion."""
import difflib
import time
from datetime import datetime, timezone
from urllib.parse import quote, quote_plus

import requests

API = "https://www.cheapshark.com/api/1.0"
HEADERS = {"User-Agent": "FreeMonitor/2.0 (personal project)"}
_fx_cache = {"done": False, "rate": None}


def _get(url, params=None):
  try:
    r = requests.get(url, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()
  except Exception as e:
    print(f"[WARN] CheapShark fetch failed: {url}: {e}")
    return None


def enc_deal_id(deal_id):
  """CheapShark dealIDs come back already percent-encoded. Don't encode twice."""
  return deal_id if "%" in deal_id else quote(deal_id, safe="")


def redirect_url(deal_id):
  return f"https://www.cheapshark.com/redirect?dealID={enc_deal_id(deal_id)}"


def php_rate():
  """USD -> PHP (free, no key). Returns None if unavailable."""
  if _fx_cache["done"]:
    return _fx_cache["rate"]
  _fx_cache["done"] = True
  try:
    r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
    r.raise_for_status()
    _fx_cache["rate"] = float(r.json()["rates"]["PHP"])
  except Exception as e:
    print(f"[WARN] FX rate unavailable: {e}")
  return _fx_cache["rate"]


def money(usd, rate):
  s = f"${usd:.2f}"
  if rate:
    s += f" (≈₱{usd * rate:,.0f})"
  return s


def _int(v):
  try:
    return int(float(v))
  except Exception:
    return None


def _float(v):
  try:
    return float(v)
  except Exception:
    return None


def steam_image(app_id, thumb=None):
  if app_id and str(app_id) not in ("0", "None", ""):
    return (
        f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg"
    )
  return thumb or None


def snapshot(title, normal, sale, rating_text, rating_pct, rating_count,
             metacritic, app_id, thumb, deal_id, low_price=None, low_date=None):
  pct = (normal - sale) / normal * 100 if normal else 0
  rp = _int(rating_pct)
  rc = _int(rating_count)
  if not rc:  # CheapShark uses 0 when there are no Steam reviews
    rp = None
  mc = _int(metacritic)
  return {
      "title": title,
      "normal": normal,
      "sale": sale,
      "pct": pct,
      "rating_text": rating_text if rc else None,
      "rating_pct": rp,
      "rating_count": rc or 0,
      "metacritic": mc if mc else None,
      "app_id": app_id,
      "thumb": thumb,
      "deal_id": deal_id,
      "low_price": low_price,
      "low_date": low_date,
  }


def snapshot_from_list_deal(d):
  """Build a snapshot from one entry of the /deals list + price history."""
  low_price = low_date = None
  game_id = d.get("gameID")
  if game_id:
    info = _get(f"{API}/games", params={"id": game_id})
    if isinstance(info, dict):
      c = info.get("cheapestPriceEver") or {}
      low_price = _float(c.get("price"))
      low_date = _int(c.get("date"))
  return snapshot(
      d.get("title", "Unknown game"),
      float(d.get("normalPrice", 0)),
      float(d.get("salePrice", 0)),
      d.get("steamRatingText"),
      d.get("steamRatingPercent"),
      d.get("steamRatingCount"),
      d.get("metacriticScore"),
      d.get("steamAppID"),
      d.get("thumb"),
      d.get("dealID"),
      low_price,
      low_date,
  )


def snapshot_from_deal_id(deal_id):
  """Used by the 'Worth it ba?' button."""
  data = _get(f"{API}/deals?id={enc_deal_id(deal_id)}")
  if not isinstance(data, dict) or "gameInfo" not in data:
    return None
  gi = data["gameInfo"]
  c = data.get("cheapestPrice") or {}
  return snapshot(
      gi.get("name", "Unknown game"),
      float(gi.get("retailPrice", 0)),
      float(gi.get("salePrice", 0)),
      gi.get("steamRatingText"),
      gi.get("steamRatingPercent"),
      gi.get("steamRatingCount"),
      gi.get("metacriticScore"),
      gi.get("steamAppID"),
      gi.get("thumb"),
      deal_id,
      _float(c.get("price")),
      _int(c.get("date")),
  )


def snapshot_from_title(title):
  """Used when someone types 'worth it ba ang <game>?'."""
  results = _get(f"{API}/games", params={"title": title, "limit": 6})
  if not isinstance(results, list) or not results:
    return None
  names = [r.get("external", "") for r in results]
  best = difflib.get_close_matches(title.lower(), [n.lower() for n in names],
                                   n=1, cutoff=0.0)
  idx = [n.lower() for n in names].index(best[0]) if best else 0
  deal_id = results[idx].get("cheapestDealID")
  if not deal_id:
    return None
  return snapshot_from_deal_id(deal_id)


def verdict(s):
  """Rules-based 'sulit ba?'. Returns (label, [reasons]). Not a human opinion."""
  score = 0
  why = []
  pct, n = s["rating_pct"], s["rating_count"]
  rated = pct is not None and n >= 50
  if not rated:
    why.append("kaunti pa ang Steam reviews, kaya di pa sigurado")
  elif pct >= 90 and n >= 1000:
    score += 3
    why.append(f"{pct}% positive sa {n:,} reviews")
  elif pct >= 80:
    score += 2
    why.append(f"{pct}% positive sa {n:,} reviews")
  elif pct >= 70:
    score += 1
    why.append(f"{pct}% positive lang, may mixed na reviews")
  else:
    score -= 1
    why.append(f"{pct}% positive lang, mababa ang reviews")

  low = s["low_price"]
  if low:
    if s["sale"] <= low * 1.03:
      score += 2
      why.append("pinakamura na ito sa history niya")
    elif s["sale"] <= low * 1.25:
      score += 1
      why.append(f"malapit sa lowest price (${low:.2f})")
    else:
      why.append(f"nagkaroon na ng ${low:.2f} dati, baka bumaba ulit")
  if s["pct"] >= 75:
    score += 1
  if not rated:
    score = min(score, 2)

  if score >= 5:
    label = "🔥 Sulit na sulit"
  elif score >= 3:
    label = "👍 Sulit"
  elif score == 2:
    label = "🤔 Pwede na, depende sa hilig mo"
  else:
    label = "⏳ Hintay muna / skip"
  return label, why


def game_lines(s, rate):
  lines = [
      f"🏷️ Orig: {money(s['normal'], rate)}",
      f"🔻 Discount: -{s['pct']:.0f}%",
      f"✅ Ngayon: {money(s['sale'], rate)}",
  ]
  if s["rating_pct"] is not None:
    r = f"⭐ {s['rating_text'] or 'Steam'} · {s['rating_pct']}% ({s['rating_count']:,} reviews)"
    if s["metacritic"]:
      r += f" · Metacritic {s['metacritic']}"
    lines.append(r)
  if s["low_price"]:
    low = f"📉 Lowest ever: {money(s['low_price'], rate)}"
    if s["sale"] <= s["low_price"] * 1.03:
      low += " · ito na yun! 🎯"
    elif s["low_date"]:
      low += " · " + datetime.fromtimestamp(
          s["low_date"], timezone.utc).strftime("%b %Y")
    lines.append(low)
  label, _ = verdict(s)
  lines.append(f"🧠 {label}")
  return lines


def worth_reply(s, rate):
  """Full answer for 'worth it ba?'. Returns plain text."""
  label, why = verdict(s)
  out = [f"🎮 {s['title']}", ""]
  out += game_lines(s, rate)[:-1]  # verdict is spelled out below
  out += ["", f"🧠 Verdict: {label}"]
  out += [f"• {w}" for w in why]
  out += ["", "Base lang ito sa reviews at price history, di sa personal na "
          "laro. Check mo rin kung gusto mo yung genre 😅"]
  return "\n".join(out)
