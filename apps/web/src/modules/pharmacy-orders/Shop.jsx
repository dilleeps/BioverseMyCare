import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { PatientPage } from "../../layouts.jsx";
import { Check, Close, Plus } from "../../icons.jsx";
import { Findings, StatusChip, fmtWhen, money } from "./shared.jsx";
import { Bag, Truck } from "./icons.jsx";

function Badges({ p }) {
  return (
    <span className="row wrap" style={{ gap: 4 }}>
      {p.controlled_schedule && <span className="chip warn">Pickup only</span>}
      {p.pharmacist_only && !p.controlled_schedule && <span className="chip">Pharmacist check</span>}
      {p.requires_refrigeration && <span className="chip">Keep cold</span>}
      {p.min_age >= 18 && <span className="chip">18+</span>}
    </span>
  );
}

// --- Health products ---------------------------------------------------------------------------------------------

function ProductCard({ p, onAdd, busy, result }) {
  return (
    <li className="card po-product">
      <div className="stack" style={{ gap: 6 }}>
        <h3 className="po-product-name">{p.name}</h3>
        <span className="strong">{money(p.price_cents)}</span>
        <span className="small muted">{p.generic_name} · {p.pack_size}</span>
        <Badges p={p} />
        <details className="po-details">
          <summary className="small strong">Ingredients and warnings</summary>
          <div className="stack" style={{ gap: 6, marginTop: 6 }}>
            {p.ingredient_text && <p className="small"><strong>Active ingredients.</strong> {p.ingredient_text}</p>}
            {p.warnings.length > 0 && <ul className="small po-warnings">{p.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
            <p className="tiny muted">Up to {p.max_qty_per_order} per order{p.min_age ? ` · ages ${p.min_age} and over` : ""}.</p>
          </div>
        </details>
      </div>
      {result?.error && <div className="error-box small">{result.error}</div>}
      {result?.findings && <Findings findings={result.findings} compact />}
      <button className="btn" onClick={() => onAdd(p)} disabled={busy} aria-label={`Add ${p.name} to cart`}>
        {result?.added ? <><Check size={16} /> Added</> : <><Plus size={16} /> Add to cart</>}
      </button>
    </li>
  );
}

function Catalog({ onChanged }) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const params = new URLSearchParams();
  if (query) params.set("q", query);
  if (category) params.set("category", category);
  const { data, error, loading } = useApi(`/pharmacy-orders/catalog${params.toString() ? `?${params}` : ""}`);
  const [busy, setBusy] = useState(null);
  const [results, setResults] = useState({});

  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  async function addProduct(p) {
    setBusy(p.id);
    try {
      const r = await api("/pharmacy-orders/cart/items", { method: "POST", body: { product_id: p.id, quantity: 1 } });
      setResults((s) => ({ ...s, [p.id]: { added: true, findings: r.findings } }));
      onChanged(r.cart);
    } catch (e) {
      setResults((s) => ({ ...s, [p.id]: { error: e.message } }));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack">
      <div className="po-search">
        <label htmlFor="po-q" className="sr-only">Search health products</label>
        <input id="po-q" type="search" placeholder="Search by name or ingredient, like loratadine" value={q}
               onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="row wrap po-cats" role="group" aria-label="Categories">
        <button className={`btn sm ${category === "" ? "dark" : ""}`} aria-pressed={category === ""} onClick={() => setCategory("")}>All</button>
        {data?.categories.map((c) => (
          <button key={c.code} className={`btn sm ${category === c.code ? "dark" : ""}`} aria-pressed={category === c.code}
                  onClick={() => setCategory(c.code)}>{c.label}</button>
        ))}
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {data && data.products.length === 0 && <div className="card empty">Nothing matches. Try another word or category.</div>}
      <ul className="po-grid">
        {data?.products.map((p) => (
          <ProductCard key={p.id} p={p} onAdd={addProduct} busy={busy === p.id} result={results[p.id]} />
        ))}
      </ul>
      {data && <p className="tiny muted">{data.notice}</p>}
    </div>
  );
}

// --- Prescriptions -----------------------------------------------------------------------------------------------

function RxList({ highlight, onChanged }) {
  const { data, error, loading, reload } = useApi("/pharmacy-orders/rx-items");
  const [busy, setBusy] = useState(null);
  const [results, setResults] = useState({});

  async function addRx(item) {
    setBusy(item.medication_request_id);
    try {
      const r = await api("/pharmacy-orders/cart/items", { method: "POST", body: { medication_request_id: item.medication_request_id } });
      setResults((s) => ({ ...s, [item.medication_request_id]: { added: true, findings: r.findings } }));
      onChanged(r.cart);
    } catch (e) {
      setResults((s) => ({ ...s, [item.medication_request_id]: { error: e.message } }));
      reload();
    } finally {
      setBusy(null);
    }
  }

  if (error) return <div className="error-box">{error.message}</div>;
  if (loading && !data) return <div className="card"><div className="skeleton" /></div>;
  return (
    <div className="stack">
      {data.items.length === 0 && (
        <div className="card empty">You have no active prescriptions. Prescriptions from your care team appear here.</div>
      )}
      {data.items.map((rx) => {
        const res = results[rx.medication_request_id];
        return (
          <article key={rx.medication_request_id}
                   className={`card stack po-rx ${highlight === rx.medication_request_id ? "highlight" : ""}`}
                   aria-labelledby={`porx-${rx.medication_request_id}`}>
            <div className="row between wrap" style={{ alignItems: "flex-start" }}>
              <div>
                <h3 id={`porx-${rx.medication_request_id}`} className="po-product-name">{rx.name}</h3>
                <p className="small">{rx.sig}</p>
                <p className="tiny muted">Prescribed by {rx.prescriber_name} · {rx.quantity} tablets per fill</p>
              </div>
              <div className="po-price">
                <span className="strong">{money(rx.estimate.patient_cents)}</span>
                <span className="tiny muted">estimate</span>
              </div>
            </div>
            <p className="small">{rx.how}</p>
            <span className="tiny muted">{rx.estimate.basis}.</span>
            {rx.controlled_schedule && <span className="chip warn">Controlled medicine: pickup only, with ID</span>}
            {res?.error && <div className="error-box small">{res.error}</div>}
            {res?.findings && <Findings findings={res.findings} compact />}
            {rx.orderable ? (
              <button className="btn primary" disabled={busy === rx.medication_request_id || res?.added}
                      onClick={() => addRx(rx)}>
                {res?.added ? <><Check size={16} /> In your cart</> : <><Plus size={16} /> Add to cart</>}
              </button>
            ) : (
              !res && <span className="chip">Not available to order now</span>
            )}
          </article>
        );
      })}
      {data && <p className="tiny muted">{data.notice} Every prescription is checked by a pharmacist before it's packed.</p>}
    </div>
  );
}

// --- Cart -------------------------------------------------------------------------------------------------------

function Cart({ cart, error, loading, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function change(item, quantity) {
    setBusy(true);
    setErr(null);
    try {
      const r = quantity === 0
        ? await api(`/pharmacy-orders/cart/items/${item.id}`, { method: "DELETE" })
        : await api(`/pharmacy-orders/cart/items/${item.id}`, { method: "PATCH", body: { quantity } });
      onChanged(r);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const items = cart?.items || [];
  const blocked = cart?.checks.findings.some((f) => f.severity === "block") || items.some((i) => !i.available);
  return (
    <section className="card stack po-cart" aria-labelledby="po-cart-title" id="cart">
      <h2 id="po-cart-title" className="card-title row" style={{ gap: 8 }}><Bag size={18} /> Your cart</h2>
      {error && <div className="error-box small">{error.message}</div>}
      {loading && !cart && <div className="skeleton" />}
      {cart && items.length === 0 && <p className="small muted">Your cart is empty. Add a prescription or a health product.</p>}
      {items.length > 0 && (
        <ul className="po-cart-items">
          {items.map((i) => (
            <li key={i.id} className="stack" style={{ gap: 6 }}>
              <div className="row between" style={{ alignItems: "flex-start", gap: 8 }}>
                <span className="stack" style={{ gap: 2, minWidth: 0 }}>
                  <span className="strong small">{i.name}</span>
                  <span className="tiny muted">{i.kind === "rx" ? "Prescription" : i.detail}</span>
                  {i.price_note && <span className="tiny muted">{i.price_note}</span>}
                </span>
                <span className="strong small">{money(i.line_total_cents)}</span>
              </div>
              {!i.available && <div className="banner warn">{i.unavailable_reason}</div>}
              <div className="row between" style={{ gap: 8 }}>
                {i.kind === "otc" ? (
                  <span className="row" style={{ gap: 6 }}>
                    <label htmlFor={`qty-${i.id}`} className="tiny strong">Qty</label>
                    <select id={`qty-${i.id}`} className="po-qty" value={i.quantity} disabled={busy}
                            onChange={(e) => change(i, Number(e.target.value))}>
                      {Array.from({ length: Math.max(i.max_quantity, i.quantity) }, (_, n) => n + 1).map((n) => (
                        <option key={n} value={n}>{n}</option>
                      ))}
                    </select>
                  </span>
                ) : <span className="tiny muted">One fill</span>}
                <button className="btn ghost sm" disabled={busy} onClick={() => change(i, 0)} aria-label={`Remove ${i.name}`}>
                  <Close size={14} /> Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {err && <div className="error-box small">{err}</div>}
      {cart && items.length > 0 && (
        <>
          <Findings findings={cart.checks.findings} />
          <dl className="po-totals">
            <div><dt>Subtotal</dt><dd>{money(cart.subtotal_cents)}</dd></div>
            <div><dt>Delivery</dt><dd>{cart.delivery_fee_cents ? `${money(cart.delivery_fee_cents)} (free over ${money(cart.free_delivery_over_cents)})` : "Free"}</dd></div>
          </dl>
          {blocked ? (
            <p className="small po-alert">Fix the items marked above to continue.</p>
          ) : (
            <Link to="/shop/checkout" className="btn primary block">Go to checkout</Link>
          )}
          <p className="tiny muted">{cart.checks.notice}</p>
        </>
      )}
    </section>
  );
}

function OpenOrders() {
  const { data } = useApi("/pharmacy-orders/orders");
  const open = (data || []).filter((o) => o.is_open);
  if (open.length === 0) return null;
  return (
    <div className="stack" style={{ gap: 8, marginBottom: 16 }}>
      {open.map((o) => (
        <Link key={o.id} to={`/shop/orders/${o.id}`} className="card po-open-order">
          <span className="po-open-icon" aria-hidden="true"><Truck size={20} /></span>
          <span className="stack" style={{ gap: 2, flexGrow: 1, minWidth: 0 }}>
            <span className="strong">Order {o.number}</span>
            <span className="small muted">
              {o.status === "out_for_delivery" && o.eta ? `Arriving around ${fmtWhen(o.eta)}` : o.window_label}
            </span>
          </span>
          <StatusChip status={o.status} label={o.status_label} />
        </Link>
      ))}
    </div>
  );
}

export default function Shop() {
  const [params] = useSearchParams();
  const highlight = params.get("rx");
  const [tab, setTab] = useState(params.get("tab") === "products" ? "products" : "rx");
  const cartApi = useApi("/pharmacy-orders/cart");
  const [cart, setCart] = useState(null);

  useEffect(() => {
    document.title = "Order medicines · Bioverse";
  }, []);
  useEffect(() => {
    if (cartApi.data) setCart(cartApi.data);
  }, [cartApi.data]);

  const count = cart?.items.length || 0;
  return (
    <PatientPage wide>
      <div className="page-head po-head">
        <div style={{ minWidth: 0 }}>
          <h1 className="page-title">Order medicines</h1>
          <p className="page-sub">Home delivery, or pickup at the clinic pharmacy. A pharmacist checks anything that needs it.</p>
        </div>
        <div className="row wrap" style={{ gap: 8 }}>
          <a href="#cart" className="btn po-cart-jump">Cart · {count}</a>
          <Link to="/shop/orders" className="btn">My orders</Link>
        </div>
      </div>
      <div className="banner info" style={{ marginBottom: 16 }}>
        Demo pharmacy: products, payments and deliveries are simulated.
      </div>
      <OpenOrders />
      <div className="po-shop">
        <div className="stack" style={{ minWidth: 0 }}>
          <div className="row wrap po-tabs" role="group" aria-label="What to order">
            <button className={`btn ${tab === "rx" ? "dark" : ""}`} aria-pressed={tab === "rx"} onClick={() => setTab("rx")}>
              Your prescriptions
            </button>
            <button className={`btn ${tab === "products" ? "dark" : ""}`} aria-pressed={tab === "products"} onClick={() => setTab("products")}>
              Health products
            </button>
          </div>
          {tab === "rx" ? <RxList highlight={highlight} onChanged={setCart} /> : <Catalog onChanged={setCart} />}
        </div>
        <Cart cart={cart} error={cartApi.error} loading={cartApi.loading} onChanged={setCart} />
      </div>
    </PatientPage>
  );
}
