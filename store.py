"""Tiny key-value store shared by the Actions monitor and the webhook bot.

Uses Upstash Redis (free tier, REST API) when UPSTASH_REDIS_REST_URL and
UPSTASH_REDIS_REST_TOKEN are set. Otherwise falls back to a local JSON file,
which is fine for testing but is NOT shared between GitHub Actions and your
webhook host.
"""
import json
import os
import time

import requests

from config import PREFS


class RedisBackend:
  def __init__(self, url, token):
    self.url = url.rstrip("/")
    self.token = token

  def _cmd(self, *cmd):
    r = requests.post(
        self.url,
        json=list(cmd),
        headers={"Authorization": f"Bearer {self.token}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json().get("result")

  def get(self, key):
    return self._cmd("GET", key)

  def set(self, key, value):
    self._cmd("SET", key, value)

  def sadd(self, key, member):
    self._cmd("SADD", key, member)

  def smembers(self, key):
    return self._cmd("SMEMBERS", key) or []

  def rpush(self, key, value):
    self._cmd("RPUSH", key, value)

  def lrange(self, key):
    return self._cmd("LRANGE", key, 0, -1) or []

  def ltrim_last(self, key, n):
    self._cmd("LTRIM", key, -n, -1)

  def delete(self, key):
    self._cmd("DEL", key)


class FileBackend:
  def __init__(self, path):
    self.path = path

  def _load(self):
    try:
      with open(self.path, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception:
      return {}

  def _save(self, data):
    with open(self.path, "w", encoding="utf-8") as f:
      json.dump(data, f)

  def get(self, key):
    return self._load().get(key)

  def set(self, key, value):
    d = self._load()
    d[key] = value
    self._save(d)

  def sadd(self, key, member):
    d = self._load()
    s = set(d.get(key, []))
    s.add(member)
    d[key] = sorted(s)
    self._save(d)

  def smembers(self, key):
    return self._load().get(key, [])

  def rpush(self, key, value):
    d = self._load()
    d.setdefault(key, []).append(value)
    self._save(d)

  def lrange(self, key):
    return self._load().get(key, [])

  def ltrim_last(self, key, n):
    d = self._load()
    d[key] = d.get(key, [])[-n:]
    self._save(d)

  def delete(self, key):
    d = self._load()
    d.pop(key, None)
    self._save(d)


def backend():
  url = os.getenv("UPSTASH_REDIS_REST_URL", "").strip()
  token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
  if url and token:
    return RedisBackend(url, token)
  return FileBackend(os.getenv("LOCAL_STORE_PATH", "local_store.json"))


def is_shared_store():
  return bool(os.getenv("UPSTASH_REDIS_REST_URL", "").strip())


# ---------- users ----------


def _new_user(psid):
  return {"psid": psid, "prefs": [], "onboarded": False, "last_msg": 0,
          "last_game_deal": None}


def get_user(psid):
  raw = backend().get(f"user:{psid}")
  if not raw:
    return _new_user(psid)
  try:
    user = _new_user(psid)
    user.update(json.loads(raw))
    return user
  except Exception:
    return _new_user(psid)


def save_user(user):
  b = backend()
  b.set(f"user:{user['psid']}", json.dumps(user))
  b.sadd("users", user["psid"])


def touch_user(psid):
  """Call on every incoming message: reopens the 24h window."""
  user = get_user(psid)
  user["last_msg"] = time.time()
  save_user(user)
  return user


def all_users():
  b = backend()
  return [get_user(p) for p in b.smembers("users")]


def toggle_pref(user, key):
  if key not in PREFS:
    return user
  prefs = list(user.get("prefs", []))
  if key in prefs:
    prefs.remove(key)
  else:
    prefs.append(key)
  user["prefs"] = prefs
  return user


# ---------- recent items (for "ano bago?") ----------


def push_recent(item):
  b = backend()
  b.rpush("recent", json.dumps(item))
  b.ltrim_last("recent", 60)


def get_recent(limit=10, kinds=None):
  out = []
  for raw in reversed(backend().lrange("recent")):
    try:
      item = json.loads(raw)
    except Exception:
      continue
    if kinds and item.get("kind") not in kinds:
      continue
    out.append(item)
    if len(out) >= limit:
      break
  return out


# ---------- pending queue (users outside the 24h window) ----------


def queue_pending(psid, item):
  from config import MAX_PENDING_PER_USER
  b = backend()
  b.rpush(f"pending:{psid}", json.dumps(item))
  b.ltrim_last(f"pending:{psid}", MAX_PENDING_PER_USER)


def pending_count(psid):
  return len(backend().lrange(f"pending:{psid}"))


def pop_pending(psid, n):
  """Take up to n (newest first) and keep the rest queued."""
  b = backend()
  raw = b.lrange(f"pending:{psid}")
  items = []
  for r in raw:
    try:
      items.append(json.loads(r))
    except Exception:
      pass
  items.reverse()  # newest first
  take, rest = items[:n], items[n:]
  b.delete(f"pending:{psid}")
  for it in reversed(rest):
    b.rpush(f"pending:{psid}", json.dumps(it))
  return take, len(rest)
