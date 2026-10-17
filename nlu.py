"""Tiny Taglish intent helpers shared by the Messenger and Telegram bots."""
import re

WORTH_PHRASES = [
    "worth it", "worth", "sulit", "okay ba", "ok ba", "maganda ba",
    "bilhin ba", "bili ba", "pasok ba", "recommend", "ganda ba",
]
# Class/work suspension questions. "pasok ba" alone is NOT here on purpose:
# it also means "is this game a good fit?" (see WORTH_PHRASES).
PASOK_WORDS = ["may pasok", "walang pasok", "pasok bukas", "pasok ngayon",
               "suspension", "suspend", "suspended", "class suspension"]
STOPWORDS = {
    "ba", "ang", "yung", "yong", "nung", "na", "po", "ito", "to", "sa", "ng",
    "mga", "is", "the", "a", "bang", "kaya", "naman", "pa", "din", "rin",
    "ngayon", "kung", "if", "may", "ko", "mo", "bilhin", "bumili", "buy",
    "this", "that", "dis", "ba?", "it", "ay", "si", "ni", "para",
}


def has_word(text, words):
  return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def extract_game_title(text):
  t = text.lower()
  for p in sorted(WORTH_PHRASES, key=len, reverse=True):
    t = t.replace(p, " ")
  t = re.sub(r"[?!.,]", " ", t)
  tokens = [w for w in t.split() if w not in STOPWORDS]
  if tokens and tokens[0] in ("game", "laro"):
    tokens = tokens[1:]
  return " ".join(tokens).strip()
