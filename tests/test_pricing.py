from decimal import Decimal
from pathlib import Path

from app.pricing import PriceList
from app.schemas import DiscountRequest, QuoteItemRequest


def test_price_and_discount():
    root = Path(__file__).resolve().parent.parent
    p = PriceList.load(root / "data" / "pricelist.json")
    items = p.resolve_items([
        QuoteItemRequest(code="WEB_BASE_5", quantity=1),
        QuoteItemRequest(code="AUTO_CONTENT", quantity=1),
    ])
    totals = p.calculate(items, DiscountRequest(amount=Decimal("300")))
    assert totals.subtotal == Decimal("2300.00")
    assert totals.discount == Decimal("300.00")
    assert totals.net_total == Decimal("2000.00")
    assert totals.vat_amount == Decimal("440.00")
    assert totals.gross_total == Decimal("2440.00")


def test_catalog_discount():
    root = Path(__file__).resolve().parent.parent
    p = PriceList.load(root / "data" / "pricelist.json")
    items = p.resolve_items([QuoteItemRequest(code="WEB_BASE_5", quantity=1)])
    totals = p.calculate(items, DiscountRequest(code="PIEMONTE30"))
    assert totals.net_total == Decimal("1260.00")
