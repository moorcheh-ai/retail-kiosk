from __future__ import annotations

from retail_kiosk.catalog import ChunkCatalog
from retail_kiosk.config import chat_history_max_user_turns, max_customer_questions
from retail_kiosk.models import AskResponse, ConversationDetail, ConversationSummary

ChatHistoryTurn = dict[str, str]

QUESTION_LIMIT_MESSAGE = (
    "This chat allows up to {limit} questions. Start a new chat to continue."
)


def count_user_messages(catalog: ChunkCatalog, conversation_id: str | None) -> int:
    if not conversation_id or not catalog.conversation_exists(conversation_id):
        return 0
    return sum(
        1
        for message in catalog.get_conversation_messages(conversation_id)
        if message.role == "user" and message.content.strip()
    )


def assert_customer_may_ask(catalog: ChunkCatalog, conversation_id: str | None) -> None:
    limit = max_customer_questions()
    if count_user_messages(catalog, conversation_id) >= limit:
        raise ValueError(QUESTION_LIMIT_MESSAGE.format(limit=limit))


def build_chat_history(
    catalog: ChunkCatalog,
    conversation_id: str | None,
    *,
    max_user_turns: int | None = None,
) -> list[ChatHistoryTurn]:
    """Prior turns for this conversation (current question is not stored yet)."""
    limit = max_user_turns if max_user_turns is not None else chat_history_max_user_turns()
    if limit <= 0 or not conversation_id:
        return []
    if not catalog.conversation_exists(conversation_id):
        return []

    messages = catalog.get_conversation_messages(conversation_id)
    if not messages:
        return []

    user_indices: list[int] = []
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.role != "user" or not message.content.strip():
            continue
        user_indices.append(index)
        if len(user_indices) >= limit:
            break

    if not user_indices:
        return []

    start = min(user_indices)
    history: list[ChatHistoryTurn] = []
    for message in messages[start:]:
        if message.role not in ("user", "assistant"):
            continue
        content = message.content.strip()
        if not content:
            continue
        history.append({"role": message.role, "content": content})
    return history


def persist_exchange(
    catalog: ChunkCatalog,
    *,
    conversation_id: str | None,
    user_text: str,
    input_mode: str,
    result: AskResponse,
) -> str:
    conv_id = catalog.ensure_conversation(conversation_id, title=user_text[:200])
    catalog.add_message(
        conv_id,
        role="user",
        content=user_text,
        input_mode=input_mode,
    )
    catalog.add_message(
        conv_id,
        role="assistant",
        content=result.answer,
        input_mode=input_mode,
        model=result.model,
        context_count=result.context_count,
    )
    catalog.touch_conversation(conv_id)
    return conv_id


def get_conversation_detail(
    catalog: ChunkCatalog,
    conversation_id: str,
) -> ConversationDetail | None:
    summary = catalog.get_conversation_summary(conversation_id)
    if summary is None:
        return None
    return ConversationDetail(
        conversation_id=summary.conversation_id,
        title=summary.title,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        messages=catalog.get_conversation_messages(conversation_id),
    )


def list_conversation_summaries(catalog: ChunkCatalog) -> list[ConversationSummary]:
    return catalog.list_conversations()


__all__ = [
    "ChatHistoryTurn",
    "QUESTION_LIMIT_MESSAGE",
    "assert_customer_may_ask",
    "build_chat_history",
    "count_user_messages",
    "get_conversation_detail",
    "list_conversation_summaries",
    "persist_exchange",
]
