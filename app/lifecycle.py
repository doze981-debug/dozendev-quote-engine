from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def first_installment(quote: dict) -> dict:
    net = Decimal(str(quote["totals"]["net_total"]))
    payment_plan = quote.get("payment_plan") or {
        "type": "50_50",
        "installments": [
            {"label": "Acconto all'avvio", "percent": 50, "amount": str((net * Decimal("0.5")).quantize(Decimal("0.01")))},
            {"label": "Saldo prima del go-live/consegna", "percent": 50, "amount": str((net * Decimal("0.5")).quantize(Decimal("0.01")))},
        ],
    }
    return payment_plan["installments"][0]


def default_checklist(quote: dict) -> list[dict]:
    tags = {tag for item in quote["items"] for tag in item.get("contract_tags", [])}
    items = [
        {"code": "LEGAL_NAME", "label": "Ragione sociale e dati fiscali confermati", "required": True, "completed": False, "value": None},
        {"code": "REFERENT", "label": "Referente operativo confermato", "required": True, "completed": False, "value": None},
        {"code": "CONTENT", "label": "Testi, immagini e materiali disponibili", "required": True, "completed": False, "value": None},
        {"code": "DOMAIN_HOSTING", "label": "Dominio/hosting e relativi accessi disponibili", "required": quote.get("project_type") == "web", "completed": False, "value": None},
        {"code": "TECH_ACCESS", "label": "Accessi tecnici necessari disponibili", "required": True, "completed": False, "value": None},
    ]
    if "DPA" in tags:
        items.append({"code": "PRIVACY_INPUTS", "label": "Informazioni privacy/DPA raccolte", "required": True, "completed": False, "value": None})
    if "AI" in tags:
        items.append({"code": "AI_INPUTS", "label": "Provider, dati e vincoli AI confermati", "required": True, "completed": False, "value": None})
    if "THIRD_PARTY" in tags:
        items.append({"code": "THIRD_PARTY", "label": "Account/licenze di terze parti confermati", "required": True, "completed": False, "value": None})
    return items


def checklist_complete(items: list[dict]) -> bool:
    return all(i.get("completed") for i in items if i.get("required", True))
