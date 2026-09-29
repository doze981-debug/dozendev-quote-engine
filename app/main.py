from __future__ import annotations

import html
import hmac
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib import request

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, Response

from .contract_handoff import build_contract_handoff
from .contractgen import build_contract_pack, build_contract_pdf
from .lifecycle import checklist_complete, default_checklist, first_installment
from .pdfgen import build_quote_pdf
from .pricing import PriceList
from .schemas import (
    ChecklistUpdateRequest,
    ContractProviderCreatedRequest,
    DepositCreatedRequest,
    DepositPaidRequest,
    DiscountRequest,
    PublicConfigureRequest,
    QuoteApproveRequest,
    QuoteCreateRequest,
    QuoteItemRequest,
    QuoteRevisionRequest,
    SignatureCompletedRequest,
    ProposalInterestRequest,
    CallBookingRequest,
    CallCancelRequest,
    EmailStatusRequest,
)
from .store import QuoteStore
from .admin import router as admin_router

BASE = Path(__file__).resolve().parent.parent
PRICELIST_PATH = BASE / "data" / "pricelist.json"
CONTRACT_MASTER_PATH = BASE / "data" / "Contratto_Master_DozenDev.json"

app = FastAPI(title="DozenDev Quote-to-Project Engine", version="0.4.0")
app.include_router(admin_router)
store = QuoteStore()

HMAC_SECRET = os.getenv("QUOTE_ENGINE_HMAC_SECRET", "").strip()


async def verify_hmac(req: Request):
    if not HMAC_SECRET:
        return
    signature_header = req.headers.get("X-Signature") or req.headers.get("X-Dozen-Signature")
    timestamp_header = req.headers.get("X-Timestamp") or req.headers.get("X-Dozen-Timestamp")
    if not signature_header or not timestamp_header:
        raise HTTPException(status_code=401, detail="Missing HMAC signature or timestamp")

    try:
        req_time = int(timestamp_header)
        now_time = int(datetime.now(timezone.utc).timestamp())
        if abs(now_time - req_time) > 300:
            raise HTTPException(status_code=401, detail="Timestamp out of bounds (replay protection)")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid timestamp header")

    body = await req.body()
    expected = hmac.new(HMAC_SECRET.encode("utf-8"), f"{timestamp_header}.".encode("utf-8") + body, hashlib.sha256).hexdigest()
    sig = signature_header.replace("sha256=", "")
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")


def load_pricelist() -> PriceList:
    return PriceList.load(PRICELIST_PATH)


def to_json_dict(model):
    return jsonable_encoder(model, custom_encoder={Decimal: lambda v: str(v)})


def money_label(v) -> str:
    return f"â‚¬ {Decimal(str(v)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def narrative_for(project: str, items: list[dict], total: Decimal) -> str:
    names = ", ".join(i["name"] for i in items)
    return (
        f"Per {project} la proposta comprende {names}. "
        "L'obiettivo Ã¨ consegnare uno scope chiaro e verificabile, con le componenti economiche calcolate esclusivamente dal prezziario DozenDev. "
        f"L'investimento complessivo Ã¨ {money_label(total)} + IVA."
    )


def make_snapshot(*, payload: QuoteCreateRequest, pricing: PriceList, status: str = "DRAFT") -> dict:
    items = pricing.resolve_items(payload.items)
    totals = pricing.calculate(items, payload.discount)
    now = datetime.now(timezone.utc)
    items_dict = [to_json_dict(i) for i in items]
    totals_dict = to_json_dict(totals)
    return {
        "status": status,
        "customer": payload.customer.model_dump(),
        "project_name": payload.project_name,
        "project_type": payload.project_type,
        "items": items_dict,
        "totals": totals_dict,
        "discount_config": to_json_dict(payload.discount) if payload.discount else None,
        "pricelist_version": pricing.version,
        "valid_until": (now + timedelta(days=payload.valid_days)).isoformat(),
        "narrative": narrative_for(payload.project_name, items_dict, totals.net_total),
        "easy_summary": {
            "rows": [{"label": i["name"], "quantity": i["quantity"], "amount": i["total"]} for i in items_dict],
            **totals_dict,
        },
        "notes": payload.notes,
        "delivery_weeks": payload.delivery_weeks,
        "acceptance_criteria": payload.acceptance_criteria,
        "exclusions": payload.exclusions,
        "external_lead_id": payload.external_lead_id,
        "source": payload.source,
        "source_data": payload.source_data,
    }


def revision_snapshot(current: dict, pricing: PriceList, payload: QuoteRevisionRequest) -> dict:
    resolved = pricing.resolve_items(payload.items)
    totals = pricing.calculate(resolved, payload.discount)
    items_dict = [to_json_dict(i) for i in resolved]
    totals_dict = to_json_dict(totals)
    return {
        "customer": current["customer"],
        "project_name": current["project_name"],
        "project_type": current["project_type"],
        "items": items_dict,
        "totals": totals_dict,
        "discount_config": to_json_dict(payload.discount) if payload.discount else None,
        "pricelist_version": pricing.version,
        "valid_until": current["valid_until"],
        "narrative": narrative_for(current["project_name"], items_dict, totals.net_total),
        "easy_summary": {"rows": [{"label": i["name"], "quantity": i["quantity"], "amount": i["total"]} for i in items_dict], **totals_dict},
        "notes": payload.notes if payload.notes is not None else current.get("notes"),
        "delivery_weeks": payload.delivery_weeks if payload.delivery_weeks is not None else current.get("delivery_weeks"),
        "acceptance_criteria": payload.acceptance_criteria if payload.acceptance_criteria is not None else current.get("acceptance_criteria", []),
        "exclusions": payload.exclusions if payload.exclusions is not None else current.get("exclusions", []),
        "external_lead_id": current.get("external_lead_id"),
        "source": current.get("source"),
        "source_data": current.get("source_data"),
    }


def public_base() -> str:
    return os.getenv("QUOTE_PUBLIC_BASE_URL", "http://localhost:8000/proposta").rstrip("/")


def internal_base() -> str:
    return os.getenv("INTERNAL_BASE_URL", "http://localhost:8000").rstrip("/")


def post_webhook(url: str | None, payload: dict) -> dict:
    result = {"attempted": False, "ok": False}
    if not url:
        return result
    raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if HMAC_SECRET:
        ts = str(int(datetime.now(timezone.utc).timestamp()))
        sig = hmac.new(HMAC_SECRET.encode("utf-8"), f"{ts}.".encode("utf-8") + raw_body, hashlib.sha256).hexdigest()
        headers["X-Signature"] = f"sha256={sig}"
        headers["X-Timestamp"] = ts
    req = request.Request(url, data=raw_body, method="POST", headers=headers)
    result["attempted"] = True
    try:
        with request.urlopen(req, timeout=8) as response:
            result["ok"] = 200 <= response.status < 300
            result["status"] = response.status
    except Exception as exc:
        result["error"] = str(exc)
    return result


def emit(event: str, payload: dict) -> dict:
    specific = os.getenv(f"N8N_{event}_WEBHOOK_URL")
    generic = os.getenv("N8N_EVENT_WEBHOOK_URL")
    body = {"event": event, **payload}
    return {"specific": post_webhook(specific, body), "generic": post_webhook(generic, body) if generic != specific else {"attempted": False, "ok": False}}


def ensure_not_expired(quote: dict):
    if datetime.fromisoformat(quote["valid_until"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Quote expired")


def require_quote(quote_id: str) -> dict:
    q = store.get(quote_id)
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    return q


def require_approved(quote_id: str) -> dict:
    q = require_quote(quote_id)
    if q["status"] != "APPROVED":
        raise HTTPException(status_code=409, detail="Quote must be approved first")
    return q


@app.get("/health")
def health():
    return {"ok": True, "service": "dozendev-quote-to-project-engine", "version": "0.4.0"}


@app.get("/api/v1/pricelist")
def pricelist():
    return json.loads(PRICELIST_PATH.read_text(encoding="utf-8"))


@app.get("/api/v1/contract-master")
def contract_master():
    return json.loads(CONTRACT_MASTER_PATH.read_text(encoding="utf-8"))


@app.get("/api/v1/quotes")
def list_quotes():
    return store.list_quotes()


@app.post("/api/v1/quotes")
async def create_quote(payload: QuoteCreateRequest, req: Request):
    await verify_hmac(req)
    try:
        quote, token = store.create(make_snapshot(payload=payload, pricing=load_pricelist()))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        **quote,
        "public_url": f"{public_base()}/{token}",
        "public_token": token,
        "idempotent": bool(quote.get("idempotent", False)),
    }


@app.get("/api/v1/quotes/{quote_id}")
def get_quote(quote_id: str):
    return require_quote(quote_id)


@app.get("/api/v1/quotes/{quote_id}/versions")
def quote_versions(quote_id: str):
    require_quote(quote_id)
    return store.versions(quote_id)


@app.get("/api/v1/quotes/{quote_id}/events")
def quote_events(quote_id: str):
    require_quote(quote_id)
    return store.events(quote_id)


@app.post("/api/v1/quotes/{quote_id}/send")
def send_quote(quote_id: str):
    require_quote(quote_id)
    try:
        q = store.mark_sent(quote_id)
        token = store.rotate_public_token(quote_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    public_url = f"{public_base()}/{token}"
    delivery = emit("QUOTE_SENT", {"quote": q, "public_url": public_url})
    return {"quote": q, "public_url": public_url, "delivery": delivery}


@app.post("/api/v1/quotes/{quote_id}/public-token")
def rotate_public_token(quote_id: str):
    q = require_quote(quote_id)
    if q["status"] == "APPROVED":
        raise HTTPException(status_code=409, detail="Approved quote public link cannot be rotated")
    token = store.rotate_public_token(quote_id)
    return {"quote_id": quote_id, "public_url": f"{public_base()}/{token}"}


@app.post("/api/v1/quotes/{quote_id}/revisions")
def revise_quote(quote_id: str, payload: QuoteRevisionRequest):
    current = require_quote(quote_id)
    try:
        snap = revision_snapshot(current, load_pricelist(), payload)
        return store.revise(quote_id, snap, actor="internal", reason=payload.reason)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/v1/quotes/{quote_id}/pdf")
def quote_pdf(quote_id: str):
    q = require_quote(quote_id)
    return Response(build_quote_pdf(q), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{q["quote_number"]}-v{q["version"]}.pdf"'})


@app.post("/api/v1/quotes/{quote_id}/interest")
async def quote_interest(quote_id: str, payload: ProposalInterestRequest, req: Request):
    await verify_hmac(req)
    require_quote(quote_id)
    audit = payload.model_dump()
    audit["client_ip"] = audit.get("client_ip") or (req.client.host if req.client else None)
    audit["user_agent"] = audit.get("user_agent") or req.headers.get("user-agent")
    audit["expressed_at"] = datetime.now(timezone.utc).isoformat()
    updated = store.mark_interested(quote_id, audit)
    delivery = emit("PROPOSAL_INTERESTED", {"quote": updated, "audit": audit})
    return {"quote": updated, "status": "INTERESTED", "delivery": delivery}


@app.post("/api/v1/quotes/{quote_id}/call-booked")
async def quote_call_booked(quote_id: str, payload: CallBookingRequest, req: Request):
    await verify_hmac(req)
    require_quote(quote_id)
    life = store.call_booked(quote_id, payload.model_dump())
    delivery = emit("CALL_BOOKED", {"quote_id": quote_id, "booking": payload.model_dump()})
    return {"quote_id": quote_id, "lifecycle": life, "delivery": delivery}


@app.post("/api/v1/quotes/{quote_id}/call-cancelled")
async def quote_call_cancelled(quote_id: str, payload: CallCancelRequest, req: Request):
    await verify_hmac(req)
    require_quote(quote_id)
    life = store.call_cancelled(quote_id, payload.model_dump())
    delivery = emit("CALL_CANCELLED", {"quote_id": quote_id, "cancellation": payload.model_dump()})
    return {"quote_id": quote_id, "lifecycle": life, "delivery": delivery}


@app.post("/api/v1/quotes/{quote_id}/email-status")
async def quote_email_status(quote_id: str, payload: EmailStatusRequest, req: Request):
    await verify_hmac(req)
    require_quote(quote_id)
    result = store.record_email_status(quote_id, payload.model_dump())
    return {"quote_id": quote_id, "email_status": payload.model_dump(), "result": result}


@app.post("/api/v1/quotes/{quote_id}/approve")
def approve_quote(quote_id: str, payload: QuoteApproveRequest, req: Request):
    current = require_quote(quote_id)
    ensure_not_expired(current)
    if not payload.confirm_business_authority:
        raise HTTPException(status_code=422, detail="Business authority confirmation is required")
    audit = payload.model_dump()
    audit["client_ip"] = audit.get("client_ip") or (req.client.host if req.client else None)
    audit["user_agent"] = audit.get("user_agent") or req.headers.get("user-agent")
    try:
        approved = store.approve(quote_id, to_json_dict(audit))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    handoff = build_contract_handoff(approved)
    delivery = emit("QUOTE_APPROVED", {"quote": approved, "contract_handoff": handoff})
    return {"quote": approved, "contract_handoff": handoff, "delivery": delivery}


@app.get("/api/v1/public/{token}")
def public_quote(token: str):
    q = store.get_by_public_token(token, mark_viewed=True)
    if not q:
        raise HTTPException(status_code=404, detail="Proposal not found")
    pricing = load_pricelist()
    options = [{"code": c, "name": s["name"], "description": s.get("client_description", s["name"]), "unit_price": str(s["unit_price"])} for c, s in pricing.services.items() if s.get("customer_configurable", False)]
    return {"quote": q, "configurable_options": options}


@app.post("/api/v1/public/{token}/configure")
def public_configure(token: str, payload: PublicConfigureRequest):
    current = store.get_by_public_token(token)
    if not current:
        raise HTTPException(status_code=404, detail="Proposal not found")
    ensure_not_expired(current)
    if current["status"] == "APPROVED":
        raise HTTPException(status_code=409, detail="Approved quote is frozen")
    pricing = load_pricelist()
    allowed = {code for code, s in pricing.services.items() if s.get("customer_configurable", False)}
    invalid = set(payload.selected_optional_codes) - allowed
    if invalid:
        raise HTTPException(status_code=422, detail=f"Options not configurable by customer: {', '.join(sorted(invalid))}")
    locked = [QuoteItemRequest(code=i["code"], quantity=Decimal(str(i["quantity"]))) for i in current["items"] if not i.get("customer_configurable", False)]
    selected = [QuoteItemRequest(code=c, quantity=Decimal("1")) for c in payload.selected_optional_codes]
    discount = DiscountRequest(**current["discount_config"]) if current.get("discount_config") else None
    rev = QuoteRevisionRequest(items=locked + selected, discount=discount, notes=current.get("notes"), reason="Customer configuration")
    snap = revision_snapshot(current, pricing, rev)
    return store.revise(current["quote_id"], snap, actor="customer", reason="Customer configuration")


@app.post("/api/v1/public/{token}/interest")
def public_interest(token: str, payload: ProposalInterestRequest, req: Request):
    current = store.get_by_public_token(token)
    if not current:
        raise HTTPException(status_code=404, detail="Proposal not found")
    ensure_not_expired(current)
    if current["status"] == "APPROVED":
        raise HTTPException(status_code=409, detail="Approved proposal is already finalized into contract")
    audit = payload.model_dump()
    audit["client_ip"] = audit.get("client_ip") or (req.client.host if req.client else None)
    audit["user_agent"] = audit.get("user_agent") or req.headers.get("user-agent")
    audit["expressed_at"] = datetime.now(timezone.utc).isoformat()
    updated = store.mark_interested(current["quote_id"], audit)
    delivery = emit("PROPOSAL_INTERESTED", {"quote": updated, "audit": audit})
    return {"quote": updated, "status": "INTERESTED", "delivery": delivery}


@app.post("/api/v1/public/{token}/approve")
def public_approve(token: str, payload: QuoteApproveRequest, req: Request):
    current = store.get_by_public_token(token)
    if not current:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return approve_quote(current["quote_id"], payload, req)


@app.get("/api/v1/quotes/{quote_id}/contract-handoff")
def quote_contract_handoff(quote_id: str):
    approved = require_approved(quote_id)
    return build_contract_handoff(approved)


@app.get("/api/v1/quotes/{quote_id}/contract/pack")
def quote_contract_pack(quote_id: str):
    approved = require_approved(quote_id)
    return build_contract_pack(approved, CONTRACT_MASTER_PATH)


@app.get("/api/v1/quotes/{quote_id}/contract/pdf")
def quote_contract_pdf(quote_id: str):
    approved = require_approved(quote_id)
    pack = build_contract_pack(approved, CONTRACT_MASTER_PATH)
    return Response(build_contract_pdf(pack), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{approved["quote_number"]}-contratto.pdf"'})


@app.get("/api/v1/quotes/{quote_id}/lifecycle")
def get_lifecycle(quote_id: str):
    require_quote(quote_id)
    life = store.lifecycle(quote_id)
    return life or {"quote_id": quote_id, "state": "DRAFT", "contract": {}, "payment": {}, "onboarding": {}}


@app.post("/api/v1/quotes/{quote_id}/contract/provider-created")
def contract_provider_created(quote_id: str, payload: ContractProviderCreatedRequest):
    require_approved(quote_id)
    updated = store.contract_created(quote_id, to_json_dict(payload))
    delivery = emit("CONTRACT_SENT", {"quote_id": quote_id, "lifecycle": updated, "payload": to_json_dict(payload)})
    return {"lifecycle": updated, "delivery": delivery}


@app.post("/api/v1/quotes/{quote_id}/contract/signed")
def contract_signed(quote_id: str, payload: SignatureCompletedRequest):
    require_approved(quote_id)
    if not payload.general_signature_completed or not payload.specific_1341_1342_completed:
        raise HTTPException(status_code=422, detail="Both general and 1341/1342 specific signatures are required")
    updated = store.contract_signed(quote_id, to_json_dict(payload))
    delivery = emit("CONTRACT_SIGNED", {"quote_id": quote_id, "lifecycle": updated, "payload": to_json_dict(payload)})
    return {"lifecycle": updated, "delivery": delivery}


@app.post("/api/v1/quotes/{quote_id}/deposit/provider-created")
def deposit_provider_created(quote_id: str, payload: DepositCreatedRequest):
    require_approved(quote_id)
    updated = store.deposit_created(quote_id, to_json_dict(payload))
    delivery = emit("DEPOSIT_PENDING", {"quote_id": quote_id, "lifecycle": updated, "payload": to_json_dict(payload)})
    return {"lifecycle": updated, "delivery": delivery}


@app.post("/api/v1/quotes/{quote_id}/deposit/paid")
def deposit_paid(quote_id: str, payload: DepositPaidRequest):
    approved = require_approved(quote_id)
    checklist = default_checklist(approved)
    onboarding = {"checklist": checklist, "complete": False, "started_at": datetime.now(timezone.utc).isoformat()}
    updated = store.deposit_paid(quote_id, to_json_dict(payload), onboarding)
    delivery = emit("ONBOARDING_STARTED", {"quote_id": quote_id, "lifecycle": updated, "payload": to_json_dict(payload)})
    return {"lifecycle": updated, "delivery": delivery}


@app.put("/api/v1/quotes/{quote_id}/onboarding/checklist")
def update_onboarding_checklist(quote_id: str, payload: ChecklistUpdateRequest):
    require_approved(quote_id)
    items = [to_json_dict(i) for i in payload.items]
    complete = checklist_complete(items)
    updated = store.update_checklist(quote_id, items, complete)
    delivery = emit("PROJECT_READY" if complete else "ONBOARDING_UPDATED", {"quote_id": quote_id, "lifecycle": updated, "complete": complete})
    return {"lifecycle": updated, "delivery": delivery}


# --- UI ENDPOINTS (Internal & Public) ----------------------------------------

@app.get("/internal", response_class=HTMLResponse)
def internal_dashboard():
    quotes = store.list_quotes()
    rows = "".join(f"<tr><td><a href='/internal/quote/{q['quote_id']}'>{html.escape(q['quote_number'])}</a></td><td>{html.escape(q['customer']['business_name'])}</td><td>{money_label(q['totals']['net_total'])}</td><td><span class='pill'>{html.escape(q['status'])}</span></td><td>{html.escape(q['created_at'][:10])}</td></tr>" for q in quotes)
    return HTMLResponse(f"""<!doctype html><html><head><meta charset='utf-8'><title>DozenDev Quotes</title><style>{CSS}</style></head><body><main><h1>Preventivi DozenDev</h1><p><a class='button' href='/internal/new'>+ Nuovo Preventivo</a></p><table><thead><tr><th>Numero</th><th>Cliente</th><th>Netto</th><th>Stato</th><th>Data</th></tr></thead><tbody>{rows}</tbody></table></main></body></html>""")


@app.get("/internal/new", response_class=HTMLResponse)
def internal_new_quote():
    p = load_pricelist()
    services = "".join(f"<label class='service'><input type='checkbox' name='service' value='{html.escape(s['code'])}'> <b>{html.escape(s['name'])}</b><span>{money_label(s['unit_price'])}</span><small>{html.escape(s.get('client_description',''))}</small></label>" for s in p.services.values())
    return HTMLResponse(f"""<!doctype html><html><head><meta charset='utf-8'><title>Nuovo Preventivo</title><style>{CSS}</style></head><body><main><a href='/internal'>â† Indietro</a><h1>Crea Preventivo</h1><form id='f'><div class='grid'><label>Ragione Sociale<input name='business_name' required></label><label>Email<input name='email' type='email' required></label><label>Referente<input name='contact_name'></label><label>P.IVA / CF<input name='vat_number'></label></div><div class='grid'><label>Nome Progetto<input name='project_name' required value='Sito Web'></label><label>Tipo Progetto<select name='project_type'><option value='web'>Web</option><option value='ai'>AI</option><option value='webapp'>Web App</option></select></label><label>Tempistiche<input name='delivery_weeks' value='3-4 settimane'></label><label>ValiditÃ  (giorni)<input name='valid_days' type='number' value='14'></label></div><label>Note aggiuntive<textarea name='notes'></textarea></label><h2>Seleziona Voci</h2><div class='services'>{services}</div><button type='submit'>Genera Preventivo</button></form><pre id='result'></pre></main><script>
const f=document.querySelector('#f');f.addEventListener('submit',async(e)=>{{e.preventDefault();const fd=new FormData(f);const body={{customer:{{business_name:fd.get('business_name'),email:fd.get('email'),contact_name:fd.get('contact_name')||null,vat_number:fd.get('vat_number')||null}},project_name:fd.get('project_name'),project_type:fd.get('project_type'),delivery_weeks:fd.get('delivery_weeks')||null,valid_days:Number(fd.get('valid_days')),notes:fd.get('notes')||null,items:[...document.querySelectorAll('input[name=service]:checked')].map(x=>({{code:x.value,quantity:1}}))}};const r=await fetch('/api/v1/quotes',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify(body)}});const j=await r.json();if(r.ok) location.href='/internal/quote/'+j.quote_id; else document.querySelector('#result').textContent=JSON.stringify(j,null,2);}});
</script></body></html>""")


@app.get("/internal/quote/{quote_id}", response_class=HTMLResponse)
def internal_quote(quote_id: str):
    q = require_quote(quote_id)
    life = store.lifecycle(quote_id)
    items = "".join(f"<tr><td>{html.escape(i['name'])}</td><td>{i['quantity']}</td><td>{money_label(i['unit_price'])}</td><td>{money_label(i['total'])}</td></tr>" for i in q["items"])
    events = "".join(f"<li>{html.escape(e['created_at'])} - <b>{html.escape(e['event_type'])}</b> ({html.escape(e.get('actor') or '-')})</li>" for e in store.events(quote_id))
    life_html = html.escape(json.dumps(life or {"state":"not started"}, indent=2, ensure_ascii=False))
    return HTMLResponse(f"""<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(q['quote_number'])}</title><style>{CSS}</style></head><body><main><a href='/internal'>â† Preventivi</a><h1>{html.escape(q['quote_number'])} <span class='pill'>{html.escape(q['status'])}</span></h1><h2>{html.escape(q['project_name'])}</h2><p>{html.escape(q['customer']['business_name'])} Â· {html.escape(q['customer']['email'])}</p><table><thead><tr><th>Voce</th><th>Qta</th><th>Unitario</th><th>Totale</th></tr></thead><tbody>{items}</tbody></table><h2>{money_label(q['totals']['net_total'])} + IVA</h2><div class='actions'><a class='button' target='_blank' href='/api/v1/quotes/{quote_id}/pdf'>PDF</a><button onclick='sendQuote()'>Segna inviato / evento n8n</button><a class='button secondary' target='_blank' href='/api/v1/quotes/{quote_id}/contract-handoff'>Payload contratto</a></div><h2>Lifecycle</h2><pre>{life_html}</pre><h2>Audit</h2><ul>{events}</ul></main><script>async function sendQuote(){{const r=await fetch('/api/v1/quotes/{quote_id}/send',{{method:'POST'}});alert(r.ok?'Evento inviato':'Errore');location.reload();}}</script></body></html>""")


@app.get("/proposta/{token}", response_class=HTMLResponse)
def proposal_page(token: str):
    q = store.get_by_public_token(token, mark_viewed=True)
    if not q:
        raise HTTPException(status_code=404, detail="Proposal not found")
    p = load_pricelist()
    selected = {i["code"] for i in q["items"] if i.get("customer_configurable")}
    options = "".join(f"<label class='service'><input type='checkbox' class='opt' value='{html.escape(code)}' {'checked' if code in selected else ''} {'disabled' if q['status']=='APPROVED' else ''}> <b>{html.escape(s['name'])}</b><span>+ {money_label(s['unit_price'])}</span><small>{html.escape(s.get('client_description',''))}</small></label>" for code,s in p.services.items() if s.get("customer_configurable",False))
    rows = "".join(f"<tr><td>{html.escape(i['name'])}</td><td>{i['quantity']}</td><td>{money_label(i['total'])}</td></tr>" for i in q["items"])
    approved = q["status"] == "APPROVED"
    is_interested = q["status"] == "INTERESTED"
    button_html = "" if approved else '<button onclick="configure()">Ricalcola proposta</button>'
    interest_status_text = "âœ“ Interesse giÃ  confermato (Prenota Call)" if is_interested else "Mi interessa, fissiamo una call â†’"
    interest_display = "block" if is_interested else "none"
    approval_title = "Proposta approvata e finalizzata" if approved else "Approvazione Definitiva & Contratto"
    approval_content = "<p>Questa versione Ã¨ congelata. Il processo prosegue con la firma del contratto.</p>" if approved else "<p class='muted' style='margin-bottom:16px;'>L'approvazione definitiva congela il preventivo e genera il contratto master vincolante. Consigliata dopo la call conoscitiva.</p>" + APPROVAL_FORM
    
    return HTMLResponse(f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Proposta {html.escape(q['quote_number'])}</title><style>{CSS}</style></head><body><main class='proposal'><p class='muted'>DOZENDEV Â· {html.escape(q['quote_number'])} Â· v{q['version']}</p><h1>{html.escape(q['project_name'])}</h1><p>{html.escape(q['narrative'])}</p><h2>Dettaglio rapido</h2><table><thead><tr><th>Voce</th><th>Qta</th><th>Totale</th></tr></thead><tbody>{rows}</tbody></table><div class='total'>{money_label(q['totals']['net_total'])} <small>+ IVA</small></div><p><a class='button secondary' target='_blank' href='/api/v1/quotes/{q['quote_id']}/pdf'>Scarica PDF Proposta</a></p><h2>Personalizza gli optional</h2><p class='muted'>Puoi modificare queste opzioni. Lo scope e i prezzi base restano bloccati.</p><div class='services'>{options}</div>{button_html}<hr><div class='interest-box' style='background:#f0f9ff;border:1px solid #bae6fd;padding:24px;border-radius:12px;margin:24px 0;'><h3 style='margin:0 0 8px 0;color:#0369a1;'>Ti interessa questa stima di preventivo?</h3><p style='margin:0 0 16px 0;color:#0c4a6e;font-size:15px;line-height:1.5;'>Se l'investimento e l'impostazione iniziale rispondono alle tue esigenze, clicca per confermare il tuo interesse. Potrai fissare la discovery call con Domenico Mazza per definire ogni dettaglio operativo prima della chiusura contrattuale.</p><button class='button' style='background:#0284c7;font-size:15px;padding:12px 20px;' onclick='markInterested()'>{interest_status_text}</button><div id='interest-feedback' style='display:{interest_display};margin-top:16px;padding:14px;background:#ecfdf5;border-left:4px solid #10b981;border-radius:4px;color:#065f46;'><strong>Perfetto!</strong> Il tuo interesse Ã¨ stato registrato nel Quote Engine. Ti abbiamo inviato via email il link per fissare la call su Cal.com, oppure <a href='https://cal.com/dozendev/discovery' target='_blank' style='color:#059669;font-weight:bold;text-decoration:underline;'>clicca qui per aprire subito il calendario</a>.</div></div><hr><h2>{approval_title}</h2>{approval_content}<pre id='msg'></pre></main><script>
async function configure(){{const codes=[...document.querySelectorAll('.opt:checked')].map(x=>x.value);const r=await fetch('/api/v1/public/{token}/configure',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{selected_optional_codes:codes}})}});if(r.ok) location.reload();else document.querySelector('#msg').textContent=JSON.stringify(await r.json(),null,2)}}
async function markInterested(){{const r=await fetch('/api/v1/public/{token}/interest',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{notes:'Interesse confermato dalla proposta online'}})}});const fb=document.querySelector('#interest-feedback');fb.style.display='block';if(r.ok){{fb.innerHTML='<strong>Perfetto!</strong> Il tuo interesse Ã¨ stato registrato nel Quote Engine. Ti abbiamo inviato via email il link per fissare la call su Cal.com, oppure <a href="https://cal.com/dozendev/discovery" target="_blank" style="color:#059669;font-weight:bold;text-decoration:underline;">clicca qui per aprire subito il calendario</a>.';}}else{{const j=await r.json();fb.innerHTML='<span style="color:#dc2626;">Errore: '+(j.detail||'Impossibile registrare la preferenza')+'</span>';}}}}
async function approve(){{const name=document.querySelector('#accepted_by').value,email=document.querySelector('#accepted_email').value,auth=document.querySelector('#authority').checked;if(!name||!email||!auth){{alert('Completa i campi di approvazione');return}}const r=await fetch('/api/v1/public/{token}/approve',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{accepted_by:name,accepted_email:email,confirm_business_authority:auth}})}});const j=await r.json();if(r.ok) location.reload();else document.querySelector('#msg').textContent=JSON.stringify(j,null,2)}}
</script></body></html>""")


APPROVAL_FORM = """<div class='grid'><label>Nome e cognome<input id='accepted_by'></label><label>Email<input id='accepted_email' type='email'></label></div><label class='check'><input id='authority' type='checkbox'> Confermo di essere autorizzato ad approvare la proposta per l'azienda indicata.</label><button onclick='approve()'>Approva questa versione (Avvia Contratto)</button>"""

CSS = """
:root{font-family:Inter,system-ui,Arial,sans-serif;color:#171717;background:#f6f7f8}body{margin:0}main{max-width:1080px;margin:0 auto;padding:40px 24px}.proposal{max-width:820px;background:white;min-height:100vh}h1{font-size:34px;margin-bottom:8px}h2{margin-top:32px}a{color:#111}.muted{color:#6b7280}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}label{display:flex;flex-direction:column;gap:6px;font-weight:600}input,select,textarea{padding:11px;border:1px solid #cfd3d7;border-radius:8px;font:inherit}textarea{min-height:90px}.services{display:grid;gap:10px;margin:16px 0}.service{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:10px;padding:14px;background:white;border:1px solid #e3e5e7;border-radius:10px}.service small{grid-column:2/-1;color:#666;font-weight:400}.service span{font-weight:700}button,.button{display:inline-block;background:#111;color:white;border:0;border-radius:8px;padding:11px 16px;font-weight:700;text-decoration:none;cursor:pointer}.secondary{background:#5f6368}.actions{display:flex;gap:10px;flex-wrap:wrap}table{width:100%;border-collapse:collapse;background:white}th,td{text-align:left;padding:12px;border-bottom:1px solid #e5e7eb}th{background:#f0f1f2}.total{font-size:32px;font-weight:800;text-align:right;margin-top:20px}.total small{font-size:16px}.pill{font-size:13px;background:#e5e7eb;padding:5px 8px;border-radius:20px}pre{background:#111;color:#f4f4f4;padding:16px;border-radius:8px;overflow:auto}.check{display:block;margin:20px 0;font-weight:500}hr{border:0;border-top:1px solid #ddd;margin:36px 0}@media(max-width:700px){.grid{grid-template-columns:1fr}.service{grid-template-columns:auto 1fr}.service span{grid-column:2}.service small{grid-column:2}main{padding:24px 16px}}
"""


