"""Telegram bot: replies to anyone, onboarding, 'worth it ba?', push helpers."""
import html
import os

import requests

import deals
import store
from config import KIND_PREF, PREFS
from nlu import PASOK_WORDS, WORTH_PHRASES, extract_game_title, has_word


def allowed_chat_ids():
  """The chat(s) in TELEGRAM_CHAT_ID (comma separated)."""
  return [c.strip() for c in os.getenv("TELEGRAM_CHAT_ID", "").split(",")
          if c.strip()]


def single_chat_mode():
  """TG_SINGLE_CHAT=1: only the chat in TELEGRAM_CHAT_ID is served. No
  per-user subscriptions, no onboarding, far fewer Redis/API calls."""
  return (os.getenv("TG_SINGLE_CHAT", "").strip() == "1"
          and bool(allowed_chat_ids()))


def esc(s):
  return html.escape(str(s or ""), quote=False)


def uid(chat_id):
  return f"tg:{chat_id}"


# ---------- API ----------


def api(method, **payload):
  """Returns the JSON dict, or {'ok': False, 'status': code} on failure."""
  token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
  if not token:
    return {"ok": False, "status": 0}
  try:
    r = requests.post(
        f"https://api.telegram.org/bot{token}/{method}", json=payload,
        timeout=15)
  except Exception as e:
    print(f"[ERROR] Telegram {method} failed: {e}")
    return {"ok": False, "status": 0}
  if r.status_code >= 400:
    print(f"[WARN] Telegram {method} HTTP {r.status_code}: {r.text[:200]}")
    return {"ok": False, "status": r.status_code}
  try:
    return r.json()
  except Exception:
    return {"ok": True}


def _send(chat_id, text, markup=None, photo=None):
  """Photo+caption when possible, else plain message. True/False/'blocked'."""
  extra = {"reply_markup": markup} if markup else {}
  if photo and len(text) <= 1000:
    res = api("sendPhoto", chat_id=chat_id, photo=photo, caption=text,
              parse_mode="HTML", **extra)
    if res.get("ok"):
      return True
    if res.get("status") == 403:
      return "blocked"
  res = api("sendMessage", chat_id=chat_id, text=text[:4000],
            parse_mode="HTML", disable_web_page_preview=True, **extra)
  if res.get("ok"):
    return True
  return "blocked" if res.get("status") == 403 else False


# ---------- keyboards ----------


def menu_rows():
  return [
      [{"text": "📰 Ano update?", "callback_data": "UPDATES"},
       {"text": "🆓 Libreng games", "callback_data": "FREE_NOW"}],
      [{"text": "🏫 May pasok?", "callback_data": "PASOK"}],
  ]


def menu_markup():
  return {"inline_keyboard": menu_rows()}


def item_markup(item):
  row = []
  if item.get("url"):
    row.append({"text": "🔗 Buksan", "url": item["url"]})
  deal_id = (item.get("meta") or {}).get("deal_id")
  if item.get("kind") == "game" and deal_id:
    row.append({"text": "🤔 Worth it ba?", "callback_data": f"WORTH|{deal_id}"})
  return {"inline_keyboard": [row]} if row else None


# ---------- items ----------


def item_html(item):
  out = f"{esc(item.get('category', ''))}\n<b>{esc(item['title'])}</b>\n"
  out += "\n".join(esc(x) for x in item.get("lines", []))
  return out.strip()


def send_item(chat_id, item):
  """Used by the monitor and the bot. True / False / 'blocked'."""
  res = _send(chat_id, item_html(item), item_markup(item), item.get("image"))
  if res is True:
    _remember_alert(chat_id, item)
  return res


def _remember_alert(chat_id, item):
  """So a plain "worth it ba?" right after an alert knows which game."""
  deal_id = (item.get("meta") or {}).get("deal_id")
  if item.get("kind") != "game" or not deal_id:
    return
  try:
    user = store.get_user(uid(chat_id))
    user["last_game_deal"] = deal_id
    store.save_user(user)
  except Exception as e:  # never break delivery because of this
    print(f"[WARN] could not remember alert for {chat_id}: {e}")


def reply_context(reply):
  """What alert is the person replying to? Works with the bot's own messages
  (the 'Worth it ba?' button's deal id, or the title in the text/caption)."""
  if not reply:
    return None
  ctx = {"deal_id": None, "title": None, "free": False, "text": ""}
  kb = (reply.get("reply_markup") or {}).get("inline_keyboard") or []
  for row in kb:
    for btn in row:
      data = btn.get("callback_data") or ""
      if data.startswith("WORTH|"):
        ctx["deal_id"] = data.split("|", 1)[1]
  text = reply.get("text") or reply.get("caption") or ""
  ctx["text"] = text
  lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
  if len(lines) >= 2:
    ctx["title"] = lines[1]
    ctx["free"] = "FREE" in lines[0].upper()
  if not (ctx["deal_id"] or ctx["title"]):
    return None
  return ctx


# ---------- conversation ----------


def say(chat_id, text, markup=None):
  return _send(chat_id, text, markup)


def welcome(chat_id, user):
  """No quiz, no settings: everything is automatic."""
  store.subscribe_all(user)
  store.save_user(user)
  say(chat_id,
      "Kumusta! 👋 Ako yung update bot para sa game deals, libreng games, "
      "AI/GitHub finds, at BSU/Malolos alerts. Automatic na lahat, "
      "ipapadala ko dito pag may bago.\n\n"
      "Pindutin lang ang buttons sa baba kung gusto mong i-refresh, o "
      "tanungin mo ako: “worth it ba ang Hollow Knight?”",
      menu_markup())
  show_updates(chat_id, user, intro="Eto muna ang pinakabago:", limit=3)


def show_updates(chat_id, user, intro=None, limit=5):
  kinds = [k for k, p in KIND_PREF.items() if p in user["prefs"]]
  items = store.get_recent(limit=limit, kinds=kinds or None)
  if not items:
    return say(chat_id, "Wala pang bagong na-detect sa ngayon. Sasabihan "
               "kita pag meron!", menu_markup())
  if intro:
    say(chat_id, esc(intro))
  for it in items:
    send_item(chat_id, it)
  say(chat_id, "Yan muna ang pinakabago.", menu_markup())


def show_free_now(chat_id):
  import monitor  # lazy: monitor imports this module
  items = monitor.fetch_epic_free_games()
  if not items:
    return say(chat_id, "Walang active na libreng Epic game ngayon.",
               menu_markup())
  for it in items:
    it.pop("_build", None)
    send_item(chat_id, it)
  say(chat_id, "Claim mo na habang libre pa! 🏃", menu_markup())


def answer_worth(chat_id, user, snap):
  if not snap:
    return say(
        chat_id,
        "Hindi ko mahanap yung game na yan sa price database ko 😅 "
        "Subukan mo yung eksaktong title, hal. “worth it ba ang Hades?”",
        menu_markup())
  rate = deals.php_rate()
  rows = []
  if snap.get("deal_id"):
    rows.append([{"text": "🔗 Buksan",
                  "url": deals.redirect_url(snap["deal_id"])}])
  rows += menu_rows()
  _send(chat_id, esc(deals.worth_reply(snap, rate)),
        {"inline_keyboard": rows},
        deals.steam_image(snap["app_id"], snap["thumb"]))
  user["last_game_deal"] = snap.get("deal_id")
  store.save_user(user)


def show_pasok(chat_id, user=None):
  """'May pasok ba?': fresh BSU/Malolos suspension + weather alerts."""
  import monitor
  items = []
  try:
    items = monitor.fetch_local_alerts()[:3]
  except Exception as e:
    print(f"[WARN] pasok lookup failed: {e}")
  items += [i for i in store.get_recent(limit=2, kinds=["memo"])
            if i.get("id") not in {x.get("id") for x in items}]
  if not items:
    return say(chat_id, "Wala akong na-detect na suspension o weather alert "
               "para sa Malolos/BulSU ngayon. Auto-detect lang ako mula sa "
               "news at feeds, kaya i-check pa rin ang official page ng "
               "BulSU/LGU para sigurado.", menu_markup())
  for it in items:
    it.pop("_build", None)
    send_item(chat_id, it)
  say(chat_id, "Auto-detect lang ito, i-confirm sa official page ng "
      "BulSU/LGU.", menu_markup())


def answer_free(chat_id, ctx):
  """'Worth it ba?' on a free-to-keep alert."""
  title = ctx["title"] or "Larong to"
  out = [f"🆓 {title}", "",
         "Libre siya ngayon at keep forever, kaya wala kang mawawala "
         "basta ma-claim mo bago mag-deadline."]
  for ln in ctx["text"].split("\n"):
    if "Claim hanggang" in ln:
      out.append(ln.strip())
  try:  # best effort: Steam reviews if the same game is on CheapShark
    snap = deals.snapshot_from_title(title)
  except Exception:
    snap = None
  if (snap and snap.get("rating_pct") is not None
      and snap["title"].lower().strip() == title.lower().strip()):
    out.append(f"⭐ Sa Steam: {snap['rating_pct']}% positive "
               f"({snap['rating_count']:,} reviews)")
  out += ["", "Check mo na lang kung gusto mo yung genre 😅"]
  return say(chat_id, esc("\n".join(out)), menu_markup())


def handle_worth_text(chat_id, user, text, ctx=None):
  title = extract_game_title(text)
  if title:
    return answer_worth(chat_id, user, deals.snapshot_from_title(title))
  if ctx:  # replying to an alert: that's the game they mean
    if ctx["deal_id"]:
      return answer_worth(chat_id, user,
                          deals.snapshot_from_deal_id(ctx["deal_id"]))
    if ctx["free"]:
      return answer_free(chat_id, ctx)
    if ctx["title"]:
      return answer_worth(chat_id, user,
                          deals.snapshot_from_title(ctx["title"]))
  if user.get("last_game_deal"):
    return answer_worth(chat_id, user,
                        deals.snapshot_from_deal_id(user["last_game_deal"]))
  say(chat_id, "Anong game? Type mo lang, hal. “worth it ba ang Hades?” "
      "o /worth Hades")


def stop(chat_id, user):
  user["prefs"] = []
  store.save_user(user)
  say(chat_id, "Okay, ihihinto ko na ang updates. Type /start kung gusto "
      "mo ulit 👋")


HELP = (
    "Ano kaya ko:\n"
    "• /updates — pinakabagong deals at alerts\n"
    "• /free — libreng Epic games ngayon\n"
    "• /pasok — may suspension ba?\n"
    "• /worth &lt;game&gt; — sulit ba? (hal. /worth Hades)\n"
    "• /stop — itigil ang updates\n\n"
    "Pwede mo rin i-type lang: “worth it ba ang Hollow Knight?”"
)


def handle_action(chat_id, data, message_id=None):
  user = store.get_user(uid(chat_id))
  if data == "UPDATES":
    return show_updates(chat_id, user)
  if data == "FREE_NOW":
    return show_free_now(chat_id)
  if data == "PASOK":
    return show_pasok(chat_id, user)
  if data.startswith("WORTH|"):
    return answer_worth(chat_id, user,
                        deals.snapshot_from_deal_id(data.split("|", 1)[1]))
  if data == "STOP":
    return stop(chat_id, user)
  return say(chat_id, "Eto ang pwede mong i-tap 👇", menu_markup())


def handle_text(chat_id, text, private=True, reply=None):
  user = store.get_user(uid(chat_id))
  raw = (text or "").strip()
  low = raw.lower()
  ctx = reply_context(reply)
  if not low:
    return
  new = (private and not user["onboarded"] and not user["prefs"]
         and not single_chat_mode())
  if new:  # first contact: subscribe silently, whatever they typed
    store.subscribe_all(user)
    store.save_user(user)

  if low.startswith("/"):
    cmd, _, args = low.partition(" ")
    cmd = cmd.split("@")[0]
    args = raw.partition(" ")[2].strip()
    if cmd == "/start":
      if private:
        return welcome(chat_id, user)
      return say(chat_id, "Hi! Gamitin mo ako dito: /worth &lt;game&gt;, "
                 "/updates, /free, /pasok. Para sa personal na updates, i-message "
                 "mo ako nang private 🙂", menu_markup())
    if cmd == "/ping":
      return say(chat_id, "Gising ako ✅")
    if cmd == "/help":
      return say(chat_id, HELP, menu_markup())
    if cmd == "/updates":
      return show_updates(chat_id, user)
    if cmd == "/free":
      return show_free_now(chat_id)
    if cmd in ("/settings", "/menu"):
      return say(chat_id, "Eto ang pwede mong i-tap 👇", menu_markup())
    if cmd == "/pasok":
      return show_pasok(chat_id, user)
    if cmd == "/stop":
      return stop(chat_id, user)
    if cmd == "/worth":
      return handle_worth_text(chat_id, user, args or "worth it", ctx)
    return say(chat_id, HELP, menu_markup())


  if has_word(low, ["stop", "unsubscribe", "tigil"]):
    return stop(chat_id, user)
  if has_word(low, PASOK_WORDS):
    return show_pasok(chat_id, user)
  if any(p in low for p in WORTH_PHRASES):
    return handle_worth_text(chat_id, user, raw, ctx)
  if has_word(low, ["settings", "setting", "preferences", "menu", "pili"]):
    return say(chat_id, "Eto ang pwede mong i-tap 👇", menu_markup())
  if has_word(low, ["free", "libre", "epic"]):
    return show_free_now(chat_id)
  if has_word(low, ["update", "updates", "balita", "bago", "latest", "news"]):
    return show_updates(chat_id, user)
  if has_word(low, ["hi", "hello", "hey", "yo", "kumusta", "musta"]):
    if new:
      return welcome(chat_id, user)
    return say(chat_id, "Uy! Ano kailangan mo ngayon?", menu_markup())
  if new:
    return welcome(chat_id, user)
  if private:
    return say(chat_id, "Di ko pa gets yan 😅 Subukan: “worth it ba ang "
               "<game>?” o pindutin ang options sa baba.".replace(
                   "<game>", "&lt;game&gt;"), menu_markup())


def handle_update(update):
  cq = update.get("callback_query")
  if cq:
    api("answerCallbackQuery", callback_query_id=cq.get("id"))
    msg = cq.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    if single_chat_mode() and str(chat_id) not in allowed_chat_ids():
      return
    if chat_id and cq.get("data"):
      handle_action(chat_id, cq["data"], msg.get("message_id"))
    return
  msg = update.get("message")
  if not msg:
    return
  chat = msg.get("chat") or {}
  if chat.get("id") is None or msg.get("from", {}).get("is_bot"):
    return
  cmd = (msg.get("text") or "").strip().lower().split(" ")[0].split("@")[0]
  if cmd in ("/id", "/ping"):  # diagnostics: work in any chat
    ok = (not single_chat_mode()) or str(chat["id"]) in allowed_chat_ids()
    note = "" if ok else "\n⚠️ Wala ang chat na ito sa TELEGRAM_CHAT_ID."
    return say(chat["id"], f"Gising ako ✅\nChat ID nito: "
               f"<code>{chat['id']}</code>{note}")
  if single_chat_mode() and str(chat["id"]) not in allowed_chat_ids():
    return
  handle_text(chat["id"], msg.get("text"),
              private=chat.get("type") == "private",
              reply=msg.get("reply_to_message"))


# ---------- one-time setup (runs at server start) ----------


def configure_webhook(base_url, secret=None):
  body = {"url": base_url.rstrip("/") + "/telegram",
          "allowed_updates": ["message", "callback_query"]}
  if secret:
    body["secret_token"] = secret
  res = api("setWebhook", **body)
  api("setMyCommands", commands=[
      {"command": "updates", "description": "Pinakabagong deals at alerts"},
      {"command": "free", "description": "Libreng Epic games ngayon"},
      {"command": "worth", "description": "Sulit ba ang isang game?"},
      {"command": "pasok", "description": "May suspension ba?"},
      {"command": "stop", "description": "Itigil ang updates"},
  ])
  return res
