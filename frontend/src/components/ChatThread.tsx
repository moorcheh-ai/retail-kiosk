import { useEffect, useRef } from "react";
import type { ChatMessage } from "../api/client";

type Props = {
  title: string;
  messages: ChatMessage[];
  pendingUser?: string | null;
  streamingAnswer?: string | null;
  thinkingPhrase?: string | null;
  showThinking?: boolean;
  dimmed?: boolean;
};

export default function ChatThread({
  title,
  messages,
  pendingUser,
  streamingAnswer,
  thinkingPhrase,
  showThinking,
  dimmed,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = scrollRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [messages, pendingUser, streamingAnswer, showThinking, thinkingPhrase]);

  return (
    <>
      <header className={`chat-main-head${dimmed ? " chat-main-head--dimmed" : ""}`}>
        <h2>{title}</h2>
        <p className="muted small">
          {messages.length > 0
            ? `${messages.length} messages`
            : "Ask anything about the store catalog"}
        </p>
      </header>

      <div
        className={`chat-thread chat-thread--main${dimmed ? " chat-thread--dimmed" : ""}`}
        ref={scrollRef}
      >
        {messages.length === 0 && !pendingUser && !showThinking && !streamingAnswer ? (
          <div className="chat-welcome">
            <p className="eyebrow">Store assistant</p>
            <p>Type below or tap the mic. Follow-ups use this chat&apos;s history.</p>
          </div>
        ) : null}

        {messages.map((message) => (
          <div
            key={message.message_id}
            className={`chat-bubble chat-bubble--${message.role}${
              message.input_mode === "voice" ? " chat-bubble--voice-msg" : ""
            }`}
          >
            <div className="chat-bubble-meta">
              <span>{message.role === "user" ? "You" : "Assistant"}</span>
              {message.input_mode === "voice" ? (
                <span className="chat-tag">voice</span>
              ) : null}
            </div>
            {message.role === "user" ? (
              <p className="chat-heard-label">You asked:</p>
            ) : null}
            <p className="chat-bubble-text">{message.content}</p>
            {message.role === "assistant" && message.model ? (
              <p className="chat-bubble-foot muted small">
                {message.model}
                {message.context_count != null ? ` · ${message.context_count} chunks` : ""}
              </p>
            ) : null}
          </div>
        ))}

        {pendingUser ? (
          <div className="chat-bubble chat-bubble--user chat-bubble--voice-msg">
            <div className="chat-bubble-meta">
              <span>You</span>
              <span className="chat-tag">voice</span>
            </div>
            <p className="chat-heard-label">You asked:</p>
            <p className="chat-bubble-text">{pendingUser}</p>
          </div>
        ) : null}

        {showThinking ? (
          <div className="chat-bubble chat-bubble--assistant chat-bubble--thinking">
            <div className="chat-bubble-meta">
              <span>Assistant</span>
            </div>
            <div className="thinking-row">
              <span className="thinking-dots" aria-hidden>
                <span />
                <span />
                <span />
              </span>
              <p className="thinking-phrase">{thinkingPhrase}</p>
            </div>
          </div>
        ) : null}

        {streamingAnswer !== null && streamingAnswer !== undefined ? (
          <div className="chat-bubble chat-bubble--assistant chat-bubble--streaming">
            <div className="chat-bubble-meta">
              <span>Assistant</span>
            </div>
            <p className="chat-bubble-text">
              {streamingAnswer}
              <span className="stream-cursor" aria-hidden>
                ▍
              </span>
            </p>
          </div>
        ) : null}
      </div>
    </>
  );
}
