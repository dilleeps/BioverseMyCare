import { useMemo, useState } from "react";
import { qrMatrix, qrSvgPath } from "./qr.js";
import { fmtMoney } from "./util.jsx";

export function QrCode({ text, size = 132, label }) {
  const path = useMemo(() => {
    try {
      return qrSvgPath(qrMatrix(text));
    } catch {
      return null;
    }
  }, [text]);
  if (!path) return <p className="small muted">This code is too long to draw. Use the text below instead.</p>;
  return (
    <svg className="ins-qr" width={size} height={size} viewBox={`0 0 ${path.size} ${path.size}`} role="img"
         aria-label={label} shapeRendering="crispEdges">
      <rect width={path.size} height={path.size} fill="#fff" />
      <path d={path.d} fill="#111" />
    </svg>
  );
}

function Field({ label, value, mono }) {
  return (
    <div className="ins-field">
      <div className="ins-field-label">{label}</div>
      <div className={`ins-field-value${mono ? " mono" : ""}`}>{value || "—"}</div>
    </div>
  );
}

// Front and back of the digital insurance card. The back carries the signed QR code.
export default function InsuranceCard({ card, token }) {
  const [side, setSide] = useState("front");
  const copays = (card.copays || []).slice(0, 4);
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="ins-side-toggle" role="group" aria-label="Card side">
        {["front", "back"].map((s) => (
          <button key={s} type="button" className={`btn sm ${side === s ? "dark" : ""}`} aria-pressed={side === s}
                  onClick={() => setSide(s)}>
            {s === "front" ? "Front" : "Back and QR code"}
          </button>
        ))}
      </div>
      <div className="ins-card-pair" data-side={side}>
        <section className="ins-card front" aria-label="Insurance card, front">
          <div className="row between" style={{ alignItems: "flex-start" }}>
            <div>
              <div className="ins-card-payer">{card.payer}</div>
              <div className="ins-card-plan">{card.plan}</div>
            </div>
            <span className={`ins-card-status ${card.active ? "" : "off"}`}>{card.active ? "Active" : "Not active"}</span>
          </div>
          <div className="ins-card-grid">
            <Field label="Member" value={card.member_name} />
            <Field label="Member ID" value={card.member_id} mono />
            <Field label="Group" value={card.group_number} mono />
            <Field label="Payer ID" value={card.payer_id} mono />
          </div>
          {copays.length > 0 && (
            <div className="ins-card-copays">
              {copays.map((c) => (
                <div key={c.label}><span>{c.label.replace(" visits", "")}</span><strong>{fmtMoney(c.amount_cents)}</strong></div>
              ))}
            </div>
          )}
        </section>
        <section className="ins-card back" aria-label="Insurance card, back">
          <div className="ins-card-back">
            <div className="stack" style={{ gap: 8, minWidth: 0 }}>
              <div className="ins-card-grid rx">
                <Field label="RxBIN" value={card.rx_bin} mono />
                <Field label="RxPCN" value={card.rx_pcn} mono />
                <Field label="RxGroup" value={card.rx_group} mono />
              </div>
              <Field label="Member services" value={card.member_phone} />
              <Field label="Providers" value={card.provider_phone} />
              {card.claims_address && <Field label="Send claims to" value={card.claims_address} />}
            </div>
            {token && (
              <div className="ins-qr-wrap">
                <QrCode text={token} size={120} label="Signed code for the front desk to scan" />
                <span className="tiny">Show at check-in</span>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
