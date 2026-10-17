import os
from flask import Flask, request
import requests

app = Flask(__name__)

PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
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

  elif request.method == "POST":
    data = request.json
    if data.get("object") == "page":
      for entry in data.get("entry", []):
        for messaging_event in entry.get("messaging", []):
          if messaging_event.get("message"):
            sender_id = messaging_event["sender"]["id"]
            message_text = messaging_event["message"].get("text")

            if message_text:
              handle_message(sender_id, message_text)

      return "EVENT_RECEIVED", 200
    return 404


def handle_message(recipient_id, message_text):
  # Dito natin ginawang mas natural ang reply
  text_lower = message_text.lower()

  if "hi" in text_lower or "hello" in text_lower or "kumusta" in text_lower:
    response_text = (
        "Uy, hello! Nakuha ko 'yung mensahe mo. Ano ba ang maitutulong ko"
        " ngayon? 😎"
    )
  else:
    response_text = (
        f"Nasa-save ko na sinabi mo: \"{message_text}\". Sandali lang, "
        "inaayos ko pa 'yung iba pang features nito!"
    )

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
