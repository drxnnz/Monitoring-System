"""Thin wrapper around the Messenger Send API."""
import os

import requests


def _graph_url():
  v = os.getenv("GRAPH_VERSION", "v23.0")
  return f"https://graph.facebook.com/{v}/me/messages"


def _send(psid, message, messaging_type="RESPONSE"):
  """Returns 'ok', 'window' (outside the 24h window) or 'fail'."""
  token = os.getenv("PAGE_ACCESS_TOKEN", "").strip()
  if not token:
    print("[WARN] PAGE_ACCESS_TOKEN missing; Messenger send skipped.")
    return "fail"
  payload = {
      "recipient": {"id": psid},
      "messaging_type": messaging_type,
      "message": message,
  }
  try:
    r = requests.post(
        _graph_url(), params={"access_token": token}, json=payload, timeout=15
    )
  except Exception as e:
    print(f"[ERROR] Messenger request failed: {e}")
    return "fail"
  if r.status_code < 400:
    return "ok"
  print(f"[ERROR] Messenger HTTP {r.status_code}: {r.text[:300]}")
  try:
    err = r.json().get("error", {})
  except Exception:
    err = {}
  if err.get("code") == 10 or err.get("error_subcode") in (2018278, 2534022):
    return "window"
  return "fail"


def send_text(psid, text, quick_replies=None, messaging_type="RESPONSE"):
  msg = {"text": text[:1900]}
  if quick_replies:
    msg["quick_replies"] = [
        {"content_type": "text", "title": t[:20], "payload": p}
        for t, p in quick_replies[:13]
    ]
  return _send(psid, msg, messaging_type)


def send_image(psid, url, messaging_type="RESPONSE"):
  msg = {"attachment": {"type": "image",
                        "payload": {"url": url, "is_reusable": False}}}
  return _send(psid, msg, messaging_type)


def send_buttons(psid, text, buttons, messaging_type="RESPONSE"):
  msg = {"attachment": {"type": "template", "payload": {
      "template_type": "button", "text": text[:640], "buttons": buttons[:3]}}}
  return _send(psid, msg, messaging_type)


def item_text(item):
  head = f"{item.get('category', '')}\n{item['title']}".strip()
  return head + "\n" + "\n".join(item.get("lines", []))


def item_buttons(item):
  buttons = []
  if item.get("url"):
    buttons.append({"type": "web_url", "url": item["url"], "title": "🔗 Buksan"})
  deal_id = (item.get("meta") or {}).get("deal_id")
  if item.get("kind") == "game" and deal_id:
    buttons.append({"type": "postback", "title": "🤔 Worth it ba?",
                    "payload": f"WORTH|{deal_id}"})
  return buttons


def send_item(psid, item, messaging_type="RESPONSE"):
  """Picture first (if any), then a compact text card with buttons."""
  if item.get("image"):
    status = send_image(psid, item["image"], messaging_type)
    if status == "window":
      return status
  buttons = item_buttons(item)
  if buttons:
    return send_buttons(psid, item_text(item), buttons, messaging_type)
  return send_text(psid, item_text(item), messaging_type=messaging_type)
