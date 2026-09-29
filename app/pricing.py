from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .schemas import DiscountRequest, QuoteItem, QuoteItemRequest, QuoteTotals

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PriceList:
    version: str
    vat_rate: Decimal
    services: dict[str, dict]
    discount_rules: dict[str, dict]

    @classmethod
    def load(cls, path: str | Path) -> "PriceList":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        services = {s["code"]: s for s in raw["services"] if s.get("active", True)}
        discounts = {d["code"]: d for d in raw.get("discount_rules", []) if d.get("active", True)}
        return cls(
            version=raw["version"],
            vat_rate=Decimal(str(raw.get("vat_rate", 22))),
            services=services,
            discount_rules=discounts,
        )

    def resolve_items(self, requested: list[QuoteItemRequest]) -> list[QuoteItem]:
        out: list[QuoteItem] = []
        for req in requested:
            service = self.services.get(req.code)
            if not service:
                raise ValueError(f"Unknown or inactive service code: {req.code}")
            qty = Decimal(req.quantity)
            unit = money(Decimal(str(service["unit_price"])))
            out.append(
                QuoteItem(
                    code=req.code,
                    name=service["name"],
                    description=service.get("client_description", service["name"]),
                    quantity=qty,
                    unit_price=unit,
                    total=money(unit * qty),
                    taxable=service.get("taxable", True),
                    contract_tags=service.get("contract_tags", []),
                    customer_configurable=service.get("customer_configurable", False),
                )
            )
        return out

    def calculate(self, items: list[QuoteItem], discount: DiscountRequest | None) -> QuoteTotals:
        subtotal = money(sum((i.total for i in items), Decimal("0")))
        discount_amount = Decimal("0")

        if discount:
            if discount.code:
                rule = self.discount_rules.get(discount.code)
                if not rule:
                    raise ValueError(f"Unknown discount code: {discount.code}")
                if rule["type"] == "percent":
                    discount_amount = subtotal * Decimal(str(rule["value"])) / Decimal("100")
                elif rule["type"] == "fixed":
                    discount_amount = Decimal(str(rule["value"]))
                else:
                    raise ValueError("Unsupported discount rule type")
            elif discount.percent is not None:
                discount_amount = subtotal * Decimal(discount.percent) / Decimal("100")
            elif discount.amount is not None:
                discount_amount = Decimal(discount.amount)

        discount_amount = min(money(discount_amount), subtotal)
        net = money(subtotal - discount_amount)
        vat = money(net * self.vat_rate / Decimal("100"))
        gross = money(net + vat)
        return QuoteTotals(
            subtotal=subtotal,
            discount=discount_amount,
            net_total=net,
            vat_rate=self.vat_rate,
            vat_amount=vat,
            gross_total=gross,
        )
