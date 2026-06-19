from __future__ import annotations

from pathlib import Path

import pytest

from retail_kiosk.catalog import ChunkCatalog, parse_tags
from retail_kiosk.chunking import (
    build_meta_header,
    build_document_chunks,
    chunk_id_for,
    format_tags,
)


class FakeEmbedder:
    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def _get_count_tokenizer(self):
        raise RuntimeError("not used in short-text tests")


def test_chunk_id_format() -> None:
    assert chunk_id_for("return-policy", 0) == "return-policy#chunk-0"


def test_meta_header_includes_fields() -> None:
    header = build_meta_header(
        doc_id="return-policy",
        category="faq",
        title="Returns",
        tags=["returns", "receipt"],
        chunk_index=1,
    )
    assert "doc_id: return-policy" in header
    assert "category: faq" in header
    assert "chunk: 1" in header
    assert header.startswith("[meta]")


def test_build_document_chunks_single() -> None:
    embedder = FakeEmbedder()
    chunks = build_document_chunks(
        doc_id="hours",
        category="info",
        title="Store Hours",
        tags=["hours"],
        body="Open 9am to 9pm daily.",
        embedder=embedder,
    )
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "hours#chunk-0"
    assert "[meta]" in chunks[0].text
    assert "Open 9am" in chunks[0].text


def test_catalog_roundtrip(tmp_path: Path) -> None:
    catalog = ChunkCatalog(tmp_path / "test.db")
    embedder = FakeEmbedder()
    built = build_document_chunks(
        doc_id="faq-1",
        category="faq",
        title="Test",
        tags=[],
        body="Hello world.",
        embedder=embedder,
    )
    catalog.replace_doc_chunks(edge_url="http://edge:8080", chunks=built, source_text="Hello world.")
    rows = catalog.list_chunks()
    assert len(rows) == 1
    assert rows[0].chunk_id == "faq-1#chunk-0"
    assert catalog.doc_exists("faq-1")
    assert catalog.chunk_ids_for_doc("faq-1") == ["faq-1#chunk-0"]

    deleted = catalog.delete_doc("faq-1")
    assert deleted == ["faq-1#chunk-0"]
    assert not catalog.doc_exists("faq-1")


def test_parse_tags() -> None:
    assert parse_tags("a,b, c") == ["a", "b", "c"]
    assert format_tags(["a", " b "]) == "a,b"


def test_conversation_roundtrip(tmp_path: Path) -> None:
    catalog = ChunkCatalog(tmp_path / "chat.db")
    conv_id = catalog.create_conversation(title="")
    assert catalog.conversation_exists(conv_id)

    user_msg = catalog.add_message(
        conv_id,
        role="user",
        content="Hello, how are you?",
        input_mode="voice",
    )
    assistant_msg = catalog.add_message(
        conv_id,
        role="assistant",
        content="Hi there!",
        input_mode="voice",
        model="test-model",
        context_count=3,
    )
    assert user_msg.message_id > 0
    assert assistant_msg.content == "Hi there!"

    messages = catalog.get_conversation_messages(conv_id)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].context_count == 3

    summary = catalog.get_conversation_summary(conv_id)
    assert summary is not None
    assert summary.message_count == 2
    assert summary.title == "Hello, how are you?"

    summaries = catalog.list_conversations()
    assert len(summaries) == 1
    assert summaries[0].conversation_id == conv_id


def test_delete_conversation(tmp_path: Path) -> None:
    catalog = ChunkCatalog(tmp_path / "delete-chat.db")
    conv_id = catalog.create_conversation(title="To delete")
    catalog.add_message(conv_id, role="user", content="Hello", input_mode="text")
    assert catalog.delete_conversation(conv_id)
    assert not catalog.conversation_exists(conv_id)
    assert catalog.get_conversation_messages(conv_id) == []
    assert catalog.delete_conversation(conv_id) is False


def test_chat_history_builds_prior_turns(tmp_path: Path) -> None:
    from retail_kiosk.conversations import build_chat_history

    catalog = ChunkCatalog(tmp_path / "history.db")
    conv_id = catalog.create_conversation(title="")
    catalog.add_message(conv_id, role="user", content="What is acetone?", input_mode="text")
    catalog.add_message(conv_id, role="assistant", content="Acetone is a solvent.", input_mode="text")
    catalog.add_message(conv_id, role="user", content="Tell me more.", input_mode="voice")

    history = build_chat_history(catalog, conv_id)
    assert history == [
        {"role": "user", "content": "What is acetone?"},
        {"role": "assistant", "content": "Acetone is a solvent."},
        {"role": "user", "content": "Tell me more."},
    ]

    assert build_chat_history(catalog, None) == []
    assert build_chat_history(catalog, "missing-id") == []


def test_chat_history_limits_user_turns(tmp_path: Path) -> None:
    from retail_kiosk.conversations import build_chat_history

    catalog = ChunkCatalog(tmp_path / "trim.db")
    conv_id = catalog.create_conversation(title="")
    pairs = [
        ("Q1", "A1"),
        ("Q2", "A2"),
        ("Q3", "A3"),
        ("Q4", "A4"),
    ]
    for user, assistant in pairs:
        catalog.add_message(conv_id, role="user", content=user, input_mode="text")
        catalog.add_message(conv_id, role="assistant", content=assistant, input_mode="text")

    history = build_chat_history(catalog, conv_id, max_user_turns=3)
    assert history == [
        {"role": "user", "content": "Q2"},
        {"role": "assistant", "content": "A2"},
        {"role": "user", "content": "Q3"},
        {"role": "assistant", "content": "A3"},
        {"role": "user", "content": "Q4"},
        {"role": "assistant", "content": "A4"},
    ]


def test_customer_question_limit(tmp_path: Path) -> None:
    from retail_kiosk.conversations import assert_customer_may_ask, count_user_messages

    catalog = ChunkCatalog(tmp_path / "limit.db")
    conv_id = catalog.create_conversation(title="")
    for index in range(4):
        catalog.add_message(conv_id, role="user", content=f"Q{index + 1}", input_mode="text")
        catalog.add_message(conv_id, role="assistant", content=f"A{index + 1}", input_mode="text")

    assert count_user_messages(catalog, conv_id) == 4
    try:
        assert_customer_may_ask(catalog, conv_id)
        raise AssertionError("expected limit error")
    except ValueError as exc:
        assert "4 questions" in str(exc)


def test_voice_listen_request_defaults() -> None:
    from retail_kiosk.models import VoiceListenRequest

    req = VoiceListenRequest()
    assert req.until_silence is True
    assert req.seconds is None
    assert req.max_seconds == 30


def test_prompt_settings_roundtrip(tmp_path: Path) -> None:
    from retail_kiosk.config import DEFAULT_FOOTER_PROMPT, DEFAULT_HEADER_PROMPT
    from retail_kiosk.models import KioskPromptSettings

    catalog = ChunkCatalog(tmp_path / "prompts.db")
    defaults = catalog.get_prompt_settings()
    assert defaults.header_prompt == DEFAULT_HEADER_PROMPT
    assert defaults.footer_prompt == DEFAULT_FOOTER_PROMPT

    updated = catalog.update_prompt_settings(
        KioskPromptSettings(
            header_prompt="Custom header for the store.",
            footer_prompt="Reply in one short sentence.",
        )
    )
    assert updated.header_prompt == "Custom header for the store."
    reloaded = catalog.get_prompt_settings()
    assert reloaded.footer_prompt == "Reply in one short sentence."


def test_voice_settings_roundtrip(tmp_path: Path) -> None:
    from retail_kiosk.config import DEFAULT_HOLDING_PROMO, DEFAULT_STORE_NAME
    from retail_kiosk.models import KioskVoiceSettings

    catalog = ChunkCatalog(tmp_path / "voice.db")
    defaults = catalog.get_voice_settings()
    assert defaults.store_name == DEFAULT_STORE_NAME
    assert defaults.holding_promo == DEFAULT_HOLDING_PROMO
    assert defaults.holding_enabled is True

    updated = catalog.update_voice_settings(
        KioskVoiceSettings(
            store_name="Demo Market",
            holding_promo="Ten percent off all drinks today.",
            holding_enabled=True,
        )
    )
    assert updated.store_name == "Demo Market"
    assert catalog.get_voice_settings().holding_promo == "Ten percent off all drinks today."


def test_holding_wav_path_default() -> None:
    from moorcheh_edge._voice_holding import (
        DEFAULT_HOLDING_SCRIPT,
        HOLDING_WAV_FILENAME,
        holding_wav_path,
    )

    path = holding_wav_path()
    assert path.name == HOLDING_WAV_FILENAME
    assert "June" not in DEFAULT_HOLDING_SCRIPT
    assert "{query}" not in DEFAULT_HOLDING_SCRIPT
