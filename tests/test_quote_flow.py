from decimal import Decimal
from pathlib import Path

from app.pricing import PriceList
from app.schemas import DiscountRequest, QuoteCreateRequest, QuoteItemRequest, Customer
from app.store import QuoteStore


def test_public_versioning_and_freeze(tmp_path):
    pricing = PriceList.load(Path('data/pricelist.json'))
    store = QuoteStore(str(tmp_path / 'quotes.db'))

    payload = QuoteCreateRequest(
        customer=Customer(business_name='ACME SRL', email='a@b.it'),
        project_name='Sito ACME',
        items=[QuoteItemRequest(code='WEB_BASE_5')],
        discount=DiscountRequest(amount=Decimal('300')),
    )
    items = pricing.resolve_items(payload.items)
    totals = pricing.calculate(items, payload.discount)
    snapshot = {
        'status': 'DRAFT',
        'customer': payload.customer.model_dump(),
        'project_name': payload.project_name,
        'project_type': payload.project_type,
        'items': [i.model_dump(mode='json') for i in items],
        'totals': totals.model_dump(mode='json'),
        'discount_config': payload.discount.model_dump(mode='json'),
        'pricelist_version': pricing.version,
        'valid_until': '2099-01-01T00:00:00+00:00',
        'narrative': 'x', 'easy_summary': {}, 'notes': None,
    }
    quote, token = store.create(snapshot)
    assert store.get_by_public_token(token)['version'] == 1

    revised = dict(snapshot)
    revised['items'] = snapshot['items'] + [pricing.resolve_items([QuoteItemRequest(code='CMS_BLOG')])[0].model_dump(mode='json')]
    revised_quote = store.revise(quote['quote_id'], revised, actor='customer')
    assert revised_quote['version'] == 2

    approved = store.approve(quote['quote_id'], {'accepted_by':'Mario','accepted_email':'m@x.it'})
    assert approved['status'] == 'APPROVED'

    try:
        store.revise(quote['quote_id'], revised, actor='customer')
        assert False, 'revision should fail after approval'
    except ValueError:
        pass
