import { parseSseChunk } from "../sse";

const base = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8765";
const DEFAULT_TIMEOUT_MS = 300_000;
const VOICE_TIMEOUT_MS = 300_000;
const DEFAULT_TOP_K = 2;
const DEFAULT_SEARCH_THRESHOLD = 0.3;

type RequestOptions = RequestInit & { timeoutMs?: number };

async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const timeoutMs = init?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const { timeoutMs: _ignored, ...fetchInit } = init ?? {};
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${base}${path}`, {
      ...fetchInit,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(fetchInit.headers ?? {}),
      },
    });
    if (!response.ok) {
      const body = await response.text();
      throw new Error(body || response.statusText);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    const text = await response.text();
    if (!text) {
      return undefined as T;
    }
    return JSON.parse(text) as T;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Request timed out");
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

export type ChunkRecord = {
  chunk_id: string;
  doc_id: string;
  chunk_index: number;
  category: string;
  title: string;
  tags: string;
  text: string;
  edge_url: string;
  updated_at: string;
};

export type DocumentDetail = {
  doc_id: string;
  category: string;
  title: string;
  tags: string[];
  text: string;
  chunks: ChunkRecord[];
};

export type SyncResult = {
  doc_id: string;
  chunks_uploaded: number;
  chunks_deleted: number;
  chunk_ids: string[];
};

export type CatalogSyncResult = {
  edge_url: string;
  documents: number;
  chunks: number;
};

export type AskResponse = {
  query: string;
  answer: string;
  model?: string;
  context_count?: number;
  conversation_id?: string;
};

export type HealthResponse = {
  status: string;
  edge_url: string;
  voice_available: boolean;
  voice_proxy_url?: string | null;
  catalog_db?: string;
  max_customer_questions?: number;
};

export type KioskPromptSettings = {
  header_prompt: string;
  footer_prompt: string;
};

export type VoiceAskResponse = AskResponse & {
  heard: string;
  spoke: boolean;
};

export type VoiceListenResponse = {
  heard: string;
};

export type ChatMessage = {
  message_id: number;
  conversation_id: string;
  role: "user" | "assistant" | string;
  content: string;
  input_mode: string;
  model?: string | null;
  context_count?: number | null;
  created_at: string;
};

export type ConversationSummary = {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
};

export type ConversationDetail = {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: ChatMessage[];
};

type AskOptions = {
  conversationId?: string | null;
  inputMode?: "text" | "voice";
  speak?: boolean;
};

export type AskStreamHandlers = {
  onMeta?: (data: Record<string, unknown>) => void;
  onHolding?: (data: Record<string, unknown>) => void;
  onThinking?: (data: Record<string, unknown>) => void;
  onToken?: (delta: string) => void;
  onSentence?: (text: string) => void;
  onDone?: (data: AskResponse) => void;
  onError?: (message: string) => void;
};

async function askStreamOnce(
  query: string,
  opts: AskOptions | undefined,
  handlers: AskStreamHandlers,
): Promise<AskResponse> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);

  let donePayload: AskResponse | null = null;

  try {
    const response = await fetch(`${base}/ask/stream`, {
      method: "POST",
      signal: controller.signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        top_k: DEFAULT_TOP_K,
        kiosk_mode: true,
        threshold: DEFAULT_SEARCH_THRESHOLD,
        conversation_id: opts?.conversationId ?? null,
        input_mode: opts?.inputMode ?? "text",
        speak: opts?.speak ?? false,
      }),
    });

    if (!response.ok) {
      const body = await response.text();
      throw new Error(body || response.statusText);
    }

    if (!response.body) {
      throw new Error("Streaming response body missing");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      const parsed = parseSseChunk(pending);
      pending = parsed.rest;

      for (const event of parsed.events) {
        let data: Record<string, unknown> = {};
        try {
          data = JSON.parse(event.data) as Record<string, unknown>;
        } catch {
          data = { raw: event.data };
        }

        if (event.event === "meta") {
          handlers.onMeta?.(data);
        } else if (event.event === "holding") {
          handlers.onHolding?.(data);
        } else if (event.event === "thinking") {
          handlers.onThinking?.(data);
        } else if (event.event === "token") {
          handlers.onToken?.(String(data.delta ?? ""));
        } else if (event.event === "sentence") {
          handlers.onSentence?.(String(data.text ?? ""));
        } else if (event.event === "done") {
          donePayload = {
            query: String(data.query ?? query),
            answer: String(data.answer ?? ""),
            model: data.model as string | undefined,
            context_count: data.context_count as number | undefined,
            conversation_id: data.conversation_id as string | undefined,
          };
          handlers.onDone?.(donePayload);
        } else if (event.event === "error") {
          const message = String(data.message ?? "Stream failed");
          handlers.onError?.(message);
          throw new Error(message);
        }
      }
    }

    if (pending.trim()) {
      const parsed = parseSseChunk(`${pending}\n\n`);
      for (const event of parsed.events) {
        if (event.event === "done") {
          const data = JSON.parse(event.data) as Record<string, unknown>;
          donePayload = {
            query: String(data.query ?? query),
            answer: String(data.answer ?? ""),
            model: data.model as string | undefined,
            context_count: data.context_count as number | undefined,
            conversation_id: data.conversation_id as string | undefined,
          };
          handlers.onDone?.(donePayload);
        }
      }
    }

    if (!donePayload) {
      throw new Error("Stream ended without a done event");
    }
    return donePayload;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Request timed out");
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

async function askStream(
  query: string,
  opts: AskOptions | undefined,
  handlers: AskStreamHandlers,
): Promise<AskResponse> {
  return askStreamOnce(query, opts, handlers);
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  listChunks: (params?: { doc_id?: string; category?: string }) => {
    const query = new URLSearchParams();
    if (params?.doc_id) query.set("doc_id", params.doc_id);
    if (params?.category) query.set("category", params.category);
    const suffix = query.toString() ? `?${query}` : "";
    return request<ChunkRecord[]>(`/admin/chunks${suffix}`);
  },
  listDocuments: () =>
    request<
      Array<{
        doc_id: string;
        category: string;
        title: string;
        tags: string;
        updated_at: string;
      }>
    >("/admin/documents"),
  syncFromEdge: () =>
    request<CatalogSyncResult>("/admin/sync-from-edge", {
      method: "POST",
    }),
  getDocument: (docId: string) =>
    request<DocumentDetail>(`/admin/documents/${encodeURIComponent(docId)}`),
  createDocument: (body: {
    doc_id: string;
    category: string;
    title: string;
    tags: string[];
    text: string;
  }) =>
    request<SyncResult>("/admin/documents", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateDocument: (
    docId: string,
    body: {
      category: string;
      title: string;
      tags: string[];
      text: string;
    },
  ) =>
    request<SyncResult>(`/admin/documents/${encodeURIComponent(docId)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteDocument: (docId: string) =>
    request<SyncResult>(`/admin/documents/${encodeURIComponent(docId)}`, {
      method: "DELETE",
    }),
  getPromptSettings: () => request<KioskPromptSettings>("/admin/settings"),
  updatePromptSettings: (body: KioskPromptSettings) =>
    request<KioskPromptSettings>("/admin/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  createConversation: (title = "") =>
    request<ConversationSummary>("/conversations", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  listConversations: () => request<ConversationSummary[]>("/conversations"),
  getConversation: (conversationId: string) =>
    request<ConversationDetail>(`/conversations/${encodeURIComponent(conversationId)}`),
  deleteConversation: (conversationId: string) =>
    request<void>(`/conversations/${encodeURIComponent(conversationId)}`, {
      method: "DELETE",
    }),
  ask: (query: string, opts?: AskOptions) =>
    request<AskResponse>("/ask", {
      method: "POST",
      body: JSON.stringify({
        query,
        top_k: DEFAULT_TOP_K,
        kiosk_mode: true,
        threshold: DEFAULT_SEARCH_THRESHOLD,
        conversation_id: opts?.conversationId ?? null,
        input_mode: opts?.inputMode ?? "text",
      }),
    }),
  askStream,
  voiceListen: (opts?: { untilSilence?: boolean; maxSeconds?: number; seconds?: number }) =>
    request<VoiceListenResponse>("/ask/voice/listen", {
      method: "POST",
      body: JSON.stringify({
        until_silence: opts?.seconds ? false : (opts?.untilSilence ?? true),
        max_seconds: opts?.maxSeconds ?? 30,
        ...(opts?.seconds ? { seconds: opts.seconds } : {}),
      }),
      timeoutMs: VOICE_TIMEOUT_MS,
    }),
  voiceSpeak: (text: string) =>
    request<{ spoke: boolean }>("/ask/voice/speak", {
      method: "POST",
      body: JSON.stringify({ text }),
      timeoutMs: VOICE_TIMEOUT_MS,
    }),
  askVoice: (opts?: { conversationId?: string | null }) =>
    request<VoiceAskResponse>("/ask/voice", {
      method: "POST",
      body: JSON.stringify({
        until_silence: true,
        max_seconds: 30,
        top_k: DEFAULT_TOP_K,
        kiosk_mode: true,
        threshold: DEFAULT_SEARCH_THRESHOLD,
        speak: true,
        conversation_id: opts?.conversationId ?? null,
      }),
      timeoutMs: VOICE_TIMEOUT_MS,
    }),
};

export { base as apiBaseUrl };
