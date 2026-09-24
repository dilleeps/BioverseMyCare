import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useApi } from "../../hooks.js";
import { fmtDateTime } from "../../format.js";
import { Shield } from "../../icons.jsx";
import PhotoFlow from "./PhotoFlow.jsx";
import PhotoCard from "./PhotoCard.jsx";
import AuthImage from "./AuthImage.jsx";
import { KINDS } from "./image.js";

function SentPhotos() {
  const { data, error, loading } = useApi("/photo-questions/skin");
  return (
    <section className="stack" aria-labelledby="sent-photos" style={{ marginTop: 24 }}>
      <h2 id="sent-photos" className="card-title">Photos you've sent</h2>
      {loading && <div className="skeleton" />}
      {error && <div className="error-box">{error.message}</div>}
      {data && data.length === 0 && <div className="card empty">You haven't sent any photos to your care team.</div>}
      {data?.map((s) => (
        <article key={s.id} className="card stack sent-photo">
          <div className="row" style={{ alignItems: "flex-start" }}>
            <AuthImage path={`${s.image_url}`} alt="Skin photo you sent" className="photo-thumb" />
            <div style={{ minWidth: 0 }}>
              <div className="small muted">Sent {fmtDateTime(s.created_at)} to {s.practitioner_name}</div>
              <div>{s.note || "No note"}</div>
            </div>
          </div>
          {s.reply ? (
            <div className="bubble assistant sent-reply">
              <div className="small strong">{s.replied_by_name} replied</div>
              {s.reply}
            </div>
          ) : (
            <span className="chip">Waiting for a reply</span>
          )}
        </article>
      ))}
    </section>
  );
}

export default function PhotoAsk() {
  const [params] = useSearchParams();
  const preset = KINDS.some((k) => k.id === params.get("kind")) ? params.get("kind") : null;
  const [entries, setEntries] = useState([]);
  const [flowKey, setFlowKey] = useState(0);

  return (
    <main className="column">
      <div className="page-head">
        <div>
          <h1 className="page-title">Ask with a photo</h1>
          <div className="page-sub">A medicine box, a skin concern, or a paper lab report</div>
        </div>
      </div>
      <div className="stack">
        {entries.map((e) => <PhotoCard key={e.id} entry={e} />)}
        <section className="card">
          <PhotoFlow key={flowKey} initialKind={entries.length ? null : preset}
                     onSent={(entry) => { setEntries((xs) => [...xs, entry]); setFlowKey((k) => k + 1); }} />
        </section>
        <p className="tiny muted row" style={{ gap: 6 }}>
          <Shield size={13} /> Photos are checked and then discarded, unless you choose to send a skin photo to your care team.
        </p>
      </div>
      {params.get("view") === "sent" ? <SentPhotos /> : (
        <p className="small" style={{ marginTop: 16 }}><Link to="/ask/photo?view=sent">Photos you've sent to your care team</Link></p>
      )}
    </main>
  );
}
