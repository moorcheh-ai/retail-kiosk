from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from retail_kiosk.catalog import ChunkCatalog
from retail_kiosk.config import (
    DEFAULT_SEARCH_THRESHOLD,
    DEFAULT_TOP_K,
    voice_proxy_url,
    voice_timeout,
)
from retail_kiosk.models import AskResponse, VoiceAskResponse, VoiceListenResponse, VoiceSpeakResponse


class VoiceProxyError(RuntimeError):
    """Voice proxy request failed."""


def _voice_proxy_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    proxy = voice_proxy_url()
    if not proxy:
        raise VoiceProxyError(
            "Voice hardware proxy is not configured. "
            "Set MOORCHEH_VOICE_PROXY_URL=http://UNO-Q-IP:8766 on the PC API "
            "and run moorcheh-edge voice serve on the UNO Q."
        )

    url = f"{proxy.rstrip('/')}{path}"
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = voice_timeout()
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            message = str(parsed.get("error") or parsed.get("detail") or detail)
        except json.JSONDecodeError:
            message = detail or str(exc)
        raise VoiceProxyError(message) from exc
    except URLError as exc:
        raise VoiceProxyError(
            f"Could not reach voice server at {url}: {exc.reason}"
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VoiceProxyError("Voice server returned invalid JSON") from exc

    if not isinstance(data, dict):
        raise VoiceProxyError("Voice server returned an unexpected response")
    return data


def proxy_voice_listen(
    *,
    seconds: int | None = None,
    until_silence: bool = True,
    max_seconds: int = 30,
) -> VoiceListenResponse:
    payload: dict[str, Any] = {
        "until_silence": until_silence,
        "max_seconds": max_seconds,
    }
    if seconds is not None:
        payload["seconds"] = seconds
        payload["until_silence"] = False
    data = _voice_proxy_post("/listen", payload)
    heard = str(data.get("heard") or "").strip()
    if not heard:
        raise VoiceProxyError("Voice server returned no transcript")
    return VoiceListenResponse(heard=heard)


def proxy_voice_speak(*, text: str) -> VoiceSpeakResponse:
    cleaned = text.strip()
    if not cleaned:
        raise VoiceProxyError("Nothing to speak")
    data = _voice_proxy_post("/speak", {"text": cleaned})
    return VoiceSpeakResponse(spoke=bool(data.get("spoke", True)))


def proxy_catalog_document(
    *,
    doc_id: str,
    category: str,
    title: str,
    tags: list[str],
    text: str,
    orphan_chunk_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Chunk, embed, and upload on UNO Q via voice serve."""
    payload: dict[str, Any] = {
        "doc_id": doc_id.strip(),
        "category": category.strip(),
        "title": title.strip(),
        "text": text,
        "tags": tags,
    }
    if orphan_chunk_ids:
        payload["orphan_chunk_ids"] = orphan_chunk_ids
    return _voice_proxy_post("/catalog/document", payload)


def proxy_voice_ask(
    catalog: ChunkCatalog,
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
    prompts = catalog.get_prompt_settings()
    payload: dict[str, Any] = {
        "until_silence": until_silence,
        "max_seconds": max_seconds,
        "top_k": top_k,
        "kiosk_mode": kiosk_mode,
        "threshold": threshold,
        "header_prompt": prompts.header_prompt,
        "footer_prompt": prompts.footer_prompt,
        "speak": speak,
    }
    if seconds is not None:
        payload["seconds"] = seconds
        payload["until_silence"] = False
    if query and query.strip():
        payload["query"] = query.strip()
    if chat_history:
        payload["chat_history"] = chat_history

    data = _voice_proxy_post("/ask", payload)

    heard = str(data.get("heard") or data.get("query") or query or "").strip()
    answer = str(data.get("answer") or "").strip()
    if not heard:
        raise VoiceProxyError("Voice server returned no transcript")
    if not answer:
        raise VoiceProxyError("Voice server returned an empty answer")

    return VoiceAskResponse(
        heard=heard,
        query=str(data.get("query") or heard),
        answer=answer,
        model=data.get("model"),
        context_count=data.get("context_count"),
        sources=data.get("sources"),
        spoke=bool(data.get("spoke", speak)),
    )


def proxy_edge_rag(
    catalog: ChunkCatalog,
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    kiosk_mode: bool = True,
    threshold: float = DEFAULT_SEARCH_THRESHOLD,
    chat_history: list[dict[str, str]] | None = None,
) -> AskResponse:
    """Embed + RAG on UNO Q (via voice serve → local :8080). No mic/speaker."""
    voice_result = proxy_voice_ask(
        catalog,
        top_k=top_k,
        kiosk_mode=kiosk_mode,
        threshold=threshold,
        speak=False,
        query=query,
        chat_history=chat_history,
    )
    return AskResponse(
        query=voice_result.query,
        answer=voice_result.answer,
        model=voice_result.model,
        context_count=voice_result.context_count,
        sources=voice_result.sources,
    )


def voice_proxy_configured() -> bool:
    return bool(voice_proxy_url())


__all__ = [
    "VoiceProxyError",
    "proxy_catalog_document",
    "proxy_edge_rag",
    "proxy_voice_ask",
    "proxy_voice_listen",
    "proxy_voice_speak",
    "voice_proxy_configured",
]
