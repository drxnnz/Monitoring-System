import os
from flask import Flask, request
import requests

app = Flask(__name__)

# Kukunin nito ang mga tokens mula sa environment variables (na galing sa GitHub/Render secrets)
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
  # 1. Webhook Verification (Handshake ni Facebook)
  if request.method == "GET":
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token:
      if mode == "subscribe" and token == VERIFY_TOKEN:
        print("WEBHOOK_VERIFIED")
        return challenge, 200
      else:
        return "Verification failed", 403
    return "Hello world", 200

  # 2. Pagdating ng Mensahe mula kay User
  elif request.method == "POST":
    data = request.json
    if data.get("object") == "page":
      for entry in data.get("entry", []):
        for messaging_event in entry.get("messaging", []):
          if messaging_event.get("message"):
            sender_id = messaging_event["sender"]["id"]
            message_text = messaging_event["message"].get("text")

            if message_text:
              # Dito mo ikokonekta ang logic ng DiscoveryRadar bot mo
              handle_message(sender_id, message_text)

      return "EVENT_RECEIVED", 200
    return 404


def handle_message(recipient_id, message_text):
  # Pansamantalang Echo reply muna para masigurong gumagana
  response_text = f"Nakuha ko ang mensahe mo: '{message_text}'. Paparating na ang DiscoveryRadar updates mo!"

  payload = {
      "recipient": {"id": recipient_id},
      "message": {"text": response_text},
  }
  headers = {"Content-Type": "application/json"}
  url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"

  requests.post(url, json=payload, headers=headers)


if __name__ == "__main__":
  port = int(os.environ.get("PORT", 5000))
  app.run(host="0.0.0.0", port=port)
