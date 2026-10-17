"""Shared constants for the monitor and the Messenger bot."""

# What a user can subscribe to (key -> button label)
PREFS = {
    "games": "🎮 Game deals",
    "free": "🆓 Libreng games",
    "github": "🧩 AI / GitHub",
    "local": "📢 BSU / Malolos",
}

# Which preference each item kind belongs to
KIND_PREF = {
    "game": "games",
    "free": "free",
    "github": "github",
    "local": "local",
    "memo": "local",
}

# Messenger only allows bots to message a user within 24h of the user's last
# message. Stay a bit under it.
WINDOW_SECONDS = 23 * 3600

MAX_PUSH_PER_USER = 4      # items pushed at once per run
MAX_PENDING_PER_USER = 40  # items queued for users outside the 24h window
