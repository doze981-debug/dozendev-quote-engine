# API map

## Quote

- `GET /api/v1/pricelist`
- `POST /api/v1/quotes`
- `GET /api/v1/quotes`
- `GET /api/v1/quotes/{quote_id}`
- `GET /api/v1/quotes/{quote_id}/versions`
- `GET /api/v1/quotes/{quote_id}/events`
- `POST /api/v1/quotes/{quote_id}/public-token`
- `POST /api/v1/quotes/{quote_id}/send`
- `POST /api/v1/quotes/{quote_id}/revisions`
- `GET /api/v1/quotes/{quote_id}/pdf`
- `POST /api/v1/quotes/{quote_id}/approve`

## Customer proposal

- `GET /proposta/{token}` - customer HTML UI
- `GET /api/v1/public/{token}`
- `POST /api/v1/public/{token}/configure`
- `POST /api/v1/public/{token}/approve`

## Contract

- `GET /api/v1/quotes/{quote_id}/contract-handoff`
- `GET /api/v1/quotes/{quote_id}/contract/pack`
- `GET /api/v1/quotes/{quote_id}/contract/pdf`
- `POST /api/v1/quotes/{quote_id}/contract/provider-created`
- `POST /api/v1/quotes/{quote_id}/contract/signed`

`contract/signed` accepts the provider-normalized evidence and requires both:

```json
{
  "general_signature_completed": true,
  "specific_1341_1342_completed": true
}
```

## Deposit

- `POST /api/v1/quotes/{quote_id}/deposit/provider-created`
- `POST /api/v1/quotes/{quote_id}/deposit/paid`

The engine rejects an explicitly supplied paid amount lower than the required deposit.

## Onboarding / lifecycle

- `GET /api/v1/quotes/{quote_id}/lifecycle`
- `PUT /api/v1/quotes/{quote_id}/onboarding/checklist`

When every required checklist item is complete, state becomes `PROJECT_READY` and the engine emits the corresponding n8n event.
