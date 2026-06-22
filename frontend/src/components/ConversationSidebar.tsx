import type { ConversationSummary } from "../api/client";

type Props = {
  conversations: ConversationSummary[];
  activeId: string | null;
  onSelect: (conversationId: string) => void;
  onDelete: (conversationId: string) => void;
  onNewChat: () => void;
  busy: boolean;
};

function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  if (sameDay) {
    return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function previewTitle(conversation: ConversationSummary): string {
  const title = conversation.title.trim();
  if (title) return title;
  if (conversation.message_count > 0) return "Untitled chat";
  return "New conversation";
}

export default function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onDelete,
  onNewChat,
  busy,
}: Props) {
  return (
    <aside className="conv-sidebar panel panel--flush">
      <div className="conv-sidebar-head">
        <h3>Chats</h3>
        <button
          type="button"
          className="btn btn--primary btn--sm"
          onClick={onNewChat}
          disabled={busy}
        >
          + New
        </button>
      </div>

      <div className="conv-sidebar-list">
        {conversations.length === 0 ? (
          <p className="conv-sidebar-empty muted small">No chats yet</p>
        ) : (
          conversations.map((conversation) => {
            const active = conversation.conversation_id === activeId;
            return (
              <div
                key={conversation.conversation_id}
                className={`conv-sidebar-row${active ? " conv-sidebar-row--active" : ""}`}
              >
                <button
                  type="button"
                  className="conv-sidebar-item"
                  onClick={() => onSelect(conversation.conversation_id)}
                  disabled={busy}
                >
                  <span className="conv-sidebar-item-title">{previewTitle(conversation)}</span>
                  <span className="conv-sidebar-item-meta muted small">
                    {formatWhen(conversation.updated_at)}
                    {conversation.message_count > 0
                      ? ` · ${conversation.message_count} msgs`
                      : " · empty"}
                  </span>
                </button>
                <button
                  type="button"
                  className="conv-sidebar-delete"
                  disabled={busy}
                  aria-label={`Delete ${previewTitle(conversation)}`}
                  title="Delete chat"
                  onClick={() => onDelete(conversation.conversation_id)}
                >
                  ×
                </button>
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
