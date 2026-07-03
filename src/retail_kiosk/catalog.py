from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from retail_kiosk.chunking import BuiltChunk, format_tags
from retail_kiosk.config import (
    DEFAULT_FOOTER_PROMPT,
    DEFAULT_HEADER_PROMPT,
    DEFAULT_HOLDING_ENABLED,
    DEFAULT_HOLDING_PROMO,
    DEFAULT_STORE_NAME,
)
from retail_kiosk.models import (
    ChatMessage,
    ChunkRecord,
    ConversationSummary,
    KioskPromptSettings,
    KioskVoiceSettings,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class ChunkCatalog:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL,
                    edge_url TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_category ON chunks(category)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    doc_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '',
                    source_text TEXT NOT NULL,
                    edge_url TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kiosk_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    input_mode TEXT NOT NULL DEFAULT 'text',
                    model TEXT,
                    context_count INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                ON conversation_messages(conversation_id, message_id)
                """
            )
            self._ensure_default_settings(conn)

    def get_document_meta(self, doc_id: str) -> dict[str, str] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "doc_id": str(row["doc_id"]),
            "category": str(row["category"]),
            "title": str(row["title"]),
            "tags": str(row["tags"]),
            "source_text": str(row["source_text"]),
            "edge_url": str(row["edge_url"]),
            "updated_at": str(row["updated_at"]),
        }

    def upsert_document(
        self,
        *,
        doc_id: str,
        category: str,
        title: str,
        tags: list[str],
        source_text: str,
        edge_url: str,
    ) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO documents (
                    doc_id, category, title, tags, source_text, edge_url, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    category = excluded.category,
                    title = excluded.title,
                    tags = excluded.tags,
                    source_text = excluded.source_text,
                    edge_url = excluded.edge_url,
                    updated_at = excluded.updated_at
                """,
                (
                    doc_id,
                    category,
                    title,
                    format_tags(tags),
                    source_text,
                    edge_url,
                    now,
                ),
            )

    def list_documents(self) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT doc_id, category, title, tags, updated_at FROM documents ORDER BY doc_id"
            ).fetchall()
        return [
            {
                "doc_id": str(row["doc_id"]),
                "category": str(row["category"]),
                "title": str(row["title"]),
                "tags": str(row["tags"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def list_chunks(
        self,
        *,
        doc_id: str | None = None,
        category: str | None = None,
    ) -> list[ChunkRecord]:
        query = "SELECT * FROM chunks WHERE 1=1"
        params: list[str] = []
        if doc_id:
            query += " AND doc_id = ?"
            params.append(doc_id)
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY doc_id, chunk_index"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def chunk_ids_for_doc(self, doc_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT chunk_id FROM chunks WHERE doc_id = ? ORDER BY chunk_index",
                (doc_id,),
            ).fetchall()
        return [str(row["chunk_id"]) for row in rows]

    def get_doc_ids(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT doc_id FROM chunks ORDER BY doc_id"
            ).fetchall()
        return [str(row["doc_id"]) for row in rows]

    def doc_exists(self, doc_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM chunks WHERE doc_id = ? LIMIT 1",
                (doc_id,),
            ).fetchone()
        return row is not None

    def replace_doc_chunks(
        self,
        *,
        edge_url: str,
        chunks: list[BuiltChunk],
        source_text: str,
    ) -> None:
        if not chunks:
            return
        doc_id = chunks[0].doc_id
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            for chunk in chunks:
                conn.execute(
                    """
                    INSERT INTO chunks (
                        chunk_id, doc_id, chunk_index, category, title,
                        tags, text, edge_url, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.chunk_id,
                        chunk.doc_id,
                        chunk.chunk_index,
                        chunk.category,
                        chunk.title,
                        format_tags(chunk.tags),
                        chunk.text,
                        edge_url,
                        now,
                    ),
                )
        self.upsert_document(
            doc_id=doc_id,
            category=chunks[0].category,
            title=chunks[0].title,
            tags=chunks[0].tags,
            source_text=source_text,
            edge_url=edge_url,
        )

    def delete_doc(self, doc_id: str) -> list[str]:
        chunk_ids = self.chunk_ids_for_doc(doc_id)
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        return chunk_ids

    def replace_all_from_edge(
        self,
        *,
        edge_url: str,
        chunks: list[BuiltChunk],
    ) -> tuple[int, int]:
        """Replace the local catalog with chunks exported from Moorcheh Edge."""
        from retail_kiosk.chunk_meta import group_chunks_by_document, source_text_for_doc

        grouped = group_chunks_by_document(chunks)
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM documents")
            for doc_id in sorted(grouped):
                doc_chunks = sorted(grouped[doc_id], key=lambda row: row.chunk_index)
                first = doc_chunks[0]
                conn.execute(
                    """
                    INSERT INTO documents (
                        doc_id, category, title, tags, source_text, edge_url, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        first.category,
                        first.title,
                        format_tags(first.tags),
                        source_text_for_doc(doc_chunks),
                        edge_url,
                        now,
                    ),
                )
                for chunk in doc_chunks:
                    conn.execute(
                        """
                        INSERT INTO chunks (
                            chunk_id, doc_id, chunk_index, category, title,
                            tags, text, edge_url, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            chunk.chunk_id,
                            chunk.doc_id,
                            chunk.chunk_index,
                            chunk.category,
                            chunk.title,
                            format_tags(chunk.tags),
                            chunk.text,
                            edge_url,
                            now,
                        ),
                    )
        return len(grouped), len(chunks)

    def delete_chunk_ids(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._connect() as conn:
            conn.execute(
                f"DELETE FROM chunks WHERE chunk_id IN ({placeholders})",
                chunk_ids,
            )

    def get_prompt_settings(self) -> KioskPromptSettings:
        with self._connect() as conn:
            self._ensure_default_settings(conn)
            header = self._get_setting(conn, "header_prompt", DEFAULT_HEADER_PROMPT)
            footer = self._get_setting(conn, "footer_prompt", DEFAULT_FOOTER_PROMPT)
        return KioskPromptSettings(header_prompt=header, footer_prompt=footer)

    def get_voice_settings(self) -> KioskVoiceSettings:
        with self._connect() as conn:
            self._ensure_default_settings(conn)
            store_name = self._get_setting(conn, "store_name", DEFAULT_STORE_NAME)
            holding_promo = self._get_setting(conn, "holding_promo", DEFAULT_HOLDING_PROMO)
            holding_enabled = self._get_setting(
                conn, "holding_enabled", "true" if DEFAULT_HOLDING_ENABLED else "false"
            )
            template = self._get_setting(conn, "holding_template", "")
        enabled = holding_enabled.strip().lower() not in {"0", "false", "no", "off"}
        return KioskVoiceSettings(
            store_name=store_name,
            holding_promo=holding_promo,
            holding_enabled=enabled,
            holding_template=template or None,
        )

    def update_voice_settings(self, settings: KioskVoiceSettings) -> KioskVoiceSettings:
        store_name = settings.store_name.strip()
        holding_promo = settings.holding_promo.strip()
        if not store_name:
            raise ValueError("store_name must be non-empty")
        with self._connect() as conn:
            self._set_setting(conn, "store_name", store_name)
            self._set_setting(conn, "holding_promo", holding_promo)
            self._set_setting(
                conn,
                "holding_enabled",
                "true" if settings.holding_enabled else "false",
            )
            if settings.holding_template and settings.holding_template.strip():
                self._set_setting(conn, "holding_template", settings.holding_template.strip())
            else:
                conn.execute("DELETE FROM kiosk_settings WHERE key = ?", ("holding_template",))
        return self.get_voice_settings()

    def update_prompt_settings(self, settings: KioskPromptSettings) -> KioskPromptSettings:
        header = settings.header_prompt.strip()
        footer = settings.footer_prompt.strip()
        if not header or not footer:
            raise ValueError("header_prompt and footer_prompt must be non-empty")
        with self._connect() as conn:
            self._set_setting(conn, "header_prompt", header)
            self._set_setting(conn, "footer_prompt", footer)
        return KioskPromptSettings(header_prompt=header, footer_prompt=footer)

    @staticmethod
    def _ensure_default_settings(conn: sqlite3.Connection) -> None:
        defaults = {
            "header_prompt": DEFAULT_HEADER_PROMPT,
            "footer_prompt": DEFAULT_FOOTER_PROMPT,
            "store_name": DEFAULT_STORE_NAME,
            "holding_promo": DEFAULT_HOLDING_PROMO,
            "holding_enabled": "true" if DEFAULT_HOLDING_ENABLED else "false",
        }
        for key, value in defaults.items():
            row = conn.execute(
                "SELECT 1 FROM kiosk_settings WHERE key = ? LIMIT 1",
                (key,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO kiosk_settings (key, value) VALUES (?, ?)",
                    (key, value),
                )

    @staticmethod
    def _get_setting(conn: sqlite3.Connection, key: str, default: str) -> str:
        row = conn.execute(
            "SELECT value FROM kiosk_settings WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return default
        value = str(row["value"]).strip()
        return value or default

    @staticmethod
    def _set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            """
            INSERT INTO kiosk_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def create_conversation(self, title: str = "") -> str:
        conversation_id = str(uuid.uuid4())
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations (conversation_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, title[:200], now, now),
            )
        return conversation_id

    def conversation_exists(self, conversation_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM conversations WHERE conversation_id = ? LIMIT 1",
                (conversation_id,),
            ).fetchone()
        return row is not None

    def touch_conversation(self, conversation_id: str) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (now, conversation_id),
            )

    def get_conversation_summary(self, conversation_id: str) -> ConversationSummary | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    c.conversation_id,
                    c.title,
                    c.created_at,
                    c.updated_at,
                    COUNT(m.message_id) AS message_count
                FROM conversations c
                LEFT JOIN conversation_messages m
                    ON m.conversation_id = c.conversation_id
                WHERE c.conversation_id = ?
                GROUP BY c.conversation_id
                """,
                (conversation_id,),
            ).fetchone()
        if row is None:
            return None
        return ConversationSummary(
            conversation_id=str(row["conversation_id"]),
            title=str(row["title"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            message_count=int(row["message_count"]),
        )

    def list_conversations(self, *, limit: int = 30) -> list[ConversationSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.conversation_id,
                    c.title,
                    c.created_at,
                    c.updated_at,
                    COUNT(m.message_id) AS message_count
                FROM conversations c
                LEFT JOIN conversation_messages m
                    ON m.conversation_id = c.conversation_id
                GROUP BY c.conversation_id
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            ConversationSummary(
                conversation_id=str(row["conversation_id"]),
                title=str(row["title"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                message_count=int(row["message_count"]),
            )
            for row in rows
        ]

    def get_conversation_messages(self, conversation_id: str) -> list[ChatMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT message_id, conversation_id, role, content, input_mode,
                       model, context_count, created_at
                FROM conversation_messages
                WHERE conversation_id = ?
                ORDER BY message_id
                """,
                (conversation_id,),
            ).fetchall()
        return [self._row_to_chat_message(row) for row in rows]

    def add_message(
        self,
        conversation_id: str,
        *,
        role: str,
        content: str,
        input_mode: str = "text",
        model: str | None = None,
        context_count: int | None = None,
    ) -> ChatMessage:
        now = _utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO conversation_messages (
                    conversation_id, role, content, input_mode,
                    model, context_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    role,
                    content,
                    input_mode,
                    model,
                    context_count,
                    now,
                ),
            )
            message_id = int(cursor.lastrowid)
            conn.execute(
                """
                UPDATE conversations
                SET updated_at = ?,
                    title = CASE
                        WHEN title = '' AND ? = 'user' THEN substr(?, 1, 200)
                        ELSE title
                    END
                WHERE conversation_id = ?
                """,
                (now, role, content, conversation_id),
            )
        return ChatMessage(
            message_id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            input_mode=input_mode,
            model=model,
            context_count=context_count,
            created_at=now,
        )

    def ensure_conversation(self, conversation_id: str | None, *, title: str = "") -> str:
        if conversation_id and self.conversation_exists(conversation_id):
            return conversation_id
        return self.create_conversation(title=title)

    def delete_conversation(self, conversation_id: str) -> bool:
        if not self.conversation_exists(conversation_id):
            return False
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM conversation_messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.execute(
                "DELETE FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            )
        return True

    @staticmethod
    def _row_to_chat_message(row: sqlite3.Row) -> ChatMessage:
        return ChatMessage(
            message_id=int(row["message_id"]),
            conversation_id=str(row["conversation_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            input_mode=str(row["input_mode"]),
            model=str(row["model"]) if row["model"] is not None else None,
            context_count=int(row["context_count"])
            if row["context_count"] is not None
            else None,
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ChunkRecord:
        return ChunkRecord(
            chunk_id=str(row["chunk_id"]),
            doc_id=str(row["doc_id"]),
            chunk_index=int(row["chunk_index"]),
            category=str(row["category"]),
            title=str(row["title"]),
            tags=str(row["tags"]),
            text=str(row["text"]),
            edge_url=str(row["edge_url"]),
            updated_at=str(row["updated_at"]),
        )


def parse_tags(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]
