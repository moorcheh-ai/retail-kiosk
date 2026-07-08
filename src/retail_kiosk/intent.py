"""Customer utterance intent routing for the retail kiosk (no embedding required)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from retail_kiosk.config import (
    DEFAULT_ACK_REPLY,
    DEFAULT_CHITCHAT_REPLY,
    DEFAULT_FAREWELL_REPLY,
    DEFAULT_GREETING_REPLY,
    DEFAULT_HELP_REPLY,
    DEFAULT_STORE_NAME,
    DEFAULT_THANKS_REPLY,
)


class IntentKind(str, Enum):
    GREETING = "greeting"
    THANKS = "thanks"
    FAREWELL = "farewell"
    HELP = "help"
    CHITCHAT = "chitchat"
    ACKNOWLEDGMENT = "acknowledgment"
    QUESTION = "question"


class ClassificationMethod(str, Enum):
    EMPTY = "empty"
    QUESTION_OVERRIDE = "question_override"
    RULE = "rule"
    DEFAULT = "default"


SOCIAL_INTENTS: frozenset[IntentKind] = frozenset(
    {
        IntentKind.GREETING,
        IntentKind.THANKS,
        IntentKind.FAREWELL,
        IntentKind.HELP,
        IntentKind.CHITCHAT,
        IntentKind.ACKNOWLEDGMENT,
    }
)

# Utterances longer than this are unlikely to be pure social intents.
MAX_SOCIAL_WORDS = 10

_CONTRACTIONS = {
    "what's": "what is",
    "whats": "what is",
    "where's": "where is",
    "how's": "how is",
    "i'm": "i am",
    "you're": "you are",
    "we're": "we are",
    "they're": "they are",
    "it's": "it is",
    "that's": "that is",
    "who's": "who is",
    "don't": "do not",
    "doesn't": "does not",
    "don't": "do not",
    "can't": "can not",
    "won't": "will not",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "weren't": "were not",
    "couldn't": "could not",
    "wouldn't": "would not",
    "shouldn't": "should not",
    "haven't": "have not",
    "hasn't": "has not",
    "hadn't": "had not",
    "i'd": "i would",
    "you'd": "you would",
    "we'd": "we would",
    "i'll": "i will",
    "you'll": "you will",
    "we'll": "we will",
    "gonna": "going to",
    "wanna": "want to",
    "gimme": "give me",
    "lemme": "let me",
}

# If any of these appear, treat as a catalog / store question (not social).
_QUESTION_SIGNAL_RE = re.compile(
    r"\b("
    r"price|prices|cost|how much|how many|"
    r"hours?|open|close|closing|opening|"
    r"where|location|aisle|shelf|"
    r"do you have|do you sell|do you carry|got any|have any|"
    r"in stock|available|availability|"
    r"ingredient|allergen|gluten|dairy|vegan|decaf|caffeine|"
    r"menu|special|deal|discount|promo|coupon|reward|"
    r"return|refund|exchange|policy|"
    r"wifi|restroom|bathroom|parking|"
    r"coffee|tea|latte|espresso|croissant|pastry|sandwich|milk|sugar|"
    r"recommend|suggestion|which one|what kind|tell me about|"
    r"can i get|can i buy|can i order|"
    r"is there|are there"
    r")\b",
    re.IGNORECASE,
)

_GREETING_RE = re.compile(
    r"^("
    r"hi|hello|hey|hiya|howdy|yo|"
    r"good morning|good afternoon|good evening|good day|"
    r"morning|afternoon|evening"
    r")(\s+there|\s+you)?[!.?]*$",
    re.IGNORECASE,
)

_THANKS_RE = re.compile(
    r"^("
    r"thanks?|thank you|thx|ty|much appreciated|appreciate it"
    r")([!.?]*\s*(you|so much|very much))?[!.?]*$",
    re.IGNORECASE,
)

_FAREWELL_RE = re.compile(
    r"^("
    r"bye|goodbye|good bye|see you|see ya|later|take care|"
    r"have a (good|nice|great) (day|one|night)|"
    r"i am done|i'm done|that is all|that's all|nothing else"
    r")[!.?]*$",
    re.IGNORECASE,
)

_HELP_RE = re.compile(
    r"^("
    r"help|what can you (do|help with)|how does this work|"
    r"how do i use (this|the kiosk)|what are you|who are you|"
    r"what do you do|can you help( me)?"
    r")[!.?]*$",
    re.IGNORECASE,
)

_CHITCHAT_RE = re.compile(
    r"^("
    r"how are you|how is it going|how are things|what is up|whats up|"
    r"how is your day|nice to meet you|pleased to meet you|"
    r"good to see you|how goes it|"
    r"how have you been|how you doing|how are ya|how ya doing"
    r")[!.?]*$",
    re.IGNORECASE,
)

_ACK_RE = re.compile(
    r"^("
    r"ok|okay|okey|k|cool|great|nice|perfect|awesome|sounds good|"
    r"got it|understood|alright|all right|sure|yes|yep|yeah|yup|"
    r"no problem|makes sense|i see|"
    r"okay got it|ok got it"
    r")[!.?]*$",
    re.IGNORECASE,
)

# Greeting prefix followed by a real question: "hi, do you have oat milk?"
_GREETING_THEN_QUESTION_RE = re.compile(
    r"^(hi|hello|hey|good morning|good afternoon|good evening)\b"
    r"[\s,!.?-]+(.+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IntentConfig:
    store_name: str = DEFAULT_STORE_NAME
    greeting_reply: str = DEFAULT_GREETING_REPLY
    thanks_reply: str = DEFAULT_THANKS_REPLY
    farewell_reply: str = DEFAULT_FAREWELL_REPLY
    help_reply: str = DEFAULT_HELP_REPLY
    chitchat_reply: str = DEFAULT_CHITCHAT_REPLY
    ack_reply: str = DEFAULT_ACK_REPLY
    max_social_words: int = MAX_SOCIAL_WORDS


@dataclass(frozen=True)
class IntentResult:
    kind: IntentKind
    confidence: float
    method: ClassificationMethod
    normalized_text: str = ""

    @property
    def needs_rag(self) -> bool:
        return self.kind == IntentKind.QUESTION

    @property
    def is_social(self) -> bool:
        return self.kind in SOCIAL_INTENTS


def intent_config_from_voice_settings(voice_settings) -> IntentConfig:
    """Build intent config from ``KioskVoiceSettings`` (or any compatible object)."""

    def pick(custom: str | None, default: str) -> str:
        if custom and str(custom).strip():
            return str(custom).strip()
        return default

    store_name = str(getattr(voice_settings, "store_name", "") or DEFAULT_STORE_NAME).strip()
    return IntentConfig(
        store_name=store_name or DEFAULT_STORE_NAME,
        greeting_reply=pick(getattr(voice_settings, "greeting_reply", None), DEFAULT_GREETING_REPLY),
        thanks_reply=pick(getattr(voice_settings, "thanks_reply", None), DEFAULT_THANKS_REPLY),
        farewell_reply=pick(getattr(voice_settings, "farewell_reply", None), DEFAULT_FAREWELL_REPLY),
        help_reply=pick(getattr(voice_settings, "help_reply", None), DEFAULT_HELP_REPLY),
        chitchat_reply=pick(getattr(voice_settings, "chitchat_reply", None), DEFAULT_CHITCHAT_REPLY),
        ack_reply=pick(getattr(voice_settings, "ack_reply", None), DEFAULT_ACK_REPLY),
    )


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation edges, expand common contractions."""
    raw = unicodedata.normalize("NFKC", text).strip().lower()
    if not raw:
        return ""
    for src, dst in _CONTRACTIONS.items():
        raw = re.sub(rf"\b{re.escape(src)}\b", dst, raw)
    raw = re.sub(r"[^\w\s'-]", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def word_count(text: str) -> int:
    normalized = normalize_text(text)
    if not normalized:
        return 0
    return len(normalized.split())


def _format_reply(template: str, *, store_name: str) -> str:
    return template.format(store_name=store_name).strip()


def canned_response(kind: IntentKind, config: IntentConfig) -> str:
    templates: dict[IntentKind, str] = {
        IntentKind.GREETING: config.greeting_reply,
        IntentKind.THANKS: config.thanks_reply,
        IntentKind.FAREWELL: config.farewell_reply,
        IntentKind.HELP: config.help_reply,
        IntentKind.CHITCHAT: config.chitchat_reply,
        IntentKind.ACKNOWLEDGMENT: config.ack_reply,
    }
    template = templates.get(kind)
    if not template:
        raise ValueError(f"No canned response for intent {kind!r}")
    return _format_reply(template, store_name=config.store_name)


def _greeting_tail(normalized: str) -> str | None:
    """Return text after a leading hi/hello/hey, or None."""
    match = _GREETING_THEN_QUESTION_RE.match(normalized)
    if not match:
        return None
    tail = match.group(2).strip()
    return tail or None


def _match_rules(normalized: str) -> IntentKind | None:
    checks: Iterable[tuple[IntentKind, re.Pattern[str]]] = (
        (IntentKind.THANKS, _THANKS_RE),
        (IntentKind.FAREWELL, _FAREWELL_RE),
        (IntentKind.HELP, _HELP_RE),
        (IntentKind.CHITCHAT, _CHITCHAT_RE),
        (IntentKind.ACKNOWLEDGMENT, _ACK_RE),
        (IntentKind.GREETING, _GREETING_RE),
    )
    for kind, pattern in checks:
        if pattern.search(normalized):
            return kind
    return None


def _has_question_signals(normalized: str) -> bool:
    if _QUESTION_SIGNAL_RE.search(normalized):
        return True
    if "?" in normalized:
        return True
    if normalized.startswith(
        ("what ", "where ", "when ", "why ", "which ", "who ", "can ", "do ", "does ", "is ", "are ")
    ):
        # "how are you" is chitchat; other "how" phrases are usually questions.
        if normalized.startswith("how ") and not _CHITCHAT_RE.search(normalized):
            return True
        if normalized.startswith(
            ("what ", "where ", "when ", "why ", "which ", "who ", "can ", "do ", "does ", "is ", "are ")
        ):
            return True
    return False


def classify_intent(text: str, config: IntentConfig | None = None) -> IntentResult:
    """Classify customer text into social vs question intents (rules only, no embed)."""
    cfg = config or IntentConfig()
    normalized = normalize_text(text)

    if not normalized:
        return IntentResult(
            kind=IntentKind.QUESTION,
            confidence=0.0,
            method=ClassificationMethod.EMPTY,
            normalized_text=normalized,
        )

    greeting_tail = _greeting_tail(normalized)
    if greeting_tail:
        # "hey, how are you" → tail is chitchat, not a catalog question.
        tail_social = _match_rules(greeting_tail)
        if tail_social is not None:
            return IntentResult(
                kind=tail_social,
                confidence=0.94,
                method=ClassificationMethod.RULE,
                normalized_text=normalized,
            )
        if _has_question_signals(greeting_tail):
            return IntentResult(
                kind=IntentKind.QUESTION,
                confidence=0.9,
                method=ClassificationMethod.QUESTION_OVERRIDE,
                normalized_text=normalized,
            )

    words = word_count(normalized)
    if words <= cfg.max_social_words:
        matched = _match_rules(normalized)
        if matched is not None:
            return IntentResult(
                kind=matched,
                confidence=0.92,
                method=ClassificationMethod.RULE,
                normalized_text=normalized,
            )

    if _has_question_signals(normalized):
        return IntentResult(
            kind=IntentKind.QUESTION,
            confidence=0.95,
            method=ClassificationMethod.QUESTION_OVERRIDE,
            normalized_text=normalized,
        )

    if words > cfg.max_social_words:
        return IntentResult(
            kind=IntentKind.QUESTION,
            confidence=0.85,
            method=ClassificationMethod.DEFAULT,
            normalized_text=normalized,
        )

    return IntentResult(
        kind=IntentKind.QUESTION,
        confidence=0.7,
        method=ClassificationMethod.DEFAULT,
        normalized_text=normalized,
    )


__all__ = [
    "ClassificationMethod",
    "IntentConfig",
    "IntentKind",
    "IntentResult",
    "SOCIAL_INTENTS",
    "canned_response",
    "classify_intent",
    "intent_config_from_voice_settings",
    "normalize_text",
    "word_count",
]
