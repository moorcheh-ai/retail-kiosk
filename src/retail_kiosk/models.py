from __future__ import annotations

from pydantic import BaseModel, Field

from retail_kiosk.config import DEFAULT_SEARCH_THRESHOLD, DEFAULT_TOP_K


class DocumentCreate(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)
    category: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=256)
    tags: list[str] = Field(default_factory=list)
    text: str = Field(..., min_length=1)


class DocumentUpdate(BaseModel):
    category: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=256)
    tags: list[str] = Field(default_factory=list)
    text: str = Field(..., min_length=1)


class ChunkRecord(BaseModel):
    chunk_id: str
    doc_id: str
    chunk_index: int
    category: str
    title: str
    tags: str
    text: str
    edge_url: str
    updated_at: str


class DocumentDetail(BaseModel):
    doc_id: str
    category: str
    title: str
    tags: list[str]
    text: str
    chunks: list[ChunkRecord]


class AskRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=20)
    kiosk_mode: bool = True
    threshold: float = Field(default=DEFAULT_SEARCH_THRESHOLD, ge=0.0, le=1.0)
    conversation_id: str | None = None
    input_mode: str = Field(default="text", pattern="^(text|voice)$")
    speak: bool = False


class AskResponse(BaseModel):
    query: str
    answer: str
    model: str | None = None
    context_count: int | None = None
    sources: list[dict] | None = None
    conversation_id: str | None = None


class SyncResult(BaseModel):
    doc_id: str
    chunks_uploaded: int
    chunks_deleted: int
    chunk_ids: list[str]


class CatalogSyncResult(BaseModel):
    edge_url: str
    documents: int
    chunks: int


class KioskPromptSettings(BaseModel):
    header_prompt: str = Field(..., min_length=1, max_length=8000)
    footer_prompt: str = Field(..., min_length=1, max_length=8000)


class KioskVoiceSettings(BaseModel):
    store_name: str = Field(default="Our Store", min_length=1, max_length=256)
    holding_promo: str = Field(default="", max_length=2000)
    holding_enabled: bool = True
    holding_template: str | None = Field(default=None, max_length=4000)
    greeting_reply: str = Field(default="", max_length=2000)
    thanks_reply: str = Field(default="", max_length=2000)
    farewell_reply: str = Field(default="", max_length=2000)
    help_reply: str = Field(default="", max_length=2000)
    chitchat_reply: str = Field(default="", max_length=2000)
    ack_reply: str = Field(default="", max_length=2000)


class VoiceAskRequest(BaseModel):
    seconds: int | None = Field(default=None, ge=1, le=60)
    until_silence: bool = True
    max_seconds: int = Field(default=30, ge=3, le=60)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=20)
    kiosk_mode: bool = True
    threshold: float = Field(default=DEFAULT_SEARCH_THRESHOLD, ge=0.0, le=1.0)
    speak: bool = True
    query: str | None = None
    conversation_id: str | None = None


class VoiceAskResponse(AskResponse):
    heard: str
    spoke: bool = True


class VoiceListenRequest(BaseModel):
    until_silence: bool = True
    max_seconds: int = Field(default=30, ge=3, le=60)
    seconds: int | None = Field(default=None, ge=1, le=60)


class VoiceListenResponse(BaseModel):
    heard: str


class VoiceSpeakRequest(BaseModel):
    text: str = Field(..., min_length=1)


class VoiceSpeakResponse(BaseModel):
    spoke: bool = True


class ConversationCreate(BaseModel):
    title: str = Field(default="", max_length=200)


class ChatMessage(BaseModel):
    message_id: int
    conversation_id: str
    role: str
    content: str
    input_mode: str
    model: str | None = None
    context_count: int | None = None
    created_at: str


class ConversationSummary(BaseModel):
    conversation_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class ConversationDetail(BaseModel):
    conversation_id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[ChatMessage]
