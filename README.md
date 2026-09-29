# DozenDev Quote-to-Project Engine 0.4

Piattaforma di generazione, gestione preventivi e ciclo di vita progetto per DozenDev:

```text
lead web (Next.js) -> n8n orchestrator -> Quote Engine (idempotente) -> Proposta Commerciale (PDF + URL)
-> Prospect Interessato -> Cal.com Discovery Call -> Approvazione/Freeze -> Contratto + Allegato A -> Onboarding
```

## Novità Versione 0.4.0

- **Integrazione Inbound Lead Web**: endpoint `POST /api/v1/quotes` esteso per supportare `external_lead_id` e metadati di provenienza.
- **Idempotenza Garantita**: l'invio ripetuto dello stesso `external_lead_id` restituisce il preventivo esistente e lo stesso link pubblico con flag `idempotent: true`, impedendo la duplicazione di preventivi per lo stesso prospect.
- **Nuovi Servizi a Listino**:
  - `WEB_BASE_5` + sconto `PIEMONTE30` (-30%) = **€ 1.260 + IVA** (Pacchetto STARTUP Promo PMI)
  - `WEB_PREMIUM` = **€ 3.500 + IVA** (Pacchetto PREMIUM E-commerce/Headless)
  - `WEB_EXCLUSIVE` = **€ 5.000 + IVA** (Pacchetto EXCLUSIVE Enterprise/Web App)
  - Gestione `needsAutomation`: le automazioni richieste vengono conservate come note di qualifica per la call, senza ricarichi forfettari automatici a listino.
- **Transizione Pubblica "Mi interessa / fissiamo una call"**:
  - Endpoint: `POST /api/v1/public/{token}/interest` (e `POST /api/v1/quotes/{id}/interest`)
  - Emette l'evento `PROPOSAL_INTERESTED`
  - Separa nettamente l'interesse iniziale dalla conferma contrattuale `QUOTE_APPROVED`.
- **Integrazione Cal.com**:
  - Endpoint `POST /api/v1/quotes/{id}/call-booked` -> imposta stato lifecycle su `CALL_BOOKED`
  - Endpoint `POST /api/v1/quotes/{id}/call-cancelled` -> imposta stato lifecycle su `CALL_CANCELLED`
- **Sicurezza HMAC-SHA256**:
  - Verifica automatica degli header `X-Signature` (`sha256=...`) e `X-Timestamp` (protezione anti-replay window 300s).
  - Configurabile via variabile ambiente `QUOTE_ENGINE_HMAC_SECRET`.
- **Tracciamento Invio Email Transazionali**:
  - Endpoint `POST /api/v1/quotes/{id}/email-status` per registrare `QUOTE_EMAIL_SENT` o `QUOTE_EMAIL_FAILED` senza loggare dati sensibili o credenziali.

---

## Tabella di Mapping: Lead Web → Preventivo

| Pacchetto Selezionato | Servizio Listino Quote Engine | Sconto Applicato | Prezzo Netto (+ IVA) | Deliverables Inclusi |
| :--- | :--- | :--- | :--- | :--- |
| **STARTUP** | `WEB_BASE_5` | `PIEMONTE30` (-30%) | **€ 1.260,00** | 4-5 pagine responsive, SEO Base + Tecnica, Performance Pack 90+, Blog CMS autonomo a €0, 100% codice proprietario |
| **PREMIUM** | `WEB_PREMIUM` | *Nessuno* | **€ 3.500,00** | Tutto ciò che include STARTUP + SEO Avanzata, cache dinamica, E-commerce starter (Stripe/PayPal), Webhook CRM |
| **EXCLUSIVE** | `WEB_EXCLUSIVE` | *Nessuno* | **€ 5.000,00** | Tutto ciò che include PREMIUM + Architettura enterprise distribuita, PostgreSQL dedicato, Area riservata protetta, Dashboard metriche real-time, Integrazioni ERP |

---

## Workflows n8n

I workflow JSON si trovano nella cartella `n8n/`:

1. `n8n-workflow-dozendev-leads.json` (nel repo principale): workflow centrale di smistamento lead; inoltra in parallelo i pacchetti web a Quote Automation.
2. `03-quote-automation.workflow.json`:
   - Riceve il lead normalizzato.
   - Chiama Quote Engine con firma HMAC e `external_lead_id`.
   - Scarica il PDF del preventivo.
   - Salva riga su Google Sheets (foglio `Proposte-Preventivi`).
   - Invia email transazionale con link pubblico e PDF allegato.
3. `04-proposal-interest-calcom.workflow.json`:
   - Riceve `PROPOSAL_INTERESTED` da Quote Engine e invia al prospect l'invito con link Cal.com.
   - Riceve il webhook di Cal.com (`BOOKING_CREATED` / `BOOKING_CANCELLED`) e aggiorna Quote Engine in `CALL_BOOKED` o `CALL_CANCELLED`.

---

## Configurazione Variabili Ambiente

Configura nel file `.env`:

```ini
# Quote Engine
QUOTE_DB_PATH=/app/data/quotes.db
QUOTE_PUBLIC_BASE_URL=http://localhost:8010/proposta
INTERNAL_BASE_URL=http://localhost:8010
QUOTE_ENGINE_HOST_PORT=8010

# Security HMAC (condiviso con Next.js e n8n)
QUOTE_ENGINE_HMAC_SECRET=dozendev-secret-lead-key-2026

# n8n Webhook Bus
N8N_EVENT_WEBHOOK_URL=http://n8n:5678/webhook/dozendev-events
N8N_PROPOSAL_INTERESTED_WEBHOOK_URL=http://n8n:5678/webhook/dozendev-proposal-interest
```

## Esecuzione Test

Esegui la suite completa con Docker:

```bash
docker exec dozendev-quote-engine-quote-engine-1 pytest -v
```

Oppure in locale:

```bash
pytest -v
```
