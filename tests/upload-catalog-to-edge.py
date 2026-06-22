#!/usr/bin/env python3
"""Upload tests/brew-corner-catalog.json to Moorcheh Edge on the Arduino UNO Q.

Requires moorcheh-edge (pip) and a running `moorcheh-edge up` on the board.
Embeds and uploads document chunks locally on the UNO Q.

Example (on UNO Q, after scp from PC):
  source ~/moorcheh-venv/bin/activate
  python ~/upload-catalog-to-edge.py -y
  python ~/upload-catalog-to-edge.py --clear -y   # replace existing vectors
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from moorcheh_edge.api import MoorchehEdgeApiClient, MoorchehEdgeApiError
from moorcheh_edge.embeddings import DEFAULT_MODEL, get_embedder

DEFAULT_EDGE_URL = "http://127.0.0.1:8080"
MAX_BODY_TOKENS = 200
DEFAULT_CATALOG = Path(__file__).resolve().parent / "brew-corner-catalog.json"


def _format_tags(tags: list[str]) -> str:
    return ",".join(tag.strip() for tag in tags if tag.strip())


def _chunk_id(doc_id: str, index: int) -> str:
    return f"{doc_id}#chunk-{index}"


def _meta_header(
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
        f"tags: {_format_tags(tags)}\n"
        f"chunk: {chunk_index}\n"
        "[/meta]\n\n"
    )


def _split_body(embedder, text: str, *, max_tokens: int = MAX_BODY_TOKENS) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    if embedder.count_tokens(stripped) <= max_tokens:
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
        start = end
    return chunks


def _build_items(
    embedder,
    *,
    doc_id: str,
    category: str,
    title: str,
    tags: list[str],
    body: str,
) -> list[dict]:
    parts = _split_body(embedder, body)
    if not parts:
        raise ValueError("document text is empty")
    items: list[dict] = []
    texts: list[str] = []
    ids: list[str] = []
    for index, part in enumerate(parts):
        chunk_id = _chunk_id(doc_id, index)
        full_text = _meta_header(
            doc_id=doc_id,
            category=category,
            title=title,
            tags=tags,
            chunk_index=index,
        ) + part
        ids.append(chunk_id)
        texts.append(full_text)
    vectors = embedder.embed_documents(texts, item_ids=ids)
    for chunk_id, full_text, vector in zip(ids, texts, vectors, strict=True):
        items.append({"id": chunk_id, "text": full_text, "vector": vector})
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help=f"Path to catalog JSON (default: {DEFAULT_CATALOG.name} next to this script)",
    )
    parser.add_argument(
        "--edge-url",
        default=DEFAULT_EDGE_URL,
        help=f"Moorcheh Edge base URL (default: {DEFAULT_EDGE_URL})",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear the vector store before upload",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation when using --clear",
    )
    args = parser.parse_args()

    catalog_path = args.catalog.resolve()
    if not catalog_path.is_file():
        print(f"catalog not found: {catalog_path}", file=sys.stderr)
        return 1

    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    documents = data.get("documents")
    if not isinstance(documents, list) or not documents:
        print("catalog JSON must contain a non-empty 'documents' array", file=sys.stderr)
        return 1

    store = data.get("store") or {}
    store_name = store.get("name", "catalog")
    edge_url = args.edge_url.rstrip("/")
    client = MoorchehEdgeApiClient(edge_url, timeout=300)

    print(f"[upload] Store:  {store_name}")
    print(f"[upload] Edge:   {edge_url}")
    print(f"[upload] Docs:   {len(documents)}")

    if args.clear:
        if not args.yes:
            answer = input("Clear ALL vectors on Moorcheh Edge before upload? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("Aborted.")
                return 1
        print("[upload] Clearing edge store …")
        client.clear_store()
        print("[upload] Edge store cleared.")

    embedder = get_embedder()
    all_items: list[dict] = []
    errors = 0

    for raw in documents:
        if not isinstance(raw, dict):
            errors += 1
            continue
        doc_id = str(raw.get("doc_id") or "").strip()
        category = str(raw.get("category") or "").strip()
        title = str(raw.get("title") or "").strip()
        body = str(raw.get("text") or "").strip()
        tags_raw = raw.get("tags") or []
        if isinstance(tags_raw, str):
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        else:
            tags = [str(t).strip() for t in tags_raw if str(t).strip()]
        if not doc_id or not body:
            print(f"[upload] Skip invalid entry: {raw!r}")
            errors += 1
            continue
        try:
            items = _build_items(
                embedder,
                doc_id=doc_id,
                category=category,
                title=title,
                tags=tags,
                body=body,
            )
            all_items.extend(items)
            print(f"[upload] Prepared {doc_id} -> {len(items)} chunk(s)")
        except Exception as exc:
            print(f"[upload] Error preparing {doc_id}: {exc}")
            errors += 1

    if not all_items:
        print("[upload] Nothing to upload.", file=sys.stderr)
        return 1

    print(f"[upload] Uploading {len(all_items)} chunk(s) …")
    try:
        result = client.upload(
            {
                "store_mode": "text",
                "embedding_model": DEFAULT_MODEL,
                "items": all_items,
            }
        )
    except MoorchehEdgeApiError as exc:
        print(f"[upload] Edge upload failed: {exc}", file=sys.stderr)
        return 1

    print(f"[upload] Done - {result}")
    print("[upload] Run `moorcheh-edge status` - dimension and embedding_model should now be set.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
