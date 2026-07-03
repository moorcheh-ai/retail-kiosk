"""Parse [meta] headers from Moorcheh Edge chunk text."""

from __future__ import annotations

import re
from collections import defaultdict

from retail_kiosk.catalog import parse_tags
from retail_kiosk.chunking import BuiltChunk, chunk_id_for

_META_BLOCK = re.compile(
    r"^\[meta\]\s*\n(.*?)\n\[/meta\]\s*\n?",
    re.DOTALL,
)


def parse_chunk_meta(text: str) -> dict[str, str | int]:
    """Return doc_id, category, title, tags, chunk_index from a stored chunk."""
    match = _META_BLOCK.match(text.strip())
    if not match:
        raise ValueError("chunk text is missing a [meta] header")

    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()

    doc_id = fields.get("doc_id")
    category = fields.get("category")
    title = fields.get("title")
    chunk_raw = fields.get("chunk")
    if not doc_id or not category or not title or chunk_raw is None:
        raise ValueError("chunk meta is missing required fields")

    try:
        chunk_index = int(chunk_raw)
    except ValueError as exc:
        raise ValueError(f"invalid chunk index: {chunk_raw!r}") from exc

    return {
        "doc_id": doc_id,
        "category": category,
        "title": title,
        "tags": fields.get("tags", ""),
        "chunk_index": chunk_index,
    }


def chunk_body_text(text: str) -> str:
    """Strip the [meta] block and return the chunk body."""
    return _META_BLOCK.sub("", text.strip(), count=1).strip()


def built_chunks_from_export_items(
    chunk_texts: list[str],
) -> list[BuiltChunk]:
    """Convert edge export payloads into BuiltChunk rows for SQLite."""
    built: list[BuiltChunk] = []
    for text in chunk_texts:
        stripped = text.strip()
        if not stripped:
            continue
        meta = parse_chunk_meta(stripped)
        doc_id = str(meta["doc_id"])
        chunk_index = int(meta["chunk_index"])
        tags = parse_tags(str(meta["tags"]))
        built.append(
            BuiltChunk(
                chunk_id=chunk_id_for(doc_id, chunk_index),
                doc_id=doc_id,
                chunk_index=chunk_index,
                category=str(meta["category"]),
                title=str(meta["title"]),
                tags=tags,
                text=stripped,
            )
        )

    built.sort(key=lambda chunk: (chunk.doc_id, chunk.chunk_index))
    return built


def source_text_for_doc(chunks: list[BuiltChunk]) -> str:
    """Rebuild editable document text from ordered chunk bodies."""
    ordered = sorted(chunks, key=lambda chunk: chunk.chunk_index)
    bodies = [chunk_body_text(chunk.text) for chunk in ordered]
    return "\n\n".join(part for part in bodies if part)


def group_chunks_by_document(chunks: list[BuiltChunk]) -> dict[str, list[BuiltChunk]]:
    grouped: dict[str, list[BuiltChunk]] = defaultdict(list)
    for chunk in chunks:
        grouped[chunk.doc_id].append(chunk)
    return dict(grouped)
