from decimal import Decimal
import hashlib
import hmac
import json
import time
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
import app.main as main
from app.pricing import PriceList
from app.store import QuoteStore


def client_with_tmp_db(tmp_path):
    main.store = QuoteStore(str(tmp_path / "quotes.db"))
    main.HMAC_SECRET = ""
    return TestClient(app)


def test_pricing_startup_premium_exclusive():
    pricing = PriceList.load(Path("data/pricelist.json"))
    
    # 1. STARTUP: WEB_BASE_5 (1800) + PIEMONTE30 (-30%) = 1260
    startup_items = pricing.resolve_items([main.QuoteItemRequest(code="WEB_BASE_5")])
    startup_discount = main.DiscountRequest(code="PIEMONTE30")
    startup_totals = pricing.calculate(startup_items, startup_discount)
    assert startup_totals.subtotal == Decimal("1800.00")
    assert startup_totals.discount == Decimal("540.00")
    assert startup_totals.net_total == Decimal("1260.00")

    # 2. PREMIUM: WEB_PREMIUM = 3500 + IVA
    premium_items = pricing.resolve_items([main.QuoteItemRequest(code="WEB_PREMIUM")])
    premium_totals = pricing.calculate(premium_items, None)
    assert premium_totals.net_total == Decimal("3500.00")

    # 3. EXCLUSIVE: WEB_EXCLUSIVE = 5000 + IVA
    exclusive_items = pricing.resolve_items([main.QuoteItemRequest(code="WEB_EXCLUSIVE")])
    exclusive_totals = pricing.calculate(exclusive_items, None)
    assert exclusive_totals.net_total == Decimal("5000.00")


def test_idempotency_external_lead_id(tmp_path):
    c = client_with_tmp_db(tmp_path)

    payload = {
        "customer": {"business_name": "Studio Rossi", "email": "rossi@example.com"},
        "project_name": "Sito Web Startup",
        "project_type": "web",
        "items": [{"code": "WEB_BASE_5", "quantity": 1}],
        "discount": {"code": "PIEMONTE30"},
        "external_lead_id": "LEAD-STARTUP-12345",
        "notes": "[Automazione richiesta: Lead Automation] Necessario CRM sync",
    }

    # Primo invio
    r1 = c.post("/api/v1/quotes", json=payload)
    assert r1.status_code == 200, r1.text
    data1 = r1.json()
    qid1 = data1["quote_id"]
    token1 = data1["public_token"]
    assert Decimal(data1["totals"]["net_total"]) == Decimal("1260.00")

    # Secondo invio con lo stesso external_lead_id: deve essere IDEMPOTENTE
    r2 = c.post("/api/v1/quotes", json=payload)
    assert r2.status_code == 200, r2.text
    data2 = r2.json()
    assert data2["quote_id"] == qid1
    assert data2["public_token"] == token1
    assert data2["idempotent"] is True

    # Verifica che nel database esista un solo record
    quotes = main.store.list_quotes()
    assert len(quotes) == 1
    assert quotes[0]["quote_id"] == qid1


def test_public_interest_transition_not_approved(tmp_path):
    c = client_with_tmp_db(tmp_path)

    payload = {
        "customer": {"business_name": "PMI Torino", "email": "info@pmitorino.it"},
        "project_name": "Nuovo Portale Web",
        "project_type": "web",
        "items": [{"code": "WEB_PREMIUM", "quantity": 1}],
        "external_lead_id": "LEAD-PREMIUM-777",
    }
    r = c.post("/api/v1/quotes", json=payload)
    token = r.json()["public_token"]
    qid = r.json()["quote_id"]

    # Utente clicca 'Mi interessa, fissiamo una call'
    r_int = c.post(f"/api/v1/public/{token}/interest", json={
        "accepted_by": "Mario Rossi",
        "accepted_email": "info@pmitorino.it",
        "notes": "Interessato al pacchetto Premium, vorrei valutare integrazione ERP"
    })
    assert r_int.status_code == 200, r_int.text
    int_data = r_int.json()
    assert int_data["status"] == "INTERESTED"

    # Verifiche di sicurezza logica: NON deve essere APPROVED
    quote_state = main.store.get(qid)
    assert quote_state["status"] == "INTERESTED"
    assert quote_state["status"] != "APPROVED"

    lifecycle = main.store.lifecycle(qid)
    assert lifecycle["state"] == "PROPOSAL_INTERESTED"

    events = [e["event_type"] for e in main.store.events(qid)]
    assert "PROPOSAL_INTERESTED" in events
    assert "QUOTE_APPROVED" not in events


def test_calcom_booking_and_cancellation(tmp_path):
    c = client_with_tmp_db(tmp_path)
    payload = {
        "customer": {"business_name": "Azienda Beta", "email": "beta@example.com"},
        "project_name": "Sito Web Exclusive",
        "items": [{"code": "WEB_EXCLUSIVE", "quantity": 1}],
    }
    qid = c.post("/api/v1/quotes", json=payload).json()["quote_id"]

    # 1. Booking creato via webhook Cal.com
    r_booked = c.post(f"/api/v1/quotes/{qid}/call-booked", json={
        "external_booking_id": "cal_book_999",
        "booking_url": "https://cal.com/booking/cal_book_999",
        "scheduled_at": "2026-10-05T10:00:00Z"
    })
    assert r_booked.status_code == 200
    assert r_booked.json()["lifecycle"]["state"] == "CALL_BOOKED"

    # 2. Booking cancellato
    r_cancel = c.post(f"/api/v1/quotes/{qid}/call-cancelled", json={
        "external_booking_id": "cal_book_999",
        "cancellation_reason": "Richiesta ripianificazione dal prospect"
    })
    assert r_cancel.status_code == 200
    assert r_cancel.json()["lifecycle"]["state"] == "CALL_CANCELLED"


def test_email_status_tracking(tmp_path):
    c = client_with_tmp_db(tmp_path)
    payload = {
        "customer": {"business_name": "Alpha SRL", "email": "alpha@example.com"},
        "project_name": "Sito Web",
        "items": [{"code": "WEB_BASE_5", "quantity": 1}],
    }
    qid = c.post("/api/v1/quotes", json=payload).json()["quote_id"]

    # Registra fallimento invio email iniziale
    r_fail = c.post(f"/api/v1/quotes/{qid}/email-status", json={
        "status": "FAILED",
        "provider": "smtp",
        "error_code": "CONNECTION_TIMEOUT"
    })
    assert r_fail.status_code == 200
    events = [e["event_type"] for e in main.store.events(qid)]
    assert "QUOTE_EMAIL_FAILED" in events

    # Retry riuscito: registra invio avvenuto
    r_sent = c.post(f"/api/v1/quotes/{qid}/email-status", json={
        "status": "SENT",
        "provider": "smtp",
        "message_id": "msg-xyz-12345"
    })
    assert r_sent.status_code == 200
    events = [e["event_type"] for e in main.store.events(qid)]
    assert "QUOTE_EMAIL_SENT" in events


def test_hmac_security(tmp_path, monkeypatch):
    c = client_with_tmp_db(tmp_path)
    secret = "super-secret-hmac-key"
    monkeypatch.setattr(main, "HMAC_SECRET", secret)

    payload = {
        "customer": {"business_name": "Security Test SRL", "email": "sec@test.it"},
        "project_name": "Test HMAC",
        "items": [{"code": "WEB_BASE_5", "quantity": 1}],
    }
    raw_body = json.dumps(payload).encode("utf-8")

    # 1. Richiesta non firmata: DEVE FALLIRE con 401
    r_unauth = c.post("/api/v1/quotes", json=payload)
    assert r_unauth.status_code == 401

    # 2. Richiesta con firma errata: DEVE FALLIRE con 401
    now_ts = str(int(time.time()))
    r_bad_sig = c.post(
        "/api/v1/quotes",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Timestamp": now_ts,
            "X-Signature": "sha256=invalid-signature",
        },
    )
    assert r_bad_sig.status_code == 401

    # 3. Richiesta con firma valida: DEVE AVERE SUCCESSO 200
    sig = hmac.new(secret.encode("utf-8"), f"{now_ts}.".encode("utf-8") + raw_body, hashlib.sha256).hexdigest()
    r_valid = c.post(
        "/api/v1/quotes",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Timestamp": now_ts,
            "X-Signature": f"sha256={sig}",
        },
    )
    assert r_valid.status_code == 200
