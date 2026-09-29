# n8n integration

The Quote Engine is the source of truth. n8n orchestrates external actions and must not calculate prices.

## Import
Import `01-event-router.workflow.json` and `02-provider-callbacks.workflow.json` into n8n.
Activate `DozenDev - Event Router`, then set:

`N8N_EVENT_WEBHOOK_URL=http://n8n:5678/webhook/dozendev-events`

## Events emitted by the engine

- `QUOTE_SENT` -> email/CRM delivery of proposal link
- `QUOTE_APPROVED` -> create the signature envelope using `/contract/pack` and `/contract/pdf`
- `CONTRACT_SENT` -> wait for provider signature callback
- `CONTRACT_SIGNED` -> create deposit checkout/payment request
- `DEPOSIT_PENDING` -> wait for payment callback
- `ONBOARDING_STARTED` -> send checklist/portal link
- `ONBOARDING_UPDATED` -> sync CRM/project tracker
- `PROJECT_READY` -> create the real project/workspace and kickoff tasks

## Provider callback contract
Provider-specific workflows normalize their callbacks and POST to the `dozendev-provider-callback` workflow:

```json
{
  "quote_id": "UUID",
  "kind": "contract_signed",
  "payload": {
    "provider": "your-provider",
    "external_envelope_id": "...",
    "signed_document_url": "...",
    "audit_trail_url": "..."
  }
}
```

Supported `kind`: `contract_created`, `contract_signed`, `deposit_created`, `deposit_paid`.

The skeleton intentionally does not contain provider credentials or pretend a DocuSign/Dropbox Sign/Stripe integration is configured. Add those provider nodes after verification.
