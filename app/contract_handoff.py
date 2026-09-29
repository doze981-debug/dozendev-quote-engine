from __future__ import annotations

from datetime import datetime
from decimal import Decimal


def d(value):
    if isinstance(value, Decimal):
        return str(value)
    return value


def build_contract_handoff(quote: dict) -> dict:
    tags = sorted({tag for item in quote["items"] for tag in item.get("contract_tags", [])})
    totals = quote["totals"]
    net = Decimal(str(totals["net_total"]))

    # Default coerente col Contract Master: 50/50 piccoli progetti.
    # La soglia e il piano possono essere sostituiti dal pricing/configuratore.
    payment_plan = quote.get("payment_plan") or {
        "type": "50_50",
        "installments": [
            {"label": "Acconto all'avvio", "percent": 50, "amount": str((net * Decimal('0.5')).quantize(Decimal('0.01')))},
            {"label": "Saldo prima del go-live/consegna", "percent": 50, "amount": str((net * Decimal('0.5')).quantize(Decimal('0.01')))},
        ],
    }

    return {
        "event": "QUOTE_APPROVED",
        "customer_id": quote["customer"].get("id"),
        "quote_id": quote["quote_id"],
        "quote_number": quote["quote_number"],
        "quote_version": quote["version"],
        "pricelist_version": quote["pricelist_version"],
        "approved_at": quote["approved_at"],
        "customer": quote["customer"],
        "project": {
            "name": quote["project_name"],
            "type": quote["project_type"],
            "notes": quote.get("notes"),
        },
        "economics": {
            **totals,
            "currency": "EUR",
            "prices_exclude_vat": True,
            "payment_plan": payment_plan,
        },
        "annex_a": {
            "source_quote": f"{quote['quote_number']}-v{quote['version']}",
            "scope": [
                {
                    "code": i["code"],
                    "name": i["name"],
                    "description": i["description"],
                    "quantity": i["quantity"],
                    "unit_price": i["unit_price"],
                    "total": i["total"],
                }
                for i in quote["items"]
            ],
            "deliverables": [i["name"] for i in quote["items"]],
            "economic_conditions": totals,
            "acceptance_criteria": quote.get("acceptance_criteria", []),
            "exclusions": quote.get("exclusions", []),
        },
        "contract_flags": {
            "requires_dpa": "DPA" in tags,
            "requires_ai_addendum": "AI" in tags,
            "requires_sla": "SLA" in tags,
            "requires_newsletter_tracking_annex": "NEWSLETTER_TRACKING" in tags,
            "requires_third_party_schedule": "THIRD_PARTY" in tags,
            "legal_review_required": False,
        },
        "audit": quote.get("approval_audit", {}),
    }
