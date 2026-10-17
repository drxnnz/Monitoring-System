"""Run once: sets Get Started button, greeting and persistent menu."""
import os
import sys

import requests

token = os.getenv("PAGE_ACCESS_TOKEN", "").strip()
if not token:
  sys.exit("Set PAGE_ACCESS_TOKEN first.")
v = os.getenv("GRAPH_VERSION", "v23.0")
body = {
    "get_started": {"payload": "GET_STARTED"},
    "greeting": [{"locale": "default", "text": (
        "Game deals, libreng games, AI/GitHub finds at BSU/Malolos alerts. "
        "Pindutin ang Get Started 👇")}],
    "persistent_menu": [{
        "locale": "default",
        "composer_input_disabled": False,
        "call_to_actions": [
            {"type": "postback", "title": "📰 Ano bago?", "payload": "UPDATES"},
            {"type": "postback", "title": "🆓 Libreng games",
             "payload": "FREE_NOW"},
            {"type": "postback", "title": "⚙️ Settings", "payload": "SETTINGS"},
        ],
    }],
}
r = requests.post(
    f"https://graph.facebook.com/{v}/me/messenger_profile",
    params={"access_token": token}, json=body, timeout=15)
print(r.status_code, r.text)
