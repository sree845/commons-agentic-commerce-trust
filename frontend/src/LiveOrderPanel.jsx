import React, {useState} from "react";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export default function LiveOrderPanel() {
  const [payload, setPayload] = useState(JSON.stringify({
    order_id: "agent-order-1001",
    agent_id: "agent_001",
    merchant_id: "merchant_A",
    amount: "25.00",
    currency: "USD",
    category: "books",
    mandate: {},
    signature: ""
  }, null, 2));
  const [tx, setTx] = useState(null);
  const [paypalOrder, setPaypalOrder] = useState("");
  const [operatorToken, setOperatorToken] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function call(path, body, auth) {
    setBusy(true); setError("");
    try {
      const headers = {"Content-Type":"application/json"};
      if (auth) headers.Authorization = `Bearer ${auth}`;
      const response = await fetch(API + path, {
        method:"POST", headers, body: JSON.stringify(body || {})
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      setResult(data);
      return data;
    } catch (e) {
      setError(e.message);
      return null;
    } finally { setBusy(false); }
  }

  async function create() {
    let order;
    try { order = JSON.parse(payload); }
    catch { setError("Order JSON is invalid."); return; }
    const data = await call("/api/live/orders", order);
    if (data) {
      setTx(data.transaction_id);
      setPaypalOrder(data.paypal_order_id || "");
    }
  }
  async function authorize() {
    if (!tx || !paypalOrder) return;
    await call(`/api/live/orders/${encodeURIComponent(tx)}/authorize`,
      {paypal_order_id:paypalOrder});
  }
  async function evaluate() {
    if (tx) await call(`/api/live/orders/${encodeURIComponent(tx)}/evaluate`);
  }
  async function execute() {
    if (tx) await call(`/api/live/orders/${encodeURIComponent(tx)}/execute`, {}, operatorToken);
  }

  return <section className="panel live-order-panel">
    <h3>Live PayPal Sandbox order pipeline</h3>
    <p className="muted">Submit a real signed mandate. This path verifies authority, reserves the nonce, creates a PayPal Sandbox checkout order, scores the authorized transaction using the active model, and requires a separate operator token for capture or void.</p>
    <label>Signed agent order JSON</label>
    <textarea rows={12} value={payload} onChange={e=>setPayload(e.target.value)} spellCheck="false"/>
    <button className="primary" disabled={busy} onClick={create}>1 · Verify mandate and create checkout</button>
    {tx && <>
      <label>Commons transaction ID</label><input readOnly value={tx}/>
      <label>PayPal order ID</label><input value={paypalOrder} onChange={e=>setPaypalOrder(e.target.value)}/>
      <button onClick={authorize} disabled={busy}>2 · Confirm buyer-approved PayPal order</button>
      <button onClick={evaluate} disabled={busy}>3 · Run trusted feature extraction and live risk inference</button>
      <label>Operator bearer token (never put this in frontend source)</label>
      <input type="password" value={operatorToken} onChange={e=>setOperatorToken(e.target.value)} placeholder="COMMONS_OPERATOR_TOKEN"/>
      <button className="primary" disabled={busy || !operatorToken} onClick={execute}>4 · Execute persisted CAPTURE / HOLD / VOID decision</button>
    </>}
    {error && <div className="notice error">{error}</div>}
    {result && <pre className="live-result">{JSON.stringify(result,null,2)}</pre>}
  </section>;
}
