from __future__ import annotations

from retail_kiosk.config import DEFAULT_SEARCH_THRESHOLD, DEFAULT_TOP_K
from retail_kiosk.edge_sync import EdgeSyncService
from retail_kiosk.models import VoiceAskResponse


class VoiceKioskError(RuntimeError):
    """Voice pipeline is unavailable or failed."""


def voice_listen_kiosk(
    *,
    seconds: int | None = None,
    until_silence: bool = True,
    max_seconds: int = 30,
) -> str:
    try:
        from moorcheh_edge._voice import (
            VoiceError,
            ensure_voice_runtime,
            listen_and_transcribe,
        )
    except ImportError as exc:
        raise VoiceKioskError(
            "Voice support requires moorcheh-edge with voice dependencies."
        ) from exc

    try:
        ensure_voice_runtime(quiet=True)
        heard = listen_and_transcribe(
            seconds=seconds,
            until_silence=until_silence,
            max_seconds=max_seconds,
        ).strip()
        if not heard:
            raise VoiceKioskError("No speech detected. Try speaking louder or closer to the mic.")
        return heard
    except VoiceError as exc:
        raise VoiceKioskError(str(exc)) from exc


def voice_speak_kiosk(*, text: str) -> None:
    try:
        from moorcheh_edge._voice import VoiceError, ensure_voice_runtime, speak_text
    except ImportError as exc:
        raise VoiceKioskError(
            "Voice support requires moorcheh-edge with voice dependencies."
        ) from exc

    cleaned = text.strip()
    if not cleaned:
        raise VoiceKioskError("Nothing to speak")
    try:
        ensure_voice_runtime(quiet=True)
        speak_text(cleaned)
    except VoiceError as exc:
        raise VoiceKioskError(str(exc)) from exc


def voice_ask_kiosk(
    sync: EdgeSyncService,
    *,
    seconds: int | None = None,
    until_silence: bool = True,
    max_seconds: int = 30,
    top_k: int = DEFAULT_TOP_K,
    kiosk_mode: bool = True,
    threshold: float = DEFAULT_SEARCH_THRESHOLD,
    speak: bool = True,
    query: str | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> VoiceAskResponse:
    """Record speech (unless query provided), RAG answer, optional TTS playback."""
    if query and query.strip():
        heard = query.strip()
    else:
        heard = voice_listen_kiosk(
            seconds=seconds,
            until_silence=until_silence,
            max_seconds=max_seconds,
        )

    result = sync.ask(
        heard,
        top_k=top_k,
        kiosk_mode=kiosk_mode,
        threshold=threshold,
        chat_history=chat_history,
    )
    answer = result.answer.strip()
    if not answer:
        raise VoiceKioskError("Answer was empty.")

    if speak:
        voice_speak_kiosk(text=answer)

    return VoiceAskResponse(
        heard=heard,
        query=result.query,
        answer=answer,
        model=result.model,
        context_count=result.context_count,
        sources=result.sources,
        spoke=speak,
    )


def voice_available() -> bool:
    """True when this machine can run the local mic/speaker voice pipeline."""
    import sys

    if sys.platform != "linux":
        return False
    try:
        from moorcheh_edge._voice import find_piper_binary, find_whisper_binary

        return find_whisper_binary() is not None and (
            find_piper_binary() is not None
            or __import__("shutil").which("espeak-ng")
            or __import__("shutil").which("espeak")
        )
    except ImportError:
        return False


__all__ = [
    "VoiceKioskError",
    "voice_ask_kiosk",
    "voice_available",
    "voice_listen_kiosk",
    "voice_speak_kiosk",
]
