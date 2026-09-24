import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { useApi } from "../../hooks.js";
import { fmtDateTime } from "../../format.js";
import { Back } from "../../icons.jsx";
import { fmtDay, fmtMoney } from "./money.js";

// Printable receipt for one demo payment. Print styles hide the app chrome (see styles.css).
export default function Receipt() {
  const { paymentId } = useParams();
  const { data, error, loading } = useApi(`/billing/payments/${paymentId}`);

  useEffect(() => {
    document.title = data ? `Receipt ${data.receipt_number} · Bioverse` : "Receipt · Bioverse";
  }, [data]);

  return (
    <main className="column receipt-page">
      <div className="page-head no-print">
        <Link className="icon-btn" to="/billing" aria-label="Back to bills"><Back /></Link>
        <h1 className="page-title" style={{ fontSize: 22 }}>Receipt</h1>
      </div>
      {loading && !data && <div className="card" aria-busy="true"><div className="skeleton" /></div>}
      {error && <div className="error-box">{error.status === 404 ? "We couldn't find that receipt." : error.message}</div>}
      {data && (
        <article className="card receipt stack" aria-labelledby="receipt-title">
          <div className="row between wrap" style={{ alignItems: "flex-start" }}>
            <div>
              <div className="eyebrow">{data.organization_name}</div>
              <h2 id="receipt-title" className="receipt-title">Payment receipt</h2>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="tiny muted">Receipt number</div>
              <div className="strong">{data.receipt_number}</div>
            </div>
          </div>
          <dl className="kv">
            <div><dt>Patient</dt><dd>{data.patient_name}</dd></div>
            <div><dt>Paid on</dt><dd>{fmtDateTime(data.created_at)}</dd></div>
            <div><dt>For</dt><dd>{data.service_name}, {fmtDay(data.service_date)}</dd></div>
            <div><dt>Method</dt><dd>Demo payment (no money moved)</dd></div>
          </dl>
          <table className="money-table">
            <caption className="sr-only">Payment summary</caption>
            <tbody>
              <tr><th scope="row">Bill amount</th><td>{fmtMoney(data.statement_amount_cents)}</td></tr>
              <tr className="total"><th scope="row">Amount paid</th><td>{fmtMoney(data.amount_cents)}</td></tr>
              <tr><th scope="row">Balance after this payment</th><td>{fmtMoney(data.balance_after_cents)}</td></tr>
            </tbody>
          </table>
          <p className="tiny muted">{data.notice}</p>
          <div className="row wrap no-print" style={{ gap: 8 }}>
            <button className="btn primary" onClick={() => window.print()}>Print receipt</button>
            <Link className="btn" to="/billing">Back to bills</Link>
          </div>
        </article>
      )}
    </main>
  );
}
