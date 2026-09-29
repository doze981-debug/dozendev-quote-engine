from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
import app.main as main
from app.store import QuoteStore


def client_with_tmp_db(tmp_path):
    main.store = QuoteStore(str(tmp_path / 'quotes.db'))
    main.HMAC_SECRET = ''
    return TestClient(app)


def create_payload():
    return {
        'customer': {
            'business_name': 'ACME SRL',
            'vat_number': 'IT00000000000',
            'address': 'Via Test 1, Torino',
            'contact_name': 'Mario Rossi',
            'email': 'mario@example.com'
        },
        'project_name': 'Nuovo sito corporate',
        'project_type': 'web',
        'items': [
            {'code': 'WEB_BASE_5', 'quantity': 1},
            {'code': 'AUTO_CONTENT', 'quantity': 1}
        ],
        'discount': {'amount': 300, 'reason': 'test'},
        'valid_days': 14,
        'delivery_weeks': '3-4 settimane',
        'acceptance_criteria': ['Sito disponibile in staging', 'Form contatto operativo'],
        'exclusions': ['Produzione contenuti non inclusa']
    }


def test_full_quote_to_project_flow(tmp_path, monkeypatch):
    monkeypatch.setenv('DOZENDEV_LEGAL_DETAILS', 'DozenDev - dati legali test')
    monkeypatch.setenv('DOZENDEV_PEC', 'dozendev@example.pec.it')
    monkeypatch.setenv('DOZENDEV_FORUM', 'Torino')
    c = client_with_tmp_db(tmp_path)

    r = c.post('/api/v1/quotes', json=create_payload())
    assert r.status_code == 200, r.text
    created = r.json()
    qid = created['quote_id']
    token = created['public_token']
    assert Decimal(created['totals']['net_total']) == Decimal('2000.00')

    r = c.get(f'/api/v1/public/{token}')
    assert r.status_code == 200
    assert r.json()['quote']['status'] == 'VIEWED'

    r = c.post(f'/api/v1/public/{token}/configure', json={'selected_optional_codes': ['CMS_BLOG', 'AUTO_CONTENT']})
    assert r.status_code == 200, r.text
    assert r.json()['version'] == 2
    assert Decimal(r.json()['totals']['net_total']) == Decimal('2350.00')  # original 300 EUR discount preserved

    r = c.post(f'/api/v1/public/{token}/approve', json={
        'accepted_by': 'Mario Rossi',
        'accepted_email': 'mario@example.com',
        'confirm_business_authority': True
    })
    assert r.status_code == 200, r.text
    assert r.json()['quote']['status'] == 'APPROVED'

    r = c.get(f'/api/v1/quotes/{qid}/contract/pack')
    assert r.status_code == 200
    assert r.json()['ready_for_signature'] is True
    assert r.json()['signature_requirements']['separate_1341_1342_signature'] is True

    r = c.get(f'/api/v1/quotes/{qid}/pdf')
    assert r.status_code == 200 and r.headers['content-type'] == 'application/pdf'
    assert r.content.startswith(b'%PDF')

    r = c.get(f'/api/v1/quotes/{qid}/contract/pdf')
    assert r.status_code == 200 and r.content.startswith(b'%PDF')

    r = c.post(f'/api/v1/quotes/{qid}/contract/provider-created', json={
        'provider': 'generic', 'external_envelope_id': 'env_123', 'signing_url': 'https://sign.local/env_123'
    })
    assert r.status_code == 200
    assert r.json()['lifecycle']['state'] == 'CONTRACT_SENT'

    r = c.post(f'/api/v1/quotes/{qid}/contract/signed', json={
        'provider': 'generic', 'external_envelope_id': 'env_123', 'signed_document_url': 'https://sign.local/signed.pdf',
        'general_signature_completed': True, 'specific_1341_1342_completed': True
    })
    assert r.status_code == 200
    assert r.json()['lifecycle']['state'] == 'CONTRACT_SIGNED'

    r = c.post(f'/api/v1/quotes/{qid}/deposit/provider-created', json={
        'provider': 'generic', 'external_payment_id': 'pay_123', 'checkout_url': 'https://pay.local/pay_123'
    })
    assert r.status_code == 200
    assert r.json()['lifecycle']['state'] == 'DEPOSIT_PENDING'

    r = c.post(f'/api/v1/quotes/{qid}/deposit/paid', json={
        'provider': 'generic', 'external_payment_id': 'pay_123'
    })
    assert r.status_code == 200
    life = r.json()['lifecycle']
    assert life['state'] == 'ONBOARDING'
    checklist = life['onboarding']['checklist']
    for item in checklist:
        if item['required']:
            item['completed'] = True
            item['value'] = 'ok'

    r = c.put(f'/api/v1/quotes/{qid}/onboarding/checklist', json={'items': checklist})
    assert r.status_code == 200
    assert r.json()['lifecycle']['state'] == 'PROJECT_READY'

    events = c.get(f'/api/v1/quotes/{qid}/events').json()
    names = [e['event_type'] for e in events]
    for required in ['QUOTE_CREATED','QUOTE_VIEWED','QUOTE_REVISED','QUOTE_APPROVED','CONTRACT_SENT','CONTRACT_SIGNED','DEPOSIT_PENDING','DEPOSIT_PAID','ONBOARDING_UPDATED']:
        assert required in names


def test_cannot_modify_after_approval(tmp_path):
    c = client_with_tmp_db(tmp_path)
    created = c.post('/api/v1/quotes', json=create_payload()).json()
    token = created['public_token']
    c.post(f'/api/v1/public/{token}/approve', json={
        'accepted_by': 'Mario Rossi', 'accepted_email': 'mario@example.com', 'confirm_business_authority': True
    })
    r = c.post(f'/api/v1/public/{token}/configure', json={'selected_optional_codes': ['CMS_BLOG']})
    assert r.status_code == 409
