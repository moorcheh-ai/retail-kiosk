from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from moorcheh_edge.api import MoorchehEdgeApiError
from requests import RequestException

from retail_kiosk.conversations import (
    assert_customer_may_ask,
    build_chat_history,
    get_conversation_detail,
    list_conversation_summaries,
    persist_exchange,
)
from retail_kiosk.catalog import ChunkCatalog, parse_tags
from retail_kiosk.config import (
    catalog_db_path,
    cors_origins,
    max_customer_questions,
    voice_proxy_url,
)
from retail_kiosk.stream_ask import iter_ask_stream_safe
from retail_kiosk.edge_sync import EdgeSyncService
from retail_kiosk.models import (
    AskRequest,
    AskResponse,
    ChunkRecord,
    ConversationCreate,
    ConversationDetail,
    ConversationSummary,
    DocumentCreate,
    DocumentDetail,
    DocumentUpdate,
    KioskPromptSettings,
    KioskVoiceSettings,
    SyncResult,
    VoiceAskRequest,
    VoiceAskResponse,
    VoiceListenRequest,
    VoiceListenResponse,
    VoiceSpeakRequest,
    VoiceSpeakResponse,
)
from retail_kiosk.voice_kiosk import (
    VoiceKioskError,
    voice_ask_kiosk,
    voice_available,
    voice_listen_kiosk,
    voice_speak_kiosk,
)
from retail_kiosk.voice_proxy import (
    VoiceProxyError,
    proxy_voice_ask,
    proxy_voice_listen,
    proxy_voice_speak,
    voice_proxy_configured,
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def create_app() -> FastAPI:
    catalog = ChunkCatalog(catalog_db_path())
    sync = EdgeSyncService(catalog)

    app = FastAPI(title="Retail Kiosk Admin", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        try:
            edge = sync.health()
        except MoorchehEdgeApiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except RequestException as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Cannot reach edge at {sync.edge_url}: {exc}",
            ) from exc
        return {
            "status": "ok",
            "edge_url": sync.edge_url,
            "catalog_db": str(catalog_db_path()),
            "voice_available": voice_available(),
            "voice_proxy_url": voice_proxy_url(),
            "rag_embed_on": "pc",
            "voice_proxy_used_for": "speak" if voice_proxy_configured() else None,
            "max_customer_questions": max_customer_questions(),
            "edge": edge,
        }

    @app.get("/admin/chunks", response_model=list[ChunkRecord])
    def list_chunks(
        doc_id: str | None = Query(default=None),
        category: str | None = Query(default=None),
    ) -> list[ChunkRecord]:
        return catalog.list_chunks(doc_id=doc_id, category=category)

    @app.get("/admin/documents")
    def list_documents() -> list[dict[str, str]]:
        return catalog.list_documents()

    @app.get("/admin/documents/{doc_id}", response_model=DocumentDetail)
    def get_document(doc_id: str) -> DocumentDetail:
        meta = catalog.get_document_meta(doc_id)
        chunks = catalog.list_chunks(doc_id=doc_id)
        if meta is None or not chunks:
            raise HTTPException(status_code=404, detail="document not found")
        return DocumentDetail(
            doc_id=doc_id,
            category=meta["category"],
            title=meta["title"],
            tags=parse_tags(meta["tags"]),
            text=meta["source_text"],
            chunks=chunks,
        )

    @app.post("/admin/documents", response_model=SyncResult)
    def create_document(payload: DocumentCreate) -> SyncResult:
        try:
            return sync.create_document(payload)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except MoorchehEdgeApiError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.put("/admin/documents/{doc_id}", response_model=SyncResult)
    def update_document(doc_id: str, payload: DocumentUpdate) -> SyncResult:
        try:
            return sync.update_document(doc_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MoorchehEdgeApiError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.delete("/admin/documents/{doc_id}", response_model=SyncResult)
    def delete_document(doc_id: str) -> SyncResult:
        if not catalog.doc_exists(doc_id):
            raise HTTPException(status_code=404, detail="document not found")
        try:
            return sync.delete_document(doc_id)
        except MoorchehEdgeApiError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.get("/admin/settings", response_model=KioskPromptSettings)
    def get_prompt_settings() -> KioskPromptSettings:
        return catalog.get_prompt_settings()

    @app.put("/admin/settings", response_model=KioskPromptSettings)
    def update_prompt_settings(payload: KioskPromptSettings) -> KioskPromptSettings:
        try:
            return catalog.update_prompt_settings(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/admin/settings/voice", response_model=KioskVoiceSettings)
    def get_voice_settings() -> KioskVoiceSettings:
        return catalog.get_voice_settings()

    @app.put("/admin/settings/voice", response_model=KioskVoiceSettings)
    def update_voice_settings(payload: KioskVoiceSettings) -> KioskVoiceSettings:
        try:
            return catalog.update_voice_settings(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/conversations", response_model=ConversationSummary)
    def create_conversation(payload: ConversationCreate) -> ConversationSummary:
        conversation_id = catalog.create_conversation(title=payload.title.strip())
        summary = catalog.get_conversation_summary(conversation_id)
        if summary is None:
            raise HTTPException(status_code=500, detail="failed to create conversation")
        return summary

    @app.get("/conversations", response_model=list[ConversationSummary])
    def list_conversations() -> list[ConversationSummary]:
        return list_conversation_summaries(catalog)

    @app.get("/conversations/{conversation_id}", response_model=ConversationDetail)
    def get_conversation(conversation_id: str) -> ConversationDetail:
        detail = get_conversation_detail(catalog, conversation_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return detail

    @app.delete("/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: str) -> None:
        if not catalog.delete_conversation(conversation_id):
            raise HTTPException(status_code=404, detail="conversation not found")

    @app.post("/ask", response_model=AskResponse)
    def ask(payload: AskRequest) -> AskResponse:
        try:
            assert_customer_may_ask(catalog, payload.conversation_id)
            history = build_chat_history(catalog, payload.conversation_id)
            if voice_proxy_configured() and payload.speak:
                result = proxy_voice_ask(
                    catalog,
                    top_k=payload.top_k,
                    kiosk_mode=payload.kiosk_mode,
                    threshold=payload.threshold,
                    speak=True,
                    query=payload.query,
                    chat_history=history,
                )
                result = AskResponse(
                    query=result.query,
                    answer=result.answer,
                    model=result.model,
                    context_count=result.context_count,
                    sources=result.sources,
                )
            else:
                result = sync.ask(
                    payload.query,
                    top_k=payload.top_k,
                    kiosk_mode=payload.kiosk_mode,
                    threshold=payload.threshold,
                    chat_history=history,
                )
            conversation_id = persist_exchange(
                catalog,
                conversation_id=payload.conversation_id,
                user_text=payload.query.strip(),
                input_mode=payload.input_mode,
                result=result,
            )
            return result.model_copy(update={"conversation_id": conversation_id})
        except VoiceProxyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MoorchehEdgeApiError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.post("/ask/stream")
    def ask_stream(payload: AskRequest) -> StreamingResponse:
        try:
            assert_customer_may_ask(catalog, payload.conversation_id)
            history = build_chat_history(catalog, payload.conversation_id)

            def generate():
                yield from iter_ask_stream_safe(
                    catalog,
                    sync,
                    query=payload.query,
                    top_k=payload.top_k,
                    kiosk_mode=payload.kiosk_mode,
                    threshold=payload.threshold,
                    speak=payload.speak,
                    chat_history=history,
                    conversation_id=payload.conversation_id,
                    input_mode=payload.input_mode,
                )

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "close"},
            )
        except VoiceProxyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MoorchehEdgeApiError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.post("/ask/voice/listen", response_model=VoiceListenResponse)
    def ask_voice_listen(payload: VoiceListenRequest) -> VoiceListenResponse:
        try:
            if voice_proxy_configured():
                return proxy_voice_listen(
                    seconds=payload.seconds,
                    until_silence=payload.until_silence,
                    max_seconds=payload.max_seconds,
                )
            heard = voice_listen_kiosk(
                seconds=payload.seconds,
                until_silence=payload.until_silence,
                max_seconds=payload.max_seconds,
            )
            return VoiceListenResponse(heard=heard)
        except (VoiceKioskError, VoiceProxyError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/ask/voice/speak", response_model=VoiceSpeakResponse)
    def ask_voice_speak(payload: VoiceSpeakRequest) -> VoiceSpeakResponse:
        try:
            if voice_proxy_configured():
                return proxy_voice_speak(text=payload.text)
            voice_speak_kiosk(text=payload.text)
            return VoiceSpeakResponse(spoke=True)
        except (VoiceKioskError, VoiceProxyError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/ask/voice", response_model=VoiceAskResponse)
    def ask_voice(payload: VoiceAskRequest) -> VoiceAskResponse:
        try:
            assert_customer_may_ask(catalog, payload.conversation_id)
            history = build_chat_history(catalog, payload.conversation_id)
            if voice_proxy_configured():
                result = proxy_voice_ask(
                    catalog,
                    seconds=payload.seconds,
                    until_silence=payload.until_silence,
                    max_seconds=payload.max_seconds,
                    top_k=payload.top_k,
                    kiosk_mode=payload.kiosk_mode,
                    threshold=payload.threshold,
                    speak=payload.speak,
                    query=payload.query,
                    chat_history=history,
                )
            else:
                result = voice_ask_kiosk(
                    sync,
                    seconds=payload.seconds,
                    until_silence=payload.until_silence,
                    max_seconds=payload.max_seconds,
                    top_k=payload.top_k,
                    kiosk_mode=payload.kiosk_mode,
                    threshold=payload.threshold,
                    speak=payload.speak,
                    query=payload.query,
                    chat_history=history,
                )
            conversation_id = persist_exchange(
                catalog,
                conversation_id=payload.conversation_id,
                user_text=result.heard,
                input_mode="voice",
                result=result,
            )
            return result.model_copy(update={"conversation_id": conversation_id})
        except (VoiceKioskError, VoiceProxyError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MoorchehEdgeApiError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return app


app = create_app()


def run() -> None:
    import uvicorn

    from retail_kiosk.config import api_host, api_port

    uvicorn.run(
        "retail_kiosk.main:app",
        host=api_host(),
        port=api_port(),
        reload=False,
    )


if __name__ == "__main__":
    run()
