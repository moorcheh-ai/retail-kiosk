from __future__ import annotations

from moorcheh_edge.api import MoorchehEdgeApiClient, MoorchehEdgeApiError
from moorcheh_edge.embeddings import DEFAULT_MODEL, get_embedder

from retail_kiosk.catalog import ChunkCatalog
from retail_kiosk.chunking import BuiltChunk, build_document_chunks
from retail_kiosk.config import (
    DEFAULT_SEARCH_THRESHOLD,
    DEFAULT_TOP_K,
    answer_timeout,
    moorcheh_edge_url,
)
from retail_kiosk.models import AskResponse, DocumentCreate, DocumentUpdate, SyncResult


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
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    @property
    def edge_url(self) -> str:
        return self._edge_url

    def health(self) -> dict:
        return self._client.health()

    def create_document(self, payload: DocumentCreate) -> SyncResult:
        doc_id = payload.doc_id.strip()
        if self._catalog.doc_exists(doc_id):
            raise ValueError(f"document {doc_id!r} already exists")
        chunks = build_document_chunks(
            doc_id=doc_id,
            category=payload.category.strip(),
            title=payload.title.strip(),
            tags=payload.tags,
            body=payload.text,
            embedder=self._get_embedder(),
        )
        self._upload_chunks(chunks)
        self._catalog.replace_doc_chunks(
            edge_url=self._edge_url,
            chunks=chunks,
            source_text=payload.text,
        )
        return SyncResult(
            doc_id=doc_id,
            chunks_uploaded=len(chunks),
            chunks_deleted=0,
            chunk_ids=[chunk.chunk_id for chunk in chunks],
        )

    def update_document(self, doc_id: str, payload: DocumentUpdate) -> SyncResult:
        if not self._catalog.doc_exists(doc_id):
            raise ValueError(f"document {doc_id!r} not found")
        old_ids = set(self._catalog.chunk_ids_for_doc(doc_id))
        chunks = build_document_chunks(
            doc_id=doc_id,
            category=payload.category.strip(),
            title=payload.title.strip(),
            tags=payload.tags,
            body=payload.text,
            embedder=self._get_embedder(),
        )
        new_ids = {chunk.chunk_id for chunk in chunks}
        orphan_ids = sorted(old_ids - new_ids)

        self._upload_chunks(chunks)
        if orphan_ids:
            self._delete_on_edge(orphan_ids)

        self._catalog.replace_doc_chunks(
            edge_url=self._edge_url,
            chunks=chunks,
            source_text=payload.text,
        )
        return SyncResult(
            doc_id=doc_id,
            chunks_uploaded=len(chunks),
            chunks_deleted=len(orphan_ids),
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

    def embed_query(self, query: str) -> list[float]:
        stripped = query.strip()
        if not stripped:
            raise ValueError("query must be non-empty")
        return self._get_embedder().embed_query(stripped)

    def _upload_chunks(self, chunks: list[BuiltChunk]) -> None:
        texts = [chunk.text for chunk in chunks]
        item_ids = [chunk.chunk_id for chunk in chunks]
        vectors = self._get_embedder().embed_documents(texts, item_ids=item_ids)
        items = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            items.append(
                {
                    "id": chunk.chunk_id,
                    "text": chunk.text,
                    "vector": vector,
                }
            )
        self._client.upload(
            {
                "store_mode": "text",
                "embedding_model": DEFAULT_MODEL,
                "items": items,
            }
        )

    def _delete_on_edge(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        self._client.delete_items({"ids": chunk_ids})


__all__ = ["EdgeSyncService", "MoorchehEdgeApiError"]
