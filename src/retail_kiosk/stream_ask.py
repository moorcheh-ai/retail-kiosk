from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import requests
from requests import RequestException

from moorcheh_edge.api import MoorchehEdgeApiError

from retail_kiosk.catalog import ChunkCatalog
from retail_kiosk.config import DEFAULT_SEARCH_THRESHOLD, DEFAULT_TOP_K, voice_proxy_url
from retail_kiosk.conversations import persist_exchange
from retail_kiosk.edge_sync import EdgeSyncService
from retail_kiosk.models import AskResponse
from retail_kiosk.voice_proxy import VoiceProxyError, voice_proxy_configured

logger = logging.getLogger(__name__)


def _iter_sse_blocks(buffer: str) -> tuple[list[str], str]:
    blocks: list[str] = []
    while True:
        sep = buffer.find("\n\n")
        if sep < 0:
            return blocks, buffer
        blocks.append(buffer[: sep + 2])
        buffer = buffer[sep + 2 :]


def _parse_sse_event(block: str) -> tuple[str, str]:
    event_name = "message"
    data_lines: list[str] = []
    for line in block.replace("\r\n", "\n").split("\n"):
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip() or event_name
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    return event_name, "\n".join(data_lines)


def _format_sse(event: str, data: str | dict[str, Any]) -> bytes:
    payload = json.dumps(data) if isinstance(data, dict) else data
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _persist_done_event(
    catalog: ChunkCatalog,
    *,
    query: str,
    data: str,
    conversation_id: str | None,
    input_mode: str,
) -> bytes | None:
    """Attach conversation_id to a done SSE event; always emit done even if SQLite fails."""
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return None

    answer = str(parsed.get("answer") or "").strip()
    result = AskResponse(
        query=str(parsed.get("query") or query.strip()),
        answer=answer,
        model=parsed.get("model"),
        context_count=parsed.get("context_count"),
        sources=parsed.get("sources"),
    )
    conv_id = conversation_id
    try:
        conv_id = persist_exchange(
            catalog,
            conversation_id=conversation_id,
            user_text=query.strip(),
            input_mode=input_mode,
            result=result,
        )
    except Exception:
        logger.exception("Failed to persist streamed exchange")
    parsed["conversation_id"] = conv_id
    return _format_sse("done", parsed)


def _proxy_voice_stream(
    catalog: ChunkCatalog,
    *,
    query: str,
    top_k: int,
    kiosk_mode: bool,
    threshold: float,
    speak: bool,
    chat_history: list[dict[str, str]] | None,
    conversation_id: str | None,
    input_mode: str,
) -> Iterator[bytes]:
    proxy = voice_proxy_url()
    if not proxy:
        raise VoiceProxyError("Voice hardware proxy is not configured.")

    prompts = catalog.get_prompt_settings()
    voice = catalog.get_voice_settings()
    # Query text only — UNO Q voice serve embeds locally, then calls :8080/answer/stream.
    payload: dict[str, Any] = {
        "query": query.strip(),
        "top_k": top_k,
        "kiosk_mode": kiosk_mode,
        "threshold": threshold,
        "header_prompt": prompts.header_prompt,
        "footer_prompt": prompts.footer_prompt,
        "speak": speak,
        "holding_enabled": voice.holding_enabled,
        "thinking_enabled": True,
    }
    if chat_history:
        payload["chat_history"] = chat_history

    url = f"{proxy.rstrip('/')}/ask/stream"
    try:
        response = requests.post(
            url,
            json=payload,
            stream=True,
            # Connect timeout only; do not cut off mid-stream while UNO Q generates.
            timeout=(30, None),
        )
    except RequestException as exc:
        raise VoiceProxyError(f"Could not reach voice server at {url}: {exc}") from exc

    if not response.ok:
        detail = response.text or response.reason
        raise VoiceProxyError(detail or f"Voice server returned {response.status_code}")

    pending = ""
    try:
        for chunk in response.iter_content(chunk_size=1024):
            if not chunk:
                continue
            pending += chunk.decode("utf-8", errors="replace")
            blocks, pending = _iter_sse_blocks(pending)
            for block in blocks:
                event_name, data = _parse_sse_event(block)
                if event_name == "done":
                    done = _persist_done_event(
                        catalog,
                        query=query,
                        data=data,
                        conversation_id=conversation_id,
                        input_mode=input_mode,
                    )
                    if done is not None:
                        yield done
                    else:
                        yield block.encode("utf-8")
                    return
                if event_name == "error":
                    yield block.encode("utf-8")
                    return
                if event_name == "holding":
                    yield block.encode("utf-8")
                    continue
                if event_name == "thinking":
                    yield block.encode("utf-8")
                    continue
                yield block.encode("utf-8")

        if pending.strip():
            event_name, data = _parse_sse_event(pending)
            if event_name == "done":
                done = _persist_done_event(
                    catalog,
                    query=query,
                    data=data,
                    conversation_id=conversation_id,
                    input_mode=input_mode,
                )
                if done is not None:
                    yield done
                else:
                    yield pending.encode("utf-8")
            else:
                yield pending.encode("utf-8")
    finally:
        response.close()


def _local_edge_stream(
    sync: EdgeSyncService,
    catalog: ChunkCatalog,
    *,
    query: str,
    top_k: int,
    kiosk_mode: bool,
    threshold: float,
    chat_history: list[dict[str, str]] | None,
    conversation_id: str | None,
    input_mode: str,
) -> Iterator[bytes]:
    from moorcheh_edge._sse import iter_sse_events, parse_sse_json

    pending = ""
    for chunk in sync.iter_answer_stream(
        query,
        top_k=top_k,
        kiosk_mode=kiosk_mode,
        threshold=threshold,
        chat_history=chat_history,
    ):
        pending += chunk.decode("utf-8", errors="replace")
        blocks, pending = _iter_sse_blocks(pending)
        for block in blocks:
            for event in iter_sse_events(block):
                if event.event == "done":
                    parsed = parse_sse_json(event.data)
                    done = _persist_done_event(
                        catalog,
                        query=query,
                        data=event.data,
                        conversation_id=conversation_id,
                        input_mode=input_mode,
                    )
                    if done is not None:
                        yield done
                    else:
                        yield _format_sse("done", parsed)
                    return
                yield _format_sse(event.event, event.data)
    if pending.strip():
        for event in iter_sse_events(pending):
            if event.event == "done":
                done = _persist_done_event(
                    catalog,
                    query=query,
                    data=event.data,
                    conversation_id=conversation_id,
                    input_mode=input_mode,
                )
                if done is not None:
                    yield done
                else:
                    parsed = parse_sse_json(event.data)
                    yield _format_sse("done", parsed)
                return
            yield _format_sse(event.event, event.data)


def iter_ask_stream(
    catalog: ChunkCatalog,
    sync: EdgeSyncService,
    *,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    kiosk_mode: bool = True,
    threshold: float = DEFAULT_SEARCH_THRESHOLD,
    speak: bool = False,
    chat_history: list[dict[str, str]] | None = None,
    conversation_id: str | None = None,
    input_mode: str = "text",
) -> Iterator[bytes]:
    stripped = query.strip()
    if not stripped:
        raise ValueError("query must be non-empty")

    # When MOORCHEH_VOICE_PROXY_URL is set, all customer asks go through UNO Q
    # voice serve (:8766). UNO embeds the query locally, then calls edge :8080.
    use_voice_proxy = voice_proxy_configured()

    if use_voice_proxy:
        yield from _proxy_voice_stream(
            catalog,
            query=stripped,
            top_k=top_k,
            kiosk_mode=kiosk_mode,
            threshold=threshold,
            speak=speak,
            chat_history=chat_history,
            conversation_id=conversation_id,
            input_mode=input_mode,
        )
        return

    yield from _local_edge_stream(
        sync,
        catalog,
        query=stripped,
        top_k=top_k,
        kiosk_mode=kiosk_mode,
        threshold=threshold,
        chat_history=chat_history,
        conversation_id=conversation_id,
        input_mode=input_mode,
    )


def iter_ask_stream_safe(
    catalog: ChunkCatalog,
    sync: EdgeSyncService,
    **kwargs,
) -> Iterator[bytes]:
    """Like iter_ask_stream but yields SSE error events instead of raising mid-stream."""
    try:
        yield from iter_ask_stream(catalog, sync, **kwargs)
    except VoiceProxyError as exc:
        yield _format_sse("error", {"message": str(exc)})
    except RequestException as exc:
        yield _format_sse("error", {"message": f"Voice proxy stream failed: {exc}"})
    except MoorchehEdgeApiError as exc:
        yield _format_sse("error", {"message": str(exc)})
    except ValueError as exc:
        yield _format_sse("error", {"message": str(exc)})


__all__ = ["iter_ask_stream", "iter_ask_stream_safe"]
