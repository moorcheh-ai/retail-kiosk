from __future__ import annotations

from moorcheh_edge.api import MoorchehEdgeApiClient, MoorchehEdgeApiError

from retail_kiosk.catalog import ChunkCatalog
from retail_kiosk.chunk_meta import built_chunks_from_export_items
from retail_kiosk.chunking import BuiltChunk
from retail_kiosk.config import (
    DEFAULT_SEARCH_THRESHOLD,
    DEFAULT_TOP_K,
    answer_timeout,
    moorcheh_edge_url,
)
from retail_kiosk.models import AskResponse, CatalogSyncResult, DocumentCreate, DocumentUpdate, SyncResult
from retail_kiosk.voice_proxy import (
    VoiceProxyError,
    proxy_catalog_document,
    voice_proxy_configured,
)


class CatalogProxyRequiredError(RuntimeError):
    """Admin catalog writes require UNO Q embed via MOORCHEH_VOICE_PROXY_URL."""


class EdgeSyncService:
    def __init__(
        self,
        catalog: ChunkCatalog,
        *,
        edge_url: str | None = None,
    ) -> None:
        self._catalog = catalog
        self._edge_url = (edge_url or moorcheh_edge_url()).rstrip("/")
        self._client = MoorchehEdgeApiClient(
            base_url=self._edge_url,
            timeout=answer_timeout(),
        )
        self._embedder = None

    def _get_embedder(self):
        from moorcheh_edge.embeddings import get_embedder

        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    @property
    def edge_url(self) -> str:
        return self._edge_url

    def health(self) -> dict:
        return self._client.health()

    def _require_voice_proxy(self) -> None:
        if not voice_proxy_configured():
            raise CatalogProxyRequiredError(
                "Catalog embed requires MOORCHEH_VOICE_PROXY_URL "
                "(UNO Q voice serve embeds and uploads to Moorcheh Edge)."
            )

    @staticmethod
    def _built_chunks_from_rows(rows: list[dict]) -> list[BuiltChunk]:
        built: list[BuiltChunk] = []
        for row in rows:
            tags_raw = str(row.get("tags") or "")
            tags = [part.strip() for part in tags_raw.split(",") if part.strip()]
            built.append(
                BuiltChunk(
                    chunk_id=str(row["chunk_id"]),
                    doc_id=str(row["doc_id"]),
                    chunk_index=int(row["chunk_index"]),
                    category=str(row["category"]),
                    title=str(row["title"]),
                    tags=tags,
                    text=str(row["text"]),
                )
            )
        return built

    def _save_proxy_document(
        self,
        *,
        doc_id: str,
        source_text: str,
        proxy_result: dict,
    ) -> list[BuiltChunk]:
        rows = proxy_result.get("chunks")
        if not isinstance(rows, list) or not rows:
            raise VoiceProxyError("Voice server returned no catalog chunks")
        chunks = self._built_chunks_from_rows(rows)
        self._catalog.replace_doc_chunks(
            edge_url=self._edge_url,
            chunks=chunks,
            source_text=source_text,
        )
        return chunks

    def pull_from_edge(self) -> CatalogSyncResult:
        export = self._client.export_store()
        items = export.get("items")
        if not isinstance(items, list):
            raise MoorchehEdgeApiError("Edge export returned no items", 502, export)

        texts = [
            str(item.get("text") or "").strip()
            for item in items
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
        chunks = built_chunks_from_export_items(texts)
        documents, chunk_count = self._catalog.replace_all_from_edge(
            edge_url=self._edge_url,
            chunks=chunks,
        )
        return CatalogSyncResult(
            edge_url=self._edge_url,
            documents=documents,
            chunks=chunk_count,
        )

    def create_document(self, payload: DocumentCreate) -> SyncResult:
        self._require_voice_proxy()
        doc_id = payload.doc_id.strip()
        if self._catalog.doc_exists(doc_id):
            raise ValueError(f"document {doc_id!r} already exists")

        proxy_result = proxy_catalog_document(
            doc_id=doc_id,
            category=payload.category.strip(),
            title=payload.title.strip(),
            tags=payload.tags,
            text=payload.text,
        )
        chunks = self._save_proxy_document(
            doc_id=doc_id,
            source_text=payload.text,
            proxy_result=proxy_result,
        )
        return SyncResult(
            doc_id=doc_id,
            chunks_uploaded=len(chunks),
            chunks_deleted=0,
            chunk_ids=[chunk.chunk_id for chunk in chunks],
        )

    def update_document(self, doc_id: str, payload: DocumentUpdate) -> SyncResult:
        self._require_voice_proxy()
        if not self._catalog.doc_exists(doc_id):
            raise ValueError(f"document {doc_id!r} not found")

        orphan_ids = self._catalog.chunk_ids_for_doc(doc_id)
        proxy_result = proxy_catalog_document(
            doc_id=doc_id,
            category=payload.category.strip(),
            title=payload.title.strip(),
            tags=payload.tags,
            text=payload.text,
            orphan_chunk_ids=orphan_ids,
        )
        chunks = self._save_proxy_document(
            doc_id=doc_id,
            source_text=payload.text,
            proxy_result=proxy_result,
        )
        new_ids = {chunk.chunk_id for chunk in chunks}
        deleted = len([chunk_id for chunk_id in orphan_ids if chunk_id not in new_ids])
        return SyncResult(
            doc_id=doc_id,
            chunks_uploaded=len(chunks),
            chunks_deleted=deleted,
            chunk_ids=[chunk.chunk_id for chunk in chunks],
        )

    def delete_document(self, doc_id: str) -> SyncResult:
        chunk_ids = self._catalog.delete_doc(doc_id)
        if chunk_ids:
            self._delete_on_edge(chunk_ids)
        return SyncResult(
            doc_id=doc_id,
            chunks_uploaded=0,
            chunks_deleted=len(chunk_ids),
            chunk_ids=chunk_ids,
        )

    def ask(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        kiosk_mode: bool = True,
        threshold: float = DEFAULT_SEARCH_THRESHOLD,
        chat_history: list[dict[str, str]] | None = None,
    ) -> AskResponse:
        stripped = query.strip()
        if not stripped:
            raise ValueError("query must be non-empty")
        prompts = self._catalog.get_prompt_settings()
        vector = self._get_embedder().embed_query(stripped)
        payload: dict = {
            "query": stripped,
            "query_vector": vector,
            "top_k": top_k,
            "header_prompt": prompts.header_prompt,
            "footer_prompt": prompts.footer_prompt,
        }
        if chat_history:
            payload["chat_history"] = chat_history
        if kiosk_mode:
            payload["kiosk_mode"] = True
            payload["threshold"] = threshold
        elif threshold > 0:
            payload["threshold"] = threshold

        response = self._client.answer(payload)
        return AskResponse(
            query=stripped,
            answer=str(response.get("answer") or ""),
            model=response.get("model"),
            context_count=response.get("context_count"),
            sources=response.get("sources"),
        )

    def iter_answer_stream(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        kiosk_mode: bool = True,
        threshold: float = DEFAULT_SEARCH_THRESHOLD,
        chat_history: list[dict[str, str]] | None = None,
    ):
        stripped = query.strip()
        if not stripped:
            raise ValueError("query must be non-empty")
        prompts = self._catalog.get_prompt_settings()
        vector = self._get_embedder().embed_query(stripped)
        payload: dict = {
            "query": stripped,
            "query_vector": vector,
            "top_k": top_k,
            "header_prompt": prompts.header_prompt,
            "footer_prompt": prompts.footer_prompt,
        }
        if chat_history:
            payload["chat_history"] = chat_history
        if kiosk_mode:
            payload["kiosk_mode"] = True
            payload["threshold"] = threshold
        elif threshold > 0:
            payload["threshold"] = threshold

        yield from self._client.answer_stream(payload)

    def preflight_search(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        kiosk_mode: bool = True,
        threshold: float = DEFAULT_SEARCH_THRESHOLD,
    ) -> tuple[list[float], int]:
        """Embed locally and search edge; used when voice proxy is not configured."""
        stripped = query.strip()
        if not stripped:
            raise ValueError("query must be non-empty")
        vector = self._get_embedder().embed_query(stripped)
        payload: dict = {
            "query": vector,
            "top_k": top_k,
        }
        if kiosk_mode:
            payload["kiosk_mode"] = True
            payload["threshold"] = threshold
        elif threshold > 0:
            payload["threshold"] = threshold
        response = self._client.search(payload)
        results = response.get("results") or []
        if not isinstance(results, list):
            results = []
        return vector, len(results)

    def _delete_on_edge(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        self._client.delete_items({"ids": chunk_ids})


__all__ = [
    "CatalogProxyRequiredError",
    "EdgeSyncService",
    "MoorchehEdgeApiError",
]
