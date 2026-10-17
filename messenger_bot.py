"""Messenger webhook: onboarding, preferences, 'worth it ba?', updates."""
import hashlib
import hmac
import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, request

import deals
import messenger
import store
import tg
from config import KIND_PREF, PREFS
from nlu import PASOK_WORDS, WORTH_PHRASES, extract_game_title, has_word

app = Flask(__name__)
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
_seen_mids = deque(maxlen=500)
_seen_updates = deque(maxlen=500)
_pool = ThreadPoolExecutor(max_workers=4)

# ---------- replies ----------


def main_menu_qr(pending=0):
  return [("📰 Ano update?", "UPDATES"), ("🆓 Libreng games", "FREE_NOW"),
          ("🏫 May pasok?", "PASOK")]


def welcome(psid, user):
  """No quiz, no settings: everything is automatic."""
  store.subscribe_all(user)
  store.save_user(user)
  messenger.send_text(
      psid,
      "Kumusta! 👋 Ako yung update bot para sa game deals, libreng games, "
      "AI/GitHub finds, at BSU/Malolos alerts. Automatic na lahat.\n\n"
      "Pindutin lang ang buttons sa baba para mag-refresh, o tanungin mo "
      "ako: “worth it ba ang Hollow Knight?”\n\n"
      "⚠️ Rule ng Messenger: makakapag-push lang ako within 24 hours mula "
      "sa huli mong chat. Kapag lumampas, iipunin ko muna, tapos i-tap mo "
      "lang ang “Ano update?” para makuha ang na-miss mo.",
      main_menu_qr())
  show_updates(psid, user, intro="Eto muna ang pinakabago:")


def show_updates(psid, user, intro=None):
  items, rest = store.pop_pending(psid, 5)
  from_queue = bool(items)
  if not items:
    kinds = [k for k, p in KIND_PREF.items() if p in user["prefs"]]
    items = store.get_recent(limit=5, kinds=kinds or None)
  if not items:
    messenger.send_text(
        psid, "Wala pang bagong na-detect sa ngayon. Sasabihan kita pag meron!",
        main_menu_qr())
    return
  if intro:
    messenger.send_text(psid, intro)
  for it in items:
    messenger.send_item(psid, it)
  tail = (f"May {rest} pa na naka-queue." if from_queue and rest
          else "Yan muna ang pinakabago.")
  qr = main_menu_qr()
  if from_queue and rest:
    qr = [("📰 Dagdag pa", "UPDATES")] + qr
  messenger.send_text(psid, tail, qr)


def show_free_now(psid):
  import monitor
  items = monitor.fetch_epic_free_games()
  if not items:
    messenger.send_text(psid, "Walang active na libreng Epic game ngayon.",
                        main_menu_qr())
    return
  for it in items:
    it.pop("_build", None)
    messenger.send_item(psid, it)
  messenger.send_text(psid, "Claim mo na habang libre pa! 🏃", main_menu_qr())


def show_pasok(psid, user=None):
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
    messenger.send_text(
        psid, "Wala akong na-detect na suspension o weather alert para sa "
        "Malolos/BulSU ngayon. Auto-detect lang ako mula sa news at feeds, "
        "kaya i-check pa rin ang official page ng BulSU/LGU para sigurado.",
        main_menu_qr())
    return
  for it in items:
    it.pop("_build", None)
    messenger.send_item(psid, it)
  messenger.send_text(psid, "Auto-detect lang ito, i-confirm sa official "
                      "page ng BulSU/LGU.", main_menu_qr())


def answer_worth(psid, user, snap):
  if not snap:
    messenger.send_text(
        psid,
        "Hindi ko mahanap yung game na yan sa price database ko 😅 "
        "Subukan mo yung eksaktong title, hal. “worth it ba ang Hades?”",
        main_menu_qr())
    return
  rate = deals.php_rate()
  img = deals.steam_image(snap["app_id"], snap["thumb"])
  if img:
    messenger.send_image(psid, img)
  buttons = []
  if snap.get("deal_id"):
    buttons.append({"type": "web_url", "title": "🔗 Buksan",
                    "url": deals.redirect_url(snap["deal_id"])})
  text = deals.worth_reply(snap, rate)
  if buttons:
    messenger.send_buttons(psid, text, buttons)
  else:
    messenger.send_text(psid, text)
  user["last_game_deal"] = snap.get("deal_id")
  store.save_user(user)
  messenger.send_text(psid, "May iba ka pa bang tatanungin?", main_menu_qr())


def handle_worth_text(psid, user, text):
  title = extract_game_title(text)
  if title:
    answer_worth(psid, user, deals.snapshot_from_title(title))
  elif user.get("last_game_deal"):
    answer_worth(psid, user,
                 deals.snapshot_from_deal_id(user["last_game_deal"]))
  else:
    messenger.send_text(
        psid, "Anong game? Type mo lang, hal. “worth it ba ang Hades?”")


# ---------- router ----------


def handle_event(psid, text=None, payload=None):
  user = store.touch_user(psid)  # reopens the 24h window
  low = (text or "").lower().strip()

  if payload:
    if payload == "GET_STARTED":
      return welcome(psid, user)
    if payload == "PASOK":
      return show_pasok(psid, user)
    if payload == "UPDATES":
      return show_updates(psid, user)
    if payload == "FREE_NOW":
      return show_free_now(psid)
    if payload.startswith("WORTH|"):
      return answer_worth(psid, user,
                          deals.snapshot_from_deal_id(payload.split("|", 1)[1]))
    if payload == "STOP":
      user["prefs"] = []
      store.save_user(user)
      return messenger.send_text(
          psid, "Okay, ihihinto ko na ang updates. Type “hi” anytime kung "
          "gusto mo ulit 👋")

  if not low:
    return None
  new = not user["onboarded"] and not user["prefs"]
  if new:  # first contact: subscribe silently, whatever they typed
    store.subscribe_all(user)
    store.save_user(user)
  if has_word(low, ["stop", "unsubscribe", "tigil", "huwag na", "wag na"]):
    return handle_event(psid, payload="STOP")
  if has_word(low, PASOK_WORDS):
    return show_pasok(psid, user)
  if any(p in low for p in WORTH_PHRASES):
    return handle_worth_text(psid, user, text)
  if has_word(low, ["settings", "setting", "preferences", "menu", "pili"]):
    return messenger.send_text(psid, "Eto ang pwede mong i-tap 👇",
                               main_menu_qr())
  if has_word(low, ["free", "libre", "epic"]):
    return show_free_now(psid)
  if has_word(low, ["update", "updates", "balita", "bago", "latest", "news"]):
    return show_updates(psid, user)
  if has_word(low, ["hi", "hello", "hey", "yo", "kumusta", "musta"]):
    if new:
      return welcome(psid, user)
    n = store.pending_count(psid)
    note = f"\n\n📬 May {n} bagong na-miss ka. Tap “Ano update?”" if n else ""
    return messenger.send_text(
        psid, "Uy! Ano kailangan mo ngayon?" + note, main_menu_qr())
  if new:
    return welcome(psid, user)
  return messenger.send_text(
      psid,
      "Di ko pa gets yan 😅 Pwede mo akong tanungin ng “worth it ba ang "
      "<game>?”, o pindutin ang options sa baba.", main_menu_qr())


# ---------- webhook ----------


def _valid_signature(req):
  secret = os.getenv("APP_SECRET", "").strip()
  if not secret:
    return True  # set APP_SECRET in production
  sig = req.headers.get("X-Hub-Signature-256", "")
  digest = hmac.new(secret.encode(), req.get_data(), hashlib.sha256).hexdigest()
  return hmac.compare_digest(sig, f"sha256={digest}")


@app.route("/", methods=["GET"])
def health():
  return f"ok | store: {store.storage_mode()}", 200


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
  if request.method == "GET":
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token and token == VERIFY_TOKEN:
      return challenge, 200
    return "Verification failed", 403

  if not _valid_signature(request):
    return "Bad signature", 403
  data = request.get_json(silent=True) or {}
  if data.get("object") != "page":
    return "Not found", 404
  for entry in data.get("entry", []):
    for ev in entry.get("messaging", []):
      psid = (ev.get("sender") or {}).get("id")
      if not psid:
        continue
      try:
        if ev.get("postback"):
          handle_event(psid, payload=ev["postback"].get("payload"))
        elif ev.get("message") and not ev["message"].get("is_echo"):
          msg = ev["message"]
          mid = msg.get("mid")
          if mid in _seen_mids:  # Meta retries slow webhooks
            continue
          _seen_mids.append(mid)
          qr = (msg.get("quick_reply") or {}).get("payload")
          handle_event(psid, text=msg.get("text"), payload=qr)
      except Exception as e:  # never let one bad event break the webhook
        print(f"[ERROR] handling event for {psid}: {e}")
  return "EVENT_RECEIVED", 200


@app.route("/tgstatus", methods=["GET"])
def tg_status():
  """Why is Telegram not replying? Open this URL in a browser."""
  info = tg.api("getWebhookInfo").get("result") or {}
  return {
      "token_set": bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip()),
      "webhook_set": bool(info.get("url")),
      "webhook_is_this_server": (info.get("url") or "").endswith("/telegram"),
      "pending_updates": info.get("pending_update_count"),
      "last_error": info.get("last_error_message"),
      "store": store.storage_mode(),
  }, 200


@app.route("/telegram", methods=["POST"])
def telegram_webhook():
  secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
  if secret and request.headers.get(
      "X-Telegram-Bot-Api-Secret-Token", "") != secret:
    return "Forbidden", 403
  update = request.get_json(silent=True) or {}
  upd_id = update.get("update_id")
  if upd_id is not None:  # Telegram retries slow webhooks: skip repeats
    if upd_id in _seen_updates:
      return "ok", 200
    _seen_updates.append(upd_id)
  if os.getenv("PYTEST"):
    _process_tg(update)
  else:  # answer Telegram right away; do the slow work in the background
    _pool.submit(_process_tg, update)
  return "ok", 200


def _process_tg(update):
  try:
    tg.handle_update(update)
  except Exception as e:  # never let one bad update kill the worker
    print(f"[ERROR] Telegram update failed: {e}")


def startup():
  """Registers webhooks/menus once when the server boots (best effort)."""
  print(f"[setup] Storage: {store.storage_mode()}")
  if not store.is_shared_store():
    print("[WARN] No Upstash set: user choices are lost on restart/sleep, "
          "so people get asked to choose again.")
  try:
    base = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
            or "").strip()
    if os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and base:
      res = tg.configure_webhook(
          base, os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip() or None)
      print(f"[setup] Telegram webhook -> {base}/telegram : {res}")
    elif os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
      print("[setup] No PUBLIC_URL/RENDER_EXTERNAL_URL; Telegram webhook "
            "not registered.")
    if os.getenv("PAGE_ACCESS_TOKEN", "").strip():
      messenger.configure_profile()
  except Exception as e:
    print(f"[WARN] startup setup failed: {e}")


if os.getenv("RUN_STARTUP_SETUP", "1") == "1" and not os.getenv("PYTEST"):
  import threading
  threading.Thread(target=startup, daemon=True).start()


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
