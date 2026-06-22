from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from retail_kiosk.config import DEFAULT_MAX_BODY_TOKENS

if TYPE_CHECKING:
    from moorcheh_edge.embeddings import Embedder


def chunk_id_for(doc_id: str, index: int) -> str:
    return f"{doc_id}#chunk-{index}"


def format_tags(tags: list[str]) -> str:
    return ",".join(tag.strip() for tag in tags if tag.strip())


def build_meta_header(
    *,
    doc_id: str,
    category: str,
    title: str,
    tags: list[str],
    chunk_index: int,
) -> str:
    return (
        "[meta]\n"
        f"doc_id: {doc_id}\n"
        f"category: {category}\n"
        f"title: {title}\n"
        f"tags: {format_tags(tags)}\n"
        f"chunk: {chunk_index}\n"
        "[/meta]\n\n"
    )


def split_body_text(
    embedder: Embedder,
    text: str,
    *,
    max_tokens: int = DEFAULT_MAX_BODY_TOKENS,
    overlap_tokens: int = 0,
) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []

    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be smaller than max_tokens")

    token_count = embedder.count_tokens(stripped)
    if token_count <= max_tokens:
        return [stripped]

    tokenizer = embedder._get_count_tokenizer()
    token_ids = tokenizer.encode(stripped).ids

    chunks: list[str] = []
    start = 0
    while start < len(token_ids):
        end = min(start + max_tokens, len(token_ids))
        piece = tokenizer.decode(token_ids[start:end]).strip()
        if piece:
            chunks.append(piece)
        if end >= len(token_ids):
            break
        start = max(end - overlap_tokens, start + 1)

    return chunks


@dataclass(frozen=True)
class BuiltChunk:
    chunk_id: str
    doc_id: str
    chunk_index: int
    category: str
    title: str
    tags: list[str]
    text: str


def build_document_chunks(
    *,
    doc_id: str,
    category: str,
    title: str,
    tags: list[str],
    body: str,
    embedder: Embedder,
    max_body_tokens: int = DEFAULT_MAX_BODY_TOKENS,
) -> list[BuiltChunk]:
    parts = split_body_text(embedder, body, max_tokens=max_body_tokens)
    if not parts:
        raise ValueError("document text is empty after stripping")

    built: list[BuiltChunk] = []
    for index, part in enumerate(parts):
        header = build_meta_header(
            doc_id=doc_id,
            category=category,
            title=title,
            tags=tags,
            chunk_index=index,
        )
        built.append(
            BuiltChunk(
                chunk_id=chunk_id_for(doc_id, index),
                doc_id=doc_id,
                chunk_index=index,
                category=category,
                title=title,
                tags=list(tags),
                text=header + part,
            )
        )
    return built
