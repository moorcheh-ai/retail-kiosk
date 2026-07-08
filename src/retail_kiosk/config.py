from __future__ import annotations

import os
from pathlib import Path

DEFAULT_EDGE_URL = "http://localhost:8080"
DEFAULT_DB_PATH = Path.home() / ".retail-kiosk" / "catalog.db"
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
DEFAULT_MAX_BODY_TOKENS = 200
DEFAULT_ANSWER_TIMEOUT = 300
DEFAULT_VOICE_TIMEOUT = 300
DEFAULT_CHAT_HISTORY_USER_TURNS = 3
DEFAULT_MAX_CUSTOMER_QUESTIONS = 4
DEFAULT_TOP_K = 2
# Edge similarity threshold for kiosk_mode search (0.0–1.0).
DEFAULT_SEARCH_THRESHOLD = 0.30

DEFAULT_HEADER_PROMPT = (
    "You are the friendly in-store voice assistant at The Brew Corner. "
    "Answer naturally using ONLY provided context. The customer is on-site; "
    "never provide our address, phone, website, or directions. If info is missing, "
    "politely say you don't know and suggest asking counter staff."
)
DEFAULT_FOOTER_PROMPT = (
    "Provide a brief, natural spoken response based ONLY on the context. "
    "Include prices if mentioned. No address, contact info, markdown, lists, or citations."
)

DEFAULT_STORE_NAME = "The Brew Corner"
DEFAULT_HOLDING_PROMO = (
    "Buy any twelve ounce hot drink and get a butter croissant for two dollars."
)
DEFAULT_HOLDING_ENABLED = True

DEFAULT_GREETING_REPLY = (
    "Hi! Welcome to {store_name}. What can I help you find today?"
)
DEFAULT_THANKS_REPLY = (
    "You're welcome! Let me know if you need anything else."
)
DEFAULT_FAREWELL_REPLY = (
    "Thanks for visiting {store_name}. Have a great day!"
)
DEFAULT_HELP_REPLY = (
    "I can answer questions about our products, prices, and store info. "
    "What would you like to know?"
)
DEFAULT_CHITCHAT_REPLY = (
    "I'm doing well, thanks for asking! How can I help you at {store_name} today?"
)
DEFAULT_ACK_REPLY = "Sounds good. Ask me anything else when you're ready."


def _normalize_base_url(raw: str) -> str:
    """Strip whitespace/trailing slashes and trailing dots (breaks Windows DNS for IPs)."""
    url = raw.strip().rstrip("/")
    if url.endswith("."):
        url = url.rstrip(".")
    return url


def moorcheh_edge_url() -> str:
    return _normalize_base_url(os.environ.get("MOORCHEH_EDGE_URL", DEFAULT_EDGE_URL))


def catalog_db_path() -> Path:
    raw = os.environ.get("RETAIL_KIOSK_DB")
    return Path(raw) if raw else DEFAULT_DB_PATH


def cors_origins() -> list[str]:
    raw = os.environ.get("RETAIL_KIOSK_CORS", DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def answer_timeout() -> int:
    raw = os.environ.get("RETAIL_KIOSK_ANSWER_TIMEOUT")
    if raw:
        return int(raw)
    return DEFAULT_ANSWER_TIMEOUT


def voice_timeout() -> int:
    raw = os.environ.get("RETAIL_KIOSK_VOICE_TIMEOUT")
    if raw:
        return int(raw)
    return DEFAULT_VOICE_TIMEOUT


def api_host() -> str:
    return os.environ.get("RETAIL_KIOSK_HOST", "127.0.0.1")


def api_port() -> int:
    raw = os.environ.get("RETAIL_KIOSK_PORT")
    if raw:
        return int(raw)
    return 8765


def voice_proxy_url() -> str | None:
    raw = os.environ.get("MOORCHEH_VOICE_PROXY_URL", "").strip()
    return _normalize_base_url(raw) if raw else None


def chat_history_max_user_turns() -> int:
    raw = os.environ.get("RETAIL_KIOSK_CHAT_HISTORY_USER_TURNS")
    if raw:
        return max(0, int(raw))
    return DEFAULT_CHAT_HISTORY_USER_TURNS


def max_customer_questions() -> int:
    raw = os.environ.get("RETAIL_KIOSK_MAX_CUSTOMER_QUESTIONS")
    if raw:
        return max(1, int(raw))
    return DEFAULT_MAX_CUSTOMER_QUESTIONS
