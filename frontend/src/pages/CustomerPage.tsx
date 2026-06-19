import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ChatMessage, ConversationSummary } from "../api/client";
import { browserVoiceSupported, createStreamingSpeaker, listenOnce } from "../browserVoice";
import ChatThread from "../components/ChatThread";
import ConversationSidebar from "../components/ConversationSidebar";
import VoiceOverlay from "../components/VoiceOverlay";
import { useRotatingPhrase } from "../hooks/useRotatingPhrase";
import {
  LISTENING_PHRASES,
  THINKING_PHRASES,
} from "../thinkingPhrases";

type VoiceMode = "hardware" | "browser" | "none";
type SessionPhase =
  | "idle"
  | "listening"
  | "thinking"
  | "streaming"
  | "speaking"
  | "done"
  | "error";

function formatApiError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err);
  try {
    const parsed = JSON.parse(raw) as { detail?: string };
    if (parsed.detail) return parsed.detail;
  } catch {
    /* not JSON */
  }
  return raw;
}

export default function CustomerPage() {
  const { conversationId: routeConversationId } = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();

  const [query, setQuery] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [edgeUrl, setEdgeUrl] = useState("");
  const [voiceMode, setVoiceMode] = useState<VoiceMode>("none");
  const [error, setError] = useState("");
  const [phase, setPhase] = useState<SessionPhase>("idle");
  const [statusLine, setStatusLine] = useState("");
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const [streamingAnswer, setStreamingAnswer] = useState<string | null>(null);
  const [maxCustomerQuestions, setMaxCustomerQuestions] = useState(4);

  const busy = phase !== "idle" && phase !== "done" && phase !== "error";
  const userQuestionCount = useMemo(
    () => messages.filter((message) => message.role === "user").length,
    [messages],
  );
  const atQuestionLimit = userQuestionCount >= maxCustomerQuestions;
  const questionLimitMessage = `This chat allows up to ${maxCustomerQuestions} questions. Start a new chat to continue.`;
  const thinkingPhrase = useRotatingPhrase(THINKING_PHRASES, phase === "thinking");
  const listeningPhrase = useRotatingPhrase(LISTENING_PHRASES, phase === "listening", 1400);

  const reloadConversations = useCallback(async () => {
    const rows = await api.listConversations();
    setConversations(rows);
  }, []);

  const reloadConversation = useCallback(async (id: string) => {
    const detail = await api.getConversation(id);
    setMessages(detail.messages);
    setConversationId(detail.conversation_id);
  }, []);

  const refreshAll = useCallback(
    async (id: string) => {
      await Promise.all([reloadConversation(id), reloadConversations()]);
    },
    [reloadConversation, reloadConversations],
  );

  const chatTitle = useMemo(() => {
    const active = conversations.find((c) => c.conversation_id === conversationId);
    if (active?.title.trim()) return active.title.trim();
    const firstUser = messages.find((m) => m.role === "user");
    if (firstUser?.content.trim()) return firstUser.content.trim().slice(0, 72);
    return "New chat";
  }, [conversations, conversationId, messages]);

  useEffect(() => {
    api
      .health()
      .then((health) => {
        setEdgeUrl(health.edge_url);
        if (typeof health.max_customer_questions === "number" && health.max_customer_questions > 0) {
          setMaxCustomerQuestions(health.max_customer_questions);
        }
        if (health.voice_proxy_url) {
          setVoiceMode("hardware");
        } else if (browserVoiceSupported()) {
          setVoiceMode("browser");
        } else {
          setVoiceMode("none");
        }
      })
      .catch(() => {
        setEdgeUrl("(API unreachable)");
        setVoiceMode("none");
      });
    reloadConversations().catch(() => undefined);
  }, [reloadConversations]);

  useEffect(() => {
    if (!routeConversationId) {
      setConversationId(null);
      setMessages([]);
      return;
    }

    let cancelled = false;
    setConversationId(routeConversationId);
    reloadConversation(routeConversationId).catch((err) => {
      if (cancelled) return;
      setError(formatApiError(err));
      setMessages([]);
      navigate("/", { replace: true });
    });

    return () => {
      cancelled = true;
    };
  }, [routeConversationId, reloadConversation, navigate]);

  const resetPhase = () => {
    setPhase("idle");
    setStatusLine("");
    setError("");
    setPendingUser(null);
    setStreamingAnswer(null);
  };

  const ensureConversation = async (): Promise<string> => {
    if (routeConversationId) return routeConversationId;
    const created = await api.createConversation();
    await reloadConversations();
    navigate(`/chat/${created.conversation_id}`, { replace: true });
    return created.conversation_id;
  };

  const blockIfQuestionLimit = (): boolean => {
    if (!atQuestionLimit) return false;
    resetPhase();
    setError(questionLimitMessage);
    return true;
  };

  const startNewChat = async () => {
    if (busy) return;
    resetPhase();
    setQuery("");
    setError("");
    try {
      const created = await api.createConversation();
      await reloadConversations();
      navigate(`/chat/${created.conversation_id}`);
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const selectConversation = (id: string) => {
    if (busy || id === routeConversationId) return;
    resetPhase();
    setQuery("");
    setError("");
    navigate(`/chat/${id}`);
  };

  const deleteConversation = async (id: string) => {
    if (busy) return;
    const title =
      conversations.find((c) => c.conversation_id === id)?.title.trim() || "this chat";
    if (!window.confirm(`Delete "${title || "Untitled chat"}"? This cannot be undone.`)) {
      return;
    }
    setError("");
    try {
      await api.deleteConversation(id);
      await reloadConversations();
      if (routeConversationId === id) {
        resetPhase();
        setQuery("");
        setMessages([]);
        setConversationId(null);
        navigate("/", { replace: true });
      }
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const runAskStream = async (
    text: string,
    opts: {
      conversationId: string;
      inputMode: "text" | "voice";
      speak?: boolean;
      browserSpeech?: boolean;
    },
  ): Promise<boolean> => {
    setPhase("thinking");
    setStatusLine("Sending with chat history to edge…");
    setStreamingAnswer("");

    let accumulated = "";
    let gotToken = false;
    const browserSpeaker = opts.browserSpeech ? createStreamingSpeaker() : null;

    try {
      const result = await api.askStream(
        text,
        {
          conversationId: opts.conversationId,
          inputMode: opts.inputMode,
          speak: opts.speak ?? false,
        },
        {
          onHolding: () => {
            /* Keep thinking animation; holding audio plays on UNO Q in parallel with search. */
          },
          onToken: (delta) => {
            if (!gotToken) {
              gotToken = true;
              setPhase("streaming");
              setStatusLine("Streaming answer…");
            }
            accumulated += delta;
            setStreamingAnswer(accumulated);
            browserSpeaker?.push(delta);
          },
          onSentence: () => {
            if (opts.speak && opts.inputMode === "voice") {
              setPhase("speaking");
              setStatusLine("Playing answer on UNO Q speaker…");
            }
          },
        },
      );

      setStreamingAnswer(null);
      setQuery("");
      setPendingUser(null);

      if (result.conversation_id) {
        await refreshAll(result.conversation_id);
      }

      if (browserSpeaker) {
        browserSpeaker.flush();
        setPhase("speaking");
        setStatusLine("Speaking answer in browser…");
        await browserSpeaker.waitUntilIdle();
      }

      setPhase("done");
      setStatusLine("Answer ready.");
      return true;
    } catch (err) {
      setStreamingAnswer(null);
      setPendingUser(null);
      setPhase("error");
      setError(formatApiError(err));
      setStatusLine("");
      return false;
    }
  };

  const askText = async (event: React.FormEvent) => {
    event.preventDefault();
    const text = query.trim();
    if (!text) return;
    if (blockIfQuestionLimit()) return;

    resetPhase();
    setError("");

    try {
      const convId = await ensureConversation();
      await runAskStream(text, { conversationId: convId, inputMode: "text" });
    } catch {
      /* runAskStream sets error state */
    }
  };

  const askVoiceHardware = async () => {
    if (blockIfQuestionLimit()) return;

    resetPhase();
    setError("");
    setPhase("listening");
    setStatusLine(listeningPhrase);

    try {
      const convId = await ensureConversation();
      let heard = "";

      try {
        const listenResult = await api.voiceListen();
        heard = listenResult.heard.trim();
      } catch {
        setPhase("thinking");
        setStatusLine("Using one-shot voice ask…");
        const legacy = await api.askVoice({ conversationId: convId });
        heard = legacy.heard;
        setQuery("");
        setPendingUser(heard);
        if (legacy.conversation_id) {
          await refreshAll(legacy.conversation_id);
        }
        setPendingUser(null);
        setPhase("done");
        setStatusLine("Done.");
        return;
      }

      if (!heard) {
        throw new Error("No speech heard. Try again and speak clearly.");
      }

      setPendingUser(heard);
      const ok = await runAskStream(heard, {
        conversationId: convId,
        inputMode: "voice",
        speak: true,
      });
      if (ok) setStatusLine("Done.");
    } catch (err) {
      setPendingUser(null);
      setStreamingAnswer(null);
      setPhase("error");
      setError(formatApiError(err));
      setStatusLine("");
    }
  };

  const askVoiceBrowser = async () => {
    if (blockIfQuestionLimit()) return;

    resetPhase();
    setError("");
    setPhase("listening");
    setStatusLine(listeningPhrase);
    try {
      const convId = await ensureConversation();
      const transcript = await listenOnce();
      setPendingUser(transcript);
      const ok = await runAskStream(transcript, {
        conversationId: convId,
        inputMode: "voice",
        browserSpeech: true,
      });
      if (ok) setStatusLine("Done.");
    } catch (err) {
      setPendingUser(null);
      setStreamingAnswer(null);
      setPhase("error");
      setError(formatApiError(err));
      setStatusLine("");
    }
  };

  const askVoice = () => {
    if (voiceMode === "hardware") return askVoiceHardware();
    return askVoiceBrowser();
  };

  useEffect(() => {
    if (phase === "listening") setStatusLine(listeningPhrase);
    if (phase === "thinking") setStatusLine(thinkingPhrase);
  }, [phase, listeningPhrase, thinkingPhrase]);

  const voiceOverlayActive = phase === "listening";

  return (
    <div className={`customer-shell${voiceOverlayActive ? " customer-shell--voice" : ""}`}>
      <ConversationSidebar
        conversations={conversations}
        activeId={conversationId}
        onSelect={selectConversation}
        onDelete={deleteConversation}
        onNewChat={startNewChat}
        busy={busy}
      />

      <div className="customer-chat-column">
        <div className="chat-unified panel panel--flush">
          <ChatThread
            title={chatTitle}
            messages={messages}
            pendingUser={pendingUser}
            streamingAnswer={phase === "streaming" || phase === "speaking" ? streamingAnswer : null}
            thinkingPhrase={thinkingPhrase}
            showThinking={phase === "thinking"}
            dimmed={voiceOverlayActive}
          />

          <footer className="composer-bar">
            <form className="composer-bar-form" onSubmit={askText}>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={atQuestionLimit ? questionLimitMessage : "Message…"}
                disabled={busy || atQuestionLimit}
                aria-label="Your question"
              />
              {voiceMode !== "none" ? (
                <button
                  type="button"
                  className="btn btn--voice btn--icon"
                  disabled={busy}
                  onClick={askVoice}
                  title={atQuestionLimit ? questionLimitMessage : "Ask with voice"}
                  aria-label={atQuestionLimit ? questionLimitMessage : "Ask with voice"}
                >
                  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden>
                    <path
                      fill="currentColor"
                      d="M12 14a3 3 0 0 0 3-3V5a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2Z"
                    />
                  </svg>
                </button>
              ) : null}
              <button
                type="submit"
                className="btn btn--primary btn--icon"
                disabled={busy || atQuestionLimit || !query.trim()}
                title={atQuestionLimit ? questionLimitMessage : "Send"}
                aria-label="Send message"
              >
                ↑
              </button>
            </form>
            {error ? <div className="alert alert--error composer-error">{error}</div> : null}
          </footer>
        </div>

        {voiceOverlayActive ? (
          <VoiceOverlay phase="listening" statusLine={statusLine} />
        ) : null}
      </div>
    </div>
  );
}
