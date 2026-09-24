import { Link } from "react-router-dom";
import { useApi } from "../../hooks.js";
import FloorMap from "./FloorMap.jsx";

// A printable sheet: one "You are here" sign per code, with the floor plan, the code and the link it opens.
// The code is printed as text and a URL; scanning a QR image is not offered (no QR library in the app).
export default function SignSheet() {
  const sheet = useApi("/wayfinding/signs");
  const building = useApi("/wayfinding/building");
  const origin = typeof window !== "undefined" ? window.location.origin : "";

  if (sheet.error || building.error) {
    return <main className="page"><div className="error-box" role="alert">{(sheet.error || building.error).message}</div></main>;
  }
  if (!sheet.data || !building.data) {
    return <main className="page"><div className="card stack"><div className="skeleton" /><div className="skeleton" /></div></main>;
  }
  const floors = building.data.floors;
  return (
    <main className="page wf-sign-page">
      <div className="page-head wf-noprint">
        <div>
          <div className="eyebrow">{sheet.data.building.campus} · {sheet.data.building.name}</div>
          <h1 className="page-title">“You are here” signs</h1>
          <div className="page-sub">{sheet.data.signs.length} signs. Print them and post each one at the spot its code names.</div>
        </div>
      </div>
      <div className="row wrap wf-noprint" style={{ gap: 8, marginBottom: 18 }}>
        <button type="button" className="btn primary" onClick={() => window.print()}>Print signs</button>
        <Link to="/wayfinding/admin" className="btn">Back to wayfinding</Link>
      </div>
      <div className="wf-sign-grid">
        {sheet.data.signs.map((s) => {
          const floor = floors.find((f) => f.level === s.floor_level);
          return (
            <article key={s.code} className="wf-sign" aria-label={`Sign ${s.code}`}>
              <div className="wf-sign-top">
                <span className="wf-sign-here">You are here</span>
                <span className="wf-sign-floor">{floor.short_name}</span>
              </div>
              <div className="wf-sign-name">{s.name}</div>
              <div className="small muted">{s.floor_name}{s.area && s.area !== s.name ? ` · ${s.area}` : ""}</div>
              <FloorMap floor={floor} interactive={false} whole start={{ x: s.x, y: s.y, label: "You are here" }}
                        label={`Plan of ${floor.name} with this sign marked`} />
              <div className="wf-sign-code">
                <span className="small muted">In Find your way, pick this sign as your start, or open</span>
                <code>{s.code}</code>
                <span className="wf-sign-url">{origin}{s.path}</span>
              </div>
            </article>
          );
        })}
      </div>
    </main>
  );
}
