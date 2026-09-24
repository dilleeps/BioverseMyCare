import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { fmtDateTime } from "../../format.js";
import { Back, Check, Warning } from "../../icons.jsx";
import { WorkspaceLayout } from "../../layouts.jsx";
import AuthImage from "./AuthImage.jsx";

const STATUS = { open: "Waiting for you", replied: "Replied, still open", resolved: "Resolved" };

// Clinician: skin photos patients chose to send, open ones first.
export function SkinPhotoList() {
  const { data, error, loading } = useApi("/photo-questions/skin");
  return (
    <WorkspaceLayout>
      <div className="page-head">
        <div>
          <h1 className="page-title">Patient photos</h1>
          <div className="page-sub">Skin photos patients sent with a note. They were not assessed by AI.</div>
        </div>
      </div>
      {loading && <div className="skeleton" />}
      {error && <div className="error-box">{error.message}</div>}
      {data && data.length === 0 && <div className="card empty">No patient photos yet.</div>}
      <div className="stack">
        {data?.map((s) => (
          <Link key={s.id} to={`/clinician/skin-photos/${s.id}`} className="hub-card skin-row">
            <AuthImage path={s.image_url} alt="" className="photo-thumb" />
            <span style={{ flexGrow: 1, minWidth: 0 }}>
              <span className="strong" style={{ display: "block" }}>{s.patient_name}</span>
              <span className="small muted">{fmtDateTime(s.created_at)} · {s.note || "No note"}</span>
            </span>
            {s.level === "urgent" && s.status !== "resolved" && <span className="chip warn">Warning signs</span>}
            <span className={`chip ${s.status === "resolved" ? "ok" : ""}`}>{STATUS[s.status]}</span>
          </Link>
        ))}
      </div>
    </WorkspaceLayout>
  );
}

export function SkinPhotoDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: s, error, loading, reload } = useApi(`/photo-questions/skin/${id}`);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);

  async function act(path, body) {
    setBusy(true);
    setActionError(null);
    try {
      await api(`/photo-questions/skin/${id}/${path}`, { method: "POST", body });
      setText("");
      reload();
    } catch (e) {
      setActionError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <WorkspaceLayout>
      <button type="button" className="btn ghost sm" onClick={() => navigate("/clinician/skin-photos")}>
        <Back size={16} /> All patient photos
      </button>
      {loading && <div className="skeleton" style={{ marginTop: 12 }} />}
      {error && <div className="error-box" style={{ marginTop: 12 }}>{error.message}</div>}
      {s && (
        <div className="ws-grid skin-detail" style={{ marginTop: 12 }}>
          <section className="card stack span-7">
            <div className="row between wrap">
              <div>
                <h1 className="page-title" style={{ fontSize: 24 }}>{s.patient_name}</h1>
                <div className="small muted">Sent {fmtDateTime(s.created_at)} · consented {fmtDateTime(s.consented_at)}</div>
              </div>
              <span className={`chip ${s.status === "resolved" ? "ok" : s.level === "urgent" ? "warn" : ""}`}>{STATUS[s.status]}</span>
            </div>
            <AuthImage path={s.image_url} alt={`Skin photo sent by ${s.patient_name}`} className="skin-photo-full" />
          </section>
          <section className="card stack span-5">
            <div>
              <div className="small strong">Patient's note</div>
              <p>{s.note || "No note."}</p>
            </div>
            <div>
              <div className="small strong">Safety checklist</div>
              {s.checklist_labels.length ? (
                <ul className="skin-flags">{s.checklist_labels.map((l) => <li key={l}><Warning size={14} /> {l}</li>)}</ul>
              ) : (
                <p className="small muted">None of the warning signs.</p>
              )}
            </div>
            {s.reply && (
              <div className="bubble assistant" style={{ maxWidth: "100%" }}>
                <div className="small strong">{s.replied_by_name} replied {fmtDateTime(s.replied_at)}</div>
                {s.reply}
              </div>
            )}
            {s.status !== "resolved" ? (
              <>
                <label htmlFor="skin-reply" className="small strong">Reply to {s.patient_name.split(" ")[0]}</label>
                <textarea id="skin-reply" className="edit" value={text} onChange={(e) => setText(e.target.value)} maxLength={4000}
                          placeholder="For example: thanks, please book a dermatology visit this week." />
                {actionError && <div className="error-box">{actionError}</div>}
                <div className="row wrap">
                  <button type="button" className="btn primary" disabled={busy || !text.trim()}
                          onClick={() => act("reply", { text, resolve: true })}>Reply and resolve</button>
                  <button type="button" className="btn" disabled={busy || !text.trim()}
                          onClick={() => act("reply", { text, resolve: false })}>Reply, keep open</button>
                  <button type="button" className="btn ghost" disabled={busy} onClick={() => act("resolve", {})}>Resolve without reply</button>
                </div>
              </>
            ) : (
              <div className="banner ok"><Check size={16} /> Resolved. The review item is closed.</div>
            )}
          </section>
        </div>
      )}
    </WorkspaceLayout>
  );
}
