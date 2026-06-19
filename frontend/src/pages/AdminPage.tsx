import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ChunkRecord, KioskPromptSettings } from "../api/client";

type DocSummary = {
  doc_id: string;
  category: string;
  title: string;
  tags: string;
  updated_at: string;
};

type AdminTab = "documents" | "prompts" | "catalog";

const emptyForm = {
  doc_id: "",
  category: "faq",
  title: "",
  tags: "",
  text: "",
};

export default function AdminPage() {
  const [tab, setTab] = useState<AdminTab>("documents");
  const [chunks, setChunks] = useState<ChunkRecord[]>([]);
  const [documents, setDocuments] = useState<DocSummary[]>([]);
  const [edgeUrl, setEdgeUrl] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [prompts, setPrompts] = useState<KioskPromptSettings>({
    header_prompt: "",
    footer_prompt: "",
  });
  const [promptStatus, setPromptStatus] = useState("");

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [chunkRows, docRows, promptSettings, health] = await Promise.all([
        api.listChunks(),
        api.listDocuments(),
        api.getPromptSettings(),
        api.health(),
      ]);
      setChunks(chunkRows);
      setDocuments(docRows);
      setPrompts(promptSettings);
      setEdgeUrl(health.edge_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const stats = useMemo(
    () => ({
      documents: documents.length,
      chunks: chunks.length,
      categories: new Set(documents.map((d) => d.category)).size,
    }),
    [documents, chunks],
  );

  const loadForEdit = async (docId: string) => {
    setError("");
    setBusy(true);
    try {
      const doc = await api.getDocument(docId);
      setEditingId(docId);
      setTab("documents");
      setForm({
        doc_id: doc.doc_id,
        category: doc.category,
        title: doc.title,
        tags: doc.tags.join(", "),
        text: doc.text,
      });
      setStatus(`Editing ${docId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const resetForm = () => {
    setEditingId(null);
    setForm(emptyForm);
    setStatus("");
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setStatus("");
    const tags = form.tags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    try {
      if (editingId) {
        const result = await api.updateDocument(editingId, {
          category: form.category,
          title: form.title,
          tags,
          text: form.text,
        });
        setStatus(
          `Updated ${result.doc_id}: ${result.chunks_uploaded} chunk(s) on edge, ${result.chunks_deleted} removed`,
        );
      } else {
        const result = await api.createDocument({
          doc_id: form.doc_id,
          category: form.category,
          title: form.title,
          tags,
          text: form.text,
        });
        setStatus(`Created ${result.doc_id}: ${result.chunks_uploaded} chunk(s) synced to edge`);
        setEditingId(result.doc_id);
        setForm((f) => ({ ...f, doc_id: result.doc_id }));
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (docId: string) => {
    if (!confirm(`Delete document ${docId} from edge and catalog?`)) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.deleteDocument(docId);
      setStatus(`Deleted ${docId}: ${result.chunks_deleted} chunk(s) removed`);
      if (editingId === docId) resetForm();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const savePrompts = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setPromptStatus("");
    try {
      const saved = await api.updatePromptSettings(prompts);
      setPrompts(saved);
      setPromptStatus("Prompts saved — used for every customer question.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="admin-layout">
      <header className="admin-header">
        <div>
          <p className="eyebrow">Admin dashboard</p>
          <h2>Store knowledge base</h2>
          <p className="hero-sub">
            Embed on PC · sync to edge at <code className="inline-code">{edgeUrl || "…"}</code>
          </p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={refresh} disabled={busy}>
          Refresh
        </button>
      </header>

      <div className="stat-row">
        <div className="stat-card">
          <span className="stat-value">{stats.documents}</span>
          <span className="stat-label">Documents</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{stats.chunks}</span>
          <span className="stat-label">Chunks on edge</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{stats.categories}</span>
          <span className="stat-label">Categories</span>
        </div>
      </div>

      {error ? <div className="alert alert--error">{error}</div> : null}
      {status ? <div className="alert alert--success">{status}</div> : null}

      <div className="tab-bar">
        <button
          type="button"
          className={`tab ${tab === "documents" ? "tab--active" : ""}`}
          onClick={() => setTab("documents")}
        >
          Documents
        </button>
        <button
          type="button"
          className={`tab ${tab === "prompts" ? "tab--active" : ""}`}
          onClick={() => setTab("prompts")}
        >
          LLM prompts
        </button>
        <button
          type="button"
          className={`tab ${tab === "catalog" ? "tab--active" : ""}`}
          onClick={() => setTab("catalog")}
        >
          Chunk catalog
        </button>
      </div>

      {tab === "documents" ? (
        <div className="admin-split">
          <section className="panel">
            <h3>{editingId ? "Edit document" : "Add document"}</h3>
            <form className="stack" onSubmit={submit}>
              <div className="field-row">
                <label className="field">
                  <span className="field-label">Document ID</span>
                  <input
                    required
                    disabled={!!editingId}
                    value={form.doc_id}
                    onChange={(e) => setForm({ ...form, doc_id: e.target.value })}
                    placeholder="return-policy"
                  />
                </label>
                <label className="field">
                  <span className="field-label">Category</span>
                  <input
                    required
                    value={form.category}
                    onChange={(e) => setForm({ ...form, category: e.target.value })}
                    placeholder="faq"
                  />
                </label>
              </div>
              <label className="field">
                <span className="field-label">Title</span>
                <input
                  required
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                />
              </label>
              <label className="field">
                <span className="field-label">Tags (comma-separated)</span>
                <input
                  value={form.tags}
                  onChange={(e) => setForm({ ...form, tags: e.target.value })}
                />
              </label>
              <label className="field">
                <span className="field-label">Content</span>
                <textarea
                  required
                  value={form.text}
                  onChange={(e) => setForm({ ...form, text: e.target.value })}
                  rows={8}
                />
              </label>
              <div className="action-row">
                <button type="submit" className="btn btn--primary" disabled={busy}>
                  {editingId ? "Update on edge" : "Upload to edge"}
                </button>
                {editingId ? (
                  <button type="button" className="btn btn--ghost" onClick={resetForm}>
                    Cancel
                  </button>
                ) : null}
              </div>
            </form>
          </section>

          <section className="panel">
            <h3>All documents</h3>
            {documents.length === 0 ? (
              <p className="muted">No documents yet. Add one to sync to the edge device.</p>
            ) : (
              <div className="doc-list">
                {documents.map((doc) => (
                  <article key={doc.doc_id} className="doc-card">
                    <div>
                      <span className="doc-id">{doc.doc_id}</span>
                      <span className="badge">{doc.category}</span>
                    </div>
                    <h4>{doc.title}</h4>
                    <p className="muted small">Updated {doc.updated_at}</p>
                    <div className="action-row">
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={() => loadForEdit(doc.doc_id)}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn btn--danger btn--sm"
                        onClick={() => remove(doc.doc_id)}
                      >
                        Delete
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      ) : null}

      {tab === "prompts" ? (
        <section className="panel">
          <h3>Answer prompts</h3>
          <p className="muted">
            Header (system) and footer (user suffix) for every customer text or voice question.
          </p>
          <form className="stack" onSubmit={savePrompts}>
            <label className="field">
              <span className="field-label">Header prompt</span>
              <textarea
                required
                rows={6}
                value={prompts.header_prompt}
                onChange={(e) => setPrompts({ ...prompts, header_prompt: e.target.value })}
              />
            </label>
            <label className="field">
              <span className="field-label">Footer prompt</span>
              <textarea
                required
                rows={4}
                value={prompts.footer_prompt}
                onChange={(e) => setPrompts({ ...prompts, footer_prompt: e.target.value })}
              />
            </label>
            <button type="submit" className="btn btn--primary" disabled={busy}>
              Save prompts
            </button>
          </form>
          {promptStatus ? <div className="alert alert--success">{promptStatus}</div> : null}
        </section>
      ) : null}

      {tab === "catalog" ? (
        <section className="panel panel--flush">
          <h3 className="panel-pad">Chunks synced to edge ({chunks.length})</h3>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Chunk ID</th>
                  <th>Doc</th>
                  <th>#</th>
                  <th>Category</th>
                  <th>Preview</th>
                </tr>
              </thead>
              <tbody>
                {chunks.map((chunk) => (
                  <tr key={chunk.chunk_id}>
                    <td><code className="inline-code">{chunk.chunk_id}</code></td>
                    <td>{chunk.doc_id}</td>
                    <td>{chunk.chunk_index}</td>
                    <td><span className="badge">{chunk.category}</span></td>
                    <td className="preview-cell">{chunk.text.slice(0, 100)}…</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
