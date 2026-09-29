import html
import json
import os
import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from .pricing import PriceList
from .schemas import DiscountRequest, QuoteItemRequest, QuoteRevisionRequest
from .store import QuoteStore

router = APIRouter(prefix="/internal")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "6054035Win").strip()
COOKIE_NAME = "dozen_admin_session"


def get_auth_token() -> str:
    return hashlib.sha256(f"dozen_admin_{ADMIN_PASSWORD}".encode("utf-8")).hexdigest()


def is_authenticated(request: Request) -> bool:
    session = request.cookies.get(COOKIE_NAME)
    return bool(session and session == get_auth_token())


def require_auth(request: Request):
    if not is_authenticated(request):
        next_url = request.url.path
        if request.url.query:
            next_url += f"?{request.url.query}"
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/internal/login?next={next_url}"},
        )


def money_label(v) -> str:
    try:
        val = float(v)
        return f"€ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"€ {v}"


DOZEN_CSS = """
:root {
  --bg: #07070a;
  --card-bg: #0c0d10;
  --card-border: rgba(255, 255, 255, 0.08);
  --lime: #ceff1a;
  --cyan: #00e5ff;
  --text-main: #f4f4f5;
  --text-muted: #a1a1aa;
  --text-dim: #71717a;
  --input-bg: #14151a;
  --input-border: rgba(255, 255, 255, 0.12);
  --font-head: 'Sora', sans-serif;
  --font-body: 'Manrope', sans-serif;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text-main);
  font-family: var(--font-body);
  line-height: 1.5;
  min-height: 100vh;
}
h1, h2, h3, h4 {
  font-family: var(--font-head);
  font-weight: 700;
  color: var(--text-main);
  letter-spacing: -0.02em;
}
a { color: var(--cyan); text-decoration: none; transition: 0.2s; }
a:hover { color: var(--lime); }
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 32px;
  background: rgba(12, 13, 16, 0.85);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--card-border);
  position: sticky;
  top: 0;
  z-index: 100;
}
.brand-badge {
  display: flex;
  align-items: center;
  gap: 12px;
  font-family: var(--font-head);
  font-weight: 800;
  font-size: 19px;
  color: #fff;
}
.brand-badge span { color: var(--lime); }
.nav-links { display: flex; align-items: center; gap: 16px; }
.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  border-radius: 8px;
  font-family: var(--font-head);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.2s ease;
  text-decoration: none;
}
.btn-primary { background: var(--lime); color: #07070a; }
.btn-primary:hover { background: #d8ff47; transform: translateY(-1px); box-shadow: 0 4px 16px rgba(206, 255, 26, 0.25); }
.btn-cyan { background: var(--cyan); color: #07070a; }
.btn-cyan:hover { background: #33eaff; transform: translateY(-1px); }
.btn-secondary { background: rgba(255, 255, 255, 0.06); color: var(--text-main); border: 1px solid var(--card-border); }
.btn-secondary:hover { background: rgba(255, 255, 255, 0.12); color: #fff; }
.btn-danger { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.container { max-width: 1240px; margin: 0 auto; padding: 32px 24px; }
.grid-kpi { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 32px; }
.kpi-card { background: var(--card-bg); border: 1px solid var(--card-border); padding: 20px; border-radius: 12px; position: relative; overflow: hidden; }
.kpi-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: linear-gradient(90deg, transparent, var(--lime), transparent); }
.kpi-title { font-size: 13px; color: var(--text-dim); text-transform: uppercase; font-weight: 700; letter-spacing: 0.05em; }
.kpi-val { font-size: 32px; font-weight: 800; font-family: var(--font-head); margin-top: 6px; color: #fff; }
.card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 24px; margin-bottom: 24px; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 14px; border-bottom: 1px solid var(--card-border); }
.filter-tabs { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }
.tab { padding: 8px 16px; border-radius: 6px; background: var(--input-bg); border: 1px solid var(--input-border); color: var(--text-muted); font-size: 13px; text-decoration: none; }
.tab.active, .tab:hover { background: rgba(206, 255, 26, 0.1); color: var(--lime); border-color: var(--lime); }
table { width: 100%; border-collapse: collapse; text-align: left; }
th { padding: 12px 16px; font-size: 12px; color: var(--text-dim); text-transform: uppercase; font-weight: 700; border-bottom: 1px solid var(--card-border); }
td { padding: 16px; font-size: 14px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); }
tr:hover td { background: rgba(255, 255, 255, 0.02); }
.pill { display: inline-block; padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; text-transform: uppercase; }
.pill-DRAFT { background: rgba(234, 179, 8, 0.15); color: #facc15; border: 1px solid rgba(234, 179, 8, 0.3); }
.pill-SENT { background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }
.pill-INTERESTED { background: rgba(0, 229, 255, 0.15); color: #00e5ff; border: 1px solid rgba(0, 229, 255, 0.3); }
.pill-APPROVED { background: rgba(206, 255, 26, 0.15); color: #ceff1a; border: 1px solid rgba(206, 255, 26, 0.3); }
.pill-EXPIRED, .pill-CANCELLED { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 16px; }
label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; font-weight: 600; color: var(--text-muted); }
input, select, textarea { background: var(--input-bg); border: 1px solid var(--input-border); color: var(--text-main); padding: 10px 14px; border-radius: 8px; font-family: inherit; font-size: 14px; }
input:focus, select:focus, textarea:focus { outline: none; border-color: var(--lime); }
.lead-box { background: rgba(0, 229, 255, 0.04); border: 1px solid rgba(0, 229, 255, 0.2); border-radius: 10px; padding: 16px 20px; margin-bottom: 24px; }
.lead-box h4 { color: var(--cyan); margin-bottom: 8px; font-size: 14px; text-transform: uppercase; }
.lead-tags { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.tag-badge { background: rgba(206, 255, 26, 0.1); color: var(--lime); border: 1px solid rgba(206, 255, 26, 0.25); padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; }
.totals-summary { background: #101217; border: 1px solid var(--card-border); border-radius: 12px; padding: 20px; margin-top: 24px; }
.totals-row { display: flex; justify-content: space-between; padding: 8px 0; color: var(--text-muted); font-size: 14px; }
.totals-row.final { border-top: 1px solid rgba(255, 255, 255, 0.1); margin-top: 8px; padding-top: 12px; font-size: 22px; font-weight: 800; color: #fff; }
.totals-row.final span:last-child { color: var(--lime); font-family: var(--font-head); }
.actions-bar { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--card-border); }
"""


def base_layout(title: str, content: str, user_authenticated: bool = True) -> str:
    logout_btn = """
    <div class="nav-links">
      <a href="/internal" class="btn btn-secondary">Dashboard</a>
      <a href="/internal/new" class="btn btn-secondary">+ Nuovo Preventivo</a>
      <a href="/internal/logout" class="btn btn-danger" style="padding:6px 12px; font-size:12px;">Esci</a>
    </div>
    """ if user_authenticated else ""

    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} · DozenDev Admin</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=Sora:wght@600;700;800&display=swap" rel="stylesheet">
  <style>{DOZEN_CSS}</style>
</head>
<body>
  <header class="topbar">
    <div class="brand-badge">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none"><rect width="24" height="24" rx="6" fill="#ceff1a"/><path d="M7 17L17 7M7 7H17V17" stroke="#07070a" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      DOZEN<span>DEV</span> <small style="color:var(--text-dim);font-weight:600;font-size:12px;letter-spacing:0.05em;margin-left:4px;">QUOTE ENGINE</small>
    </div>
    {logout_btn}
  </header>
  <main class="container">
    {content}
  </main>
</body>
</html>"""


@router.get("/login", response_class=HTMLResponse)
def login_page(next: str = "/internal", error: Optional[str] = None):
    err_html = f"<div style='background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);color:#f87171;padding:12px;border-radius:8px;margin-bottom:16px;font-size:14px;'>{html.escape(error)}</div>" if error else ""
    content = f"""
    <div style="max-width: 420px; margin: 80px auto; background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 16px; padding: 36px; box-shadow: 0 20px 40px rgba(0,0,0,0.5);">
      <div style="text-align: center; margin-bottom: 24px;">
        <div style="display:inline-flex; padding:12px; border-radius:12px; background:rgba(206,255,26,0.1); border:1px solid rgba(206,255,26,0.2); margin-bottom:16px;">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none"><rect x="3" y="11" width="18" height="11" rx="2" stroke="#ceff1a" stroke-width="2"/><path d="M7 11V7a5 5 0 0110 0v4" stroke="#ceff1a" stroke-width="2"/></svg>
        </div>
        <h2>Accesso Riservato</h2>
        <p style="color:var(--text-muted); font-size:14px; margin-top:6px;">Inserisci la password di amministrazione DozenDev</p>
      </div>
      {err_html}
      <form method="POST" action="/internal/login">
        <input type="hidden" name="next" value="{html.escape(next)}">
        <label style="margin-bottom: 20px;">
          Password Admin
          <input type="password" name="password" required autofocus placeholder="••••••••" style="padding:12px 14px;">
        </label>
        <button type="submit" class="btn btn-primary" style="width: 100%; justify-content: center; padding: 12px;">Accedi all'Editor</button>
      </form>
    </div>
    """
    return HTMLResponse(base_layout("Login Amministrativo", content, user_authenticated=False))


@router.post("/login")
def login_post(password: str = Form(...), next: str = Form("/internal")):
    if password == ADMIN_PASSWORD:
        response = RedirectResponse(url=next or "/internal", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            key=COOKIE_NAME,
            value=get_auth_token(),
            max_age=86400 * 30,
            httponly=True,
            samesite="lax",
        )
        return response
    return RedirectResponse(
        url=f"/internal/login?error=Password+errata&next={next}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/internal/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, status_filter: Optional[str] = None):
    require_auth(request)
    from .main import store

    quotes = store.list_quotes(limit=300)

    total_count = len(quotes)
    draft_count = sum(1 for q in quotes if q.get("status") == "DRAFT")
    sent_count = sum(1 for q in quotes if q.get("status") == "SENT")
    interested_count = sum(1 for q in quotes if q.get("status") == "INTERESTED")
    approved_count = sum(1 for q in quotes if q.get("status") == "APPROVED")

    if status_filter:
        filtered = [q for q in quotes if q.get("status") == status_filter]
    else:
        filtered = quotes

    rows = []
    for q in filtered:
        status_code = q.get("status", "DRAFT")
        customer = q.get("customer") or {}
        totals = q.get("totals") or {}
        created_at = (q.get("created_at") or "")[:10]
        q_id = q.get("quote_id")

        rows.append(f"""
        <tr>
          <td>
            <a href="/internal/quote/{q_id}" style="font-weight:700; font-family:var(--font-head); color:#fff;">
              {html.escape(q.get("quote_number", "DZN"))}
            </a>
            <div style="font-size:11px; color:var(--text-dim);">v{q.get("version", 1)}</div>
          </td>
          <td>
            <div style="font-weight:600; color:#fff;">{html.escape(customer.get("business_name") or "-")}</div>
            <div style="font-size:12px; color:var(--text-dim);">{html.escape(customer.get("email") or "-")}</div>
          </td>
          <td>
            <div>{html.escape(q.get("project_name") or "Sito Web")}</div>
            <div style="font-size:12px; color:var(--text-dim);">{html.escape(q.get("delivery_weeks") or "-")}</div>
          </td>
          <td style="font-weight:700; color:var(--lime); font-family:var(--font-head);">
            {money_label(totals.get("net_total", 0))} <small style="font-size:10px; color:var(--text-dim);">+ IVA</small>
          </td>
          <td>
            <span class="pill pill-{status_code}">{status_code}</span>
          </td>
          <td style="color:var(--text-dim); font-size:12px;">{created_at}</td>
          <td>
            <div style="display:flex; gap:6px;">
              <a href="/internal/quote/{q_id}" class="btn btn-primary" style="padding:6px 12px; font-size:12px;">✏️ Elabora</a>
              <a href="/api/v1/quotes/{q_id}/pdf" target="_blank" class="btn btn-secondary" style="padding:6px 10px; font-size:12px;">📄 PDF</a>
            </div>
          </td>
        </tr>
        """)

    table_rows = "".join(rows) if rows else "<tr><td colspan='7' style='text-align:center; padding:32px; color:var(--text-dim);'>Nessun preventivo trovato in questa categoria.</td></tr>"

    content = f"""
    <div class="card-header" style="border:none; padding:0; margin-bottom:28px;">
      <div>
        <h1>Dashboard Preventivi</h1>
        <p style="color:var(--text-muted); font-size:14px; margin-top:4px;">Gestisci, modifica e approva le proposte prima dell'invio ai clienti.</p>
      </div>
      <a href="/internal/new" class="btn btn-primary">+ Crea Preventivo</a>
    </div>

    <div class="grid-kpi">
      <div class="kpi-card">
        <div class="kpi-title">Totale Preventivi</div>
        <div class="kpi-val">{total_count}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title" style="color:#facc15;">⏳ Da Elaborare (Bozze)</div>
        <div class="kpi-val" style="color:#facc15;">{draft_count}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title" style="color:#60a5fa;">✉️ Inviati al Cliente</div>
        <div class="kpi-val" style="color:#60a5fa;">{sent_count}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title" style="color:var(--cyan);">📞 Interesse / Call</div>
        <div class="kpi-val" style="color:var(--cyan);">{interested_count}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title" style="color:var(--lime);">🤝 Approvati</div>
        <div class="kpi-val" style="color:var(--lime);">{approved_count}</div>
      </div>
    </div>

    <div class="card">
      <div class="filter-tabs">
        <a href="/internal" class="tab {'active' if not status_filter else ''}">Tutti ({total_count})</a>
        <a href="/internal?status_filter=DRAFT" class="tab {'active' if status_filter == 'DRAFT' else ''}">Bozze da Confermare ({draft_count})</a>
        <a href="/internal?status_filter=SENT" class="tab {'active' if status_filter == 'SENT' else ''}">Inviati ({sent_count})</a>
        <a href="/internal?status_filter=INTERESTED" class="tab {'active' if status_filter == 'INTERESTED' else ''}">Interessati / Call ({interested_count})</a>
        <a href="/internal?status_filter=APPROVED" class="tab {'active' if status_filter == 'APPROVED' else ''}">Approvati ({approved_count})</a>
      </div>

      <div style="overflow-x:auto;">
        <table>
          <thead>
            <tr>
              <th>Numero</th>
              <th>Cliente / Azienda</th>
              <th>Progetto</th>
              <th>Importo Netto</th>
              <th>Stato</th>
              <th>Data</th>
              <th>Azioni</th>
            </tr>
          </thead>
          <tbody>
            {table_rows}
          </tbody>
        </table>
      </div>
    </div>
    """
    return HTMLResponse(base_layout("Dashboard Preventivi", content))


@router.get("/quote/{quote_id}", response_class=HTMLResponse)
def quote_editor(quote_id: str, request: Request):
    require_auth(request)
    from .main import load_pricelist, public_base, store

    q = store.get(quote_id)
    if not q:
        raise HTTPException(status_code=404, detail="Preventivo non trovato")

    customer = q.get("customer") or {}
    source_data = q.get("source_data") or {}
    discount = q.get("discount") or {}
    status_code = q.get("status", "DRAFT")
    events = store.events(quote_id)
    public_token = store.rotate_public_token(quote_id) if status_code != "APPROVED" else ""
    public_url = f"{public_base()}/{public_token}" if public_token else ""

    pricelist = load_pricelist()

    options_html = []
    for code, s in pricelist.services.items():
        price_txt = money_label(s.get("unit_price", 0))
        options_html.append(
            f"<option value='{html.escape(code)}' data-price='{s.get('unit_price', 0)}' data-name='{html.escape(s.get('name', ''))}'>{html.escape(s.get('name', ''))} ({price_txt})</option>"
        )
    pricelist_options = "".join(options_html)

    lead_notes = source_data.get("notes") or q.get("notes") or "Nessuna nota aggiuntiva specificata dal cliente."
    needs_automation = source_data.get("needsAutomation") or []
    automation_badges = "".join(
        f"<span class='tag-badge'>⚡ {html.escape(str(a))}</span>" for a in needs_automation
    ) if needs_automation else "<span style='color:var(--text-dim);font-size:13px;'>Nessuna automazione specifica selezionata</span>"

    items_json = json.dumps(q.get("items", []), ensure_ascii=False)
    discount_json = json.dumps(discount, ensure_ascii=False)

    events_html = "".join(
        f"<li style='margin-bottom:6px; font-size:12px; color:var(--text-dim);'><span style='color:#fff;'>{html.escape(e.get('created_at', '')[:19])}</span> — <strong style='color:var(--cyan);'>{html.escape(e.get('event_type', ''))}</strong> ({html.escape(e.get('actor') or 'system')})</li>"
        for e in events[-8:]
    )

    content = f"""
    <div style="margin-bottom: 20px;">
      <a href="/internal" style="display:inline-flex; align-items:center; gap:6px; font-size:13px; color:var(--text-dim); margin-bottom:12px;">
        ← Torna alla Dashboard
      </a>
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;">
        <div style="display:flex; align-items:center; gap:12px;">
          <h1>{html.escape(q.get("quote_number", "DZN"))}</h1>
          <span class="pill pill-{status_code}">{status_code}</span>
          <span style="background:rgba(255,255,255,0.06); padding:4px 10px; border-radius:6px; font-size:12px; color:var(--text-muted);">Versione {q.get("version", 1)}</span>
        </div>
        <div style="display:flex; gap:10px;">
          <a href="/api/v1/quotes/{quote_id}/pdf" target="_blank" class="btn btn-secondary">📄 Anteprima PDF</a>
          <button type="button" onclick="sendToCustomer()" class="btn btn-primary" id="btn-send">
            🚀 Conferma ed Invia al Cliente
          </button>
        </div>
      </div>
    </div>

    <!-- Lead Info Box -->
    <div class="lead-box">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px;">
        <div>
          <h4>Dati Richiesta Lead Web</h4>
          <div style="font-size:16px; font-weight:700; color:#fff;">
            {html.escape(customer.get("contact_name") or customer.get("business_name") or "Cliente")} — {html.escape(customer.get("business_name") or "-")}
          </div>
          <div style="font-size:13px; color:var(--text-muted); margin-top:4px;">
            📧 {html.escape(customer.get("email") or "-")} | 📞 {html.escape(customer.get("phone") or source_data.get("phone") or "Non indicato")}
          </div>
        </div>
        <div>
          <span style="font-size:11px; text-transform:uppercase; color:var(--text-dim); font-weight:700;">Pacchetto Richiesto</span>
          <div style="font-weight:700; color:var(--lime);">{html.escape(source_data.get("webTier") or q.get("project_name") or "Web")}</div>
        </div>
      </div>
      <div style="margin-top:14px; padding-top:12px; border-top:1px solid rgba(0,229,255,0.15);">
        <div style="font-size:12px; font-weight:700; color:var(--text-dim); text-transform:uppercase; margin-bottom:6px;">Automazioni richieste:</div>
        <div class="lead-tags">{automation_badges}</div>
      </div>
      <div style="margin-top:12px;">
        <div style="font-size:12px; font-weight:700; color:var(--text-dim); text-transform:uppercase; margin-bottom:4px;">Note e richieste cliente:</div>
        <div style="font-size:13px; color:var(--text-main); background:rgba(0,0,0,0.25); padding:10px 14px; border-radius:6px; font-style:italic;">
          "{html.escape(lead_notes)}"
        </div>
      </div>
    </div>

    <!-- Interactive Editor Form -->
    <div class="card">
      <div class="card-header">
        <div>
          <h3>Editor Voci & Composizione Preventivo</h3>
          <p style="font-size:13px; color:var(--text-muted); margin-top:2px;">Aggiungi voci, modifica quantità o applica sconti prima di inviare.</p>
        </div>
        <button type="button" onclick="saveRevision()" class="btn btn-cyan" id="btn-save">
          💾 Salva Nuova Revisione
        </button>
      </div>

      <table id="items-table" style="margin-bottom:20px;">
        <thead>
          <tr>
            <th>Voce</th>
            <th style="width:100px;">Q.tà</th>
            <th style="width:140px;">Prezzo Unitario</th>
            <th style="width:140px;">Totale</th>
            <th style="width:60px;"></th>
          </tr>
        </thead>
        <tbody id="items-body"></tbody>
      </table>

      <div style="background:var(--input-bg); border:1px solid var(--input-border); border-radius:10px; padding:16px; margin-bottom:24px;">
        <div style="font-size:13px; font-weight:700; color:var(--text-muted); margin-bottom:12px;">+ AGGIUNGI VOCE DAL LISTINO</div>
        <div style="display:flex; gap:12px; flex-wrap:wrap; align-items:flex-end;">
          <label style="flex:2; min-width:240px;">
            Seleziona dal listino
            <select id="sel-pricelist">
              <option value="">-- Scegli una voce del listino --</option>
              {pricelist_options}
            </select>
          </label>
          <button type="button" onclick="addFromPricelist()" class="btn btn-secondary">Aggiungi al Preventivo</button>
        </div>
      </div>

      <div class="form-grid">
        <label>
          Tipo di Sconto
          <select id="disc-type" onchange="recalculate()">
            <option value="">Nessuno sconto</option>
            <option value="percentage">Percentuale (%)</option>
            <option value="fixed">Importo Fisso (€)</option>
          </select>
        </label>
        <label>
          Valore Sconto
          <input type="number" id="disc-val" step="any" min="0" placeholder="es. 10 oppure 250" oninput="recalculate()">
        </label>
        <label>
          Motivo Sconto / Campagna
          <input type="text" id="disc-reason" placeholder="es. Promo lancio Piemonte 30%">
        </label>
      </div>

      <div class="form-grid">
        <label>
          Tempistiche di Consegna
          <input type="text" id="delivery-weeks" value="{html.escape(q.get('delivery_weeks') or '3-4 settimane')}">
        </label>
        <label>
          Motivo della Revisione (Audit interno)
          <input type="text" id="rev-reason" placeholder="es. Aggiunta automazione calendar + sconto">
        </label>
      </div>

      <label style="margin-top:12px;">
        Note Personalizzate Preventivo (Visibili al cliente nel PDF e sul web)
        <textarea id="quote-notes" rows="3">{html.escape(q.get('notes') or '')}</textarea>
      </label>

      <div class="totals-summary">
        <div class="totals-row">
          <span>Subtotale Voci Imponibili:</span>
          <span id="tot-subtotal">€ 0,00</span>
        </div>
        <div class="totals-row" id="row-discount" style="display:none; color:#f87171;">
          <span>Sconto applicato:</span>
          <span id="tot-discount">-€ 0,00</span>
        </div>
        <div class="totals-row">
          <span>Imponibile Netto:</span>
          <span id="tot-net">€ 0,00</span>
        </div>
        <div class="totals-row">
          <span>IVA (22%):</span>
          <span id="tot-vat">€ 0,00</span>
        </div>
        <div class="totals-row final">
          <span>Totale Preventivo (Lordo):</span>
          <span id="tot-gross">€ 0,00</span>
        </div>
      </div>

      <div class="actions-bar">
        <button type="button" onclick="saveRevision()" class="btn btn-cyan" style="padding:12px 24px;">
          💾 Salva Nuova Revisione
        </button>
        <a href="/api/v1/quotes/{quote_id}/pdf" target="_blank" class="btn btn-secondary" style="padding:12px 20px;">
          📄 Visualizza PDF Aggiornato
        </a>
        <button type="button" onclick="sendToCustomer()" class="btn btn-primary" style="padding:12px 24px; margin-left:auto;">
          🚀 Conferma ed Invia Proposta al Cliente
        </button>
      </div>
      <div id="status-msg" style="margin-top:14px; font-size:14px; display:none; padding:12px; border-radius:8px;"></div>
    </div>

    <div class="card">
      <h3 style="font-size:16px; margin-bottom:14px;">Cronologia Eventi & Audit Trail</h3>
      <ul style="list-style:none; padding-left:0;">
        {events_html}
      </ul>
    </div>

    <script>
      let currentItems = {items_json};
      let initialDiscount = {discount_json};

      if (initialDiscount) {{
        document.querySelector('#disc-type').value = initialDiscount.discount_type || '';
        document.querySelector('#disc-val').value = initialDiscount.value || '';
        document.querySelector('#disc-reason').value = initialDiscount.reason || '';
      }}

      function formatMoney(num) {{
        return '€ ' + Number(num).toLocaleString('it-IT', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
      }}

      function renderItems() {{
        const tbody = document.querySelector('#items-body');
        if (!currentItems.length) {{
          tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-dim);padding:24px;">Nessuna voce presente. Aggiungine una dal menu in basso.</td></tr>';
          recalculate();
          return;
        }}

        tbody.innerHTML = currentItems.map((item, idx) => `
          <tr>
            <td>
              <div style="font-weight:700; color:#fff;">${{item.name || item.code}}</div>
              <div style="font-size:12px; color:var(--text-dim);">${{item.description || ''}}</div>
            </td>
            <td>
              <input type="number" min="1" value="${{item.quantity || 1}}" style="width:70px; padding:6px 8px;" onchange="updateQty(${{idx}}, this.value)">
            </td>
            <td style="color:var(--text-muted);">
              ${{formatMoney(item.unit_price || 0)}}
            </td>
            <td style="font-weight:700; color:var(--lime);">
              ${{formatMoney((item.quantity || 1) * (item.unit_price || 0))}}
            </td>
            <td style="text-align:right;">
              <button type="button" onclick="removeItem(${{idx}})" style="background:none; border:none; color:#f87171; font-size:18px; cursor:pointer;" title="Rimuovi">✕</button>
            </td>
          </tr>
        `).join('');

        recalculate();
      }}

      function updateQty(idx, val) {{
        currentItems[idx].quantity = Math.max(1, parseInt(val) || 1);
        renderItems();
      }}

      function removeItem(idx) {{
        if (confirm('Vuoi rimuovere questa voce dal preventivo?')) {{
          currentItems.splice(idx, 1);
          renderItems();
        }}
      }}

      function addFromPricelist() {{
        const sel = document.querySelector('#sel-pricelist');
        const code = sel.value;
        if (!code) return;
        const opt = sel.options[sel.selectedIndex];
        const name = opt.getAttribute('data-name');
        const price = parseFloat(opt.getAttribute('data-price')) || 0;

        currentItems.push({{
          code: code,
          name: name,
          description: '',
          quantity: 1,
          unit_price: price,
          total: price
        }});
        sel.value = '';
        renderItems();
      }}

      function recalculate() {{
        let subtotal = 0;
        currentItems.forEach(i => {{
          subtotal += (i.quantity || 1) * (i.unit_price || 0);
        }});

        const discType = document.querySelector('#disc-type').value;
        const discVal = parseFloat(document.querySelector('#disc-val').value) || 0;
        let discountAmount = 0;

        if (discType === 'percentage' && discVal > 0) {{
          discountAmount = subtotal * (discVal / 100);
        }} else if (discType === 'fixed' && discVal > 0) {{
          discountAmount = Math.min(subtotal, discVal);
        }}

        const net = Math.max(0, subtotal - discountAmount);
        const vat = net * 0.22;
        const gross = net + vat;

        document.querySelector('#tot-subtotal').textContent = formatMoney(subtotal);
        if (discountAmount > 0) {{
          document.querySelector('#row-discount').style.display = 'flex';
          document.querySelector('#tot-discount').textContent = '-' + formatMoney(discountAmount);
        }} else {{
          document.querySelector('#row-discount').style.display = 'none';
        }}
        document.querySelector('#tot-net').textContent = formatMoney(net);
        document.querySelector('#tot-vat').textContent = formatMoney(vat);
        document.querySelector('#tot-gross').textContent = formatMoney(gross);
      }}

      async function saveRevision() {{
        const btn = document.querySelector('#btn-save');
        btn.disabled = true;
        btn.textContent = 'Salvataggio in corso...';
        showMsg('', '');

        const discType = document.querySelector('#disc-type').value;
        const discVal = parseFloat(document.querySelector('#disc-val').value) || 0;
        const discReason = document.querySelector('#disc-reason').value;

        let discountObj = null;
        if (discType && discVal > 0) {{
          discountObj = {{
            discount_type: discType,
            value: discVal,
            reason: discReason || null
          }};
        }}

        const payload = {{
          items: currentItems.map(i => ({{ code: i.code, quantity: i.quantity || 1 }})),
          discount: discountObj,
          delivery_weeks: document.querySelector('#delivery-weeks').value,
          notes: document.querySelector('#quote-notes').value,
          reason: document.querySelector('#rev-reason').value || 'Modifica dall editor admin'
        }};

        try {{
          const res = await fetch('/api/v1/quotes/{quote_id}/revisions', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(payload)
          }});

          if (res.ok) {{
            showMsg('Revisione salvata con successo! Ricarico...', 'rgba(206,255,26,0.15)', '#ceff1a');
            setTimeout(() => location.reload(), 1000);
          }} else {{
            const err = await res.json();
            showMsg('Errore nel salvataggio: ' + (err.detail || 'Verifica i campi'), 'rgba(239,68,68,0.2)', '#f87171');
          }}
        }} catch (e) {{
          showMsg('Errore di connessione: ' + e.message, 'rgba(239,68,68,0.2)', '#f87171');
        }} finally {{
          btn.disabled = false;
          btn.textContent = '💾 Salva Nuova Revisione';
        }}
      }}

      async function sendToCustomer() {{
        if (!confirm('Sei sicuro di voler approvare e inviare questo preventivo al cliente? Questa azione genererà l evento per spedire l email con il PDF allegato.')) {{
          return;
        }}

        const btn = document.querySelector('#btn-send');
        btn.disabled = true;
        btn.textContent = 'Invio in corso...';
        showMsg('', '');

        try {{
          const res = await fetch('/api/v1/quotes/{quote_id}/send', {{ method: 'POST' }});
          if (res.ok) {{
            showMsg('Preventivo confermato! L email e l evento per n8n sono stati inviati al cliente con successo.', 'rgba(206,255,26,0.2)', '#ceff1a');
            setTimeout(() => location.reload(), 1500);
          }} else {{
            const err = await res.json();
            showMsg('Errore nell invio: ' + (err.detail || 'Impossibile inviare'), 'rgba(239,68,68,0.2)', '#f87171');
          }}
        }} catch (e) {{
          showMsg('Errore di connessione: ' + e.message, 'rgba(239,68,68,0.2)', '#f87171');
        }} finally {{
          btn.disabled = false;
          btn.textContent = '🚀 Conferma ed Invia al Cliente';
        }}
      }}

      function showMsg(txt, bg, color) {{
        const el = document.querySelector('#status-msg');
        if (!txt) {{ el.style.display = 'none'; return; }}
        el.style.display = 'block';
        el.style.background = bg;
        el.style.color = color;
        el.textContent = txt;
      }}

      renderItems();
    </script>
    """
    return HTMLResponse(base_layout(f"Editor {q.get('quote_number', '')}", content))


@router.get("/new", response_class=HTMLResponse)
def new_quote_page(request: Request):
    require_auth(request)
    from .main import load_pricelist

    p = load_pricelist()
    services_html = "".join(
        f"""
        <label style='display:flex; flex-direction:row; align-items:center; gap:10px; background:var(--input-bg); border:1px solid var(--input-border); padding:12px; border-radius:8px;'>
          <input type='checkbox' name='service' value='{html.escape(code)}'>
          <div style='flex:1;'>
            <div style='font-weight:700; color:#fff;'>{html.escape(s['name'])}</div>
            <div style='font-size:12px; color:var(--text-dim);'>{html.escape(s.get('client_description') or '')}</div>
          </div>
          <div style='font-weight:700; color:var(--lime);'>{money_label(s['unit_price'])}</div>
        </label>
        """
        for code, s in p.services.items()
    )

    content = f"""
    <div style="margin-bottom: 20px;">
      <a href="/internal" style="display:inline-flex; align-items:center; gap:6px; font-size:13px; color:var(--text-dim); margin-bottom:12px;">
        ← Torna alla Dashboard
      </a>
      <h1>Crea Nuovo Preventivo</h1>
      <p style="color:var(--text-muted); font-size:14px; margin-top:4px;">Compila i dati del cliente per generare una nuova proposta DozenDev.</p>
    </div>

    <div class="card">
      <form id="new-quote-form" onsubmit="submitNewQuote(event)">
        <h3 style="margin-bottom:16px;">1. Dati Cliente</h3>
        <div class="form-grid">
          <label>Ragione Sociale / Nome Azienda *<input name="business_name" required></label>
          <label>Email Cliente *<input name="email" type="email" required></label>
          <label>Nome Referente<input name="contact_name"></label>
          <label>Telefono<input name="phone"></label>
          <label>P.IVA / Codice Fiscale<input name="vat_number"></label>
        </div>

        <h3 style="margin:24px 0 16px 0;">2. Dettagli Progetto</h3>
        <div class="form-grid">
          <label>Nome Progetto *<input name="project_name" required value="Sviluppo Sito Web"></label>
          <label>Tipo Progetto
            <select name="project_type">
              <option value="web">Web Development</option>
              <option value="ai">AI Agent & Automazioni</option>
              <option value="webapp">Web Application</option>
            </select>
          </label>
          <label>Tempistiche Consegna<input name="delivery_weeks" value="3-4 settimane"></label>
          <label>Validità (Giorni)<input name="valid_days" type="number" value="14"></label>
        </div>

        <label style="margin:16px 0 24px 0;">
          Note Aggiuntive per il Cliente
          <textarea name="notes" rows="3"></textarea>
        </label>

        <h3 style="margin-bottom:16px;">3. Voci e Servizi Inclusi</h3>
        <div style="display:grid; gap:10px; margin-bottom:24px;">
          {services_html}
        </div>

        <div style="display:flex; justify-content:flex-end; gap:12px;">
          <a href="/internal" class="btn btn-secondary">Annulla</a>
          <button type="submit" class="btn btn-primary" id="btn-create">Genera Preventivo</button>
        </div>
      </form>
    </div>

    <script>
      async function submitNewQuote(e) {{
        e.preventDefault();
        const f = e.target;
        const btn = document.querySelector('#btn-create');
        btn.disabled = true;
        btn.textContent = 'Creazione in corso...';

        const fd = new FormData(f);
        const selectedServices = [...f.querySelectorAll('input[name=service]:checked')].map(x => ({{ code: x.value, quantity: 1 }}));

        if (!selectedServices.length) {{
          alert('Seleziona almeno un servizio o pacchetto');
          btn.disabled = false;
          btn.textContent = 'Genera Preventivo';
          return;
        }}

        const body = {{
          customer: {{
            business_name: fd.get('business_name'),
            email: fd.get('email'),
            contact_name: fd.get('contact_name') || null,
            phone: fd.get('phone') || null,
            vat_number: fd.get('vat_number') || null
          }},
          project_name: fd.get('project_name'),
          project_type: fd.get('project_type'),
          delivery_weeks: fd.get('delivery_weeks') || null,
          valid_days: parseInt(fd.get('valid_days')) || 14,
          notes: fd.get('notes') || null,
          items: selectedServices
        }};

        try {{
          const res = await fetch('/api/v1/quotes', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(body)
          }});

          if (res.ok) {{
            const data = await res.json();
            location.href = '/internal/quote/' + data.quote_id;
          }} else {{
            const err = await res.json();
            alert('Errore: ' + (err.detail || 'Impossibile creare il preventivo'));
            btn.disabled = false;
            btn.textContent = 'Genera Preventivo';
          }}
        }} catch (err) {{
          alert('Errore di connessione: ' + err.message);
          btn.disabled = false;
          btn.textContent = 'Genera Preventivo';
        }}
      }}
    </script>
    """
    return HTMLResponse(base_layout("Nuovo Preventivo", content))
