from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class QuoteStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("QUOTE_DB_PATH", "./data/quotes.db")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init(self):
        with self.connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS quote_heads (
                    quote_id TEXT PRIMARY KEY,
                    quote_number TEXT NOT NULL UNIQUE,
                    current_version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approved_at TEXT,
                    approval_audit_json TEXT,
                    external_lead_id TEXT,
                    source TEXT,
                    source_data_json TEXT
                );
                CREATE TABLE IF NOT EXISTS quote_versions (
                    quote_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    frozen INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (quote_id, version)
                );
                CREATE TABLE IF NOT EXISTS quote_public_tokens (
                    quote_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    token TEXT
                );
                CREATE TABLE IF NOT EXISTS quote_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    quote_id TEXT NOT NULL,
                    version INTEGER,
                    event_type TEXT NOT NULL,
                    actor TEXT,
                    payload_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_lifecycle (
                    quote_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    contract_json TEXT NOT NULL DEFAULT '{}',
                    payment_json TEXT NOT NULL DEFAULT '{}',
                    onboarding_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_quote_number ON quote_heads(quote_number);
                CREATE INDEX IF NOT EXISTS idx_quote_events ON quote_events(quote_id, created_at);
                """
            )
            # Safe schema migrations for existing databases
            for col, ddl in [
                ("external_lead_id", "ALTER TABLE quote_heads ADD COLUMN external_lead_id TEXT"),
                ("source", "ALTER TABLE quote_heads ADD COLUMN source TEXT"),
                ("source_data_json", "ALTER TABLE quote_heads ADD COLUMN source_data_json TEXT"),
            ]:
                try:
                    con.execute(ddl)
                except Exception:
                    pass
            try:
                con.execute("ALTER TABLE quote_public_tokens ADD COLUMN token TEXT")
            except Exception:
                pass
            try:
                con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_quote_external_lead_id ON quote_heads(external_lead_id) WHERE external_lead_id IS NOT NULL")
            except Exception:
                pass

    def next_number(self) -> str:
        year = datetime.now(timezone.utc).year
        prefix = f"Q-{year}-"
        with self.connect() as con:
            row = con.execute(
                "SELECT quote_number FROM quote_heads WHERE quote_number LIKE ? ORDER BY quote_number DESC LIMIT 1",
                (prefix + "%",),
            ).fetchone()
        seq = int(row["quote_number"].split("-")[-1]) + 1 if row else 1
        return f"{prefix}{seq:04d}"

    def _event(self, con, quote_id: str, version: int | None, event_type: str, actor: str | None = None, payload: dict | None = None):
        con.execute(
            "INSERT INTO quote_events(quote_id, version, event_type, actor, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (quote_id, version, event_type, actor, json.dumps(payload or {}, ensure_ascii=False), utcnow()),
        )

    def create(self, snapshot: dict) -> tuple[dict, str]:
        ext_id = snapshot.get("external_lead_id")
        if ext_id:
            with self.connect() as con:
                row = con.execute("SELECT quote_id FROM quote_heads WHERE external_lead_id = ?", (ext_id,)).fetchone()
                if row:
                    qid = row["quote_id"]
                    existing_quote = self.get(qid)
                    tok_row = con.execute("SELECT token FROM quote_public_tokens WHERE quote_id = ? AND revoked_at IS NULL", (qid,)).fetchone()
                    if tok_row and tok_row["token"]:
                        token = tok_row["token"]
                    else:
                        token = secrets.token_urlsafe(32)
                        con.execute("UPDATE quote_public_tokens SET token = ?, token_hash = ? WHERE quote_id = ?", (token, token_hash(token), qid))
                    self._event(con, qid, existing_quote.get("version", 1) if existing_quote else 1, "QUOTE_IDEMPOTENT_HIT", "internal", {"external_lead_id": ext_id})
                    existing_copy = dict(existing_quote) if existing_quote else {}
                    existing_copy["idempotent"] = True
                    return existing_copy, token

        quote_id = str(uuid4())
        number = self.next_number()
        now = utcnow()
        token = secrets.token_urlsafe(32)
        snapshot = {**snapshot, "quote_id": quote_id, "quote_number": number, "version": 1, "created_at": now}
        with self.connect() as con:
            con.execute(
                "INSERT INTO quote_heads VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)",
                (
                    quote_id,
                    number,
                    1,
                    snapshot["status"],
                    now,
                    now,
                    snapshot.get("external_lead_id"),
                    snapshot.get("source"),
                    json.dumps(snapshot.get("source_data") or {}, ensure_ascii=False),
                ),
            )
            con.execute(
                "INSERT INTO quote_versions VALUES (?, ?, ?, ?, 0)",
                (quote_id, 1, json.dumps(snapshot, ensure_ascii=False), now),
            )
            con.execute(
                "INSERT INTO quote_public_tokens VALUES (?, ?, ?, NULL, ?)",
                (quote_id, token_hash(token), now, token),
            )
            self._event(con, quote_id, 1, "QUOTE_CREATED", "internal")
        return snapshot, token

    def list_quotes(self, limit: int = 100) -> list[dict]:
        with self.connect() as con:
            rows = con.execute("SELECT quote_id FROM quote_heads ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [q for r in rows if (q := self.get(r["quote_id"]))]

    def get(self, quote_id: str) -> dict | None:
        with self.connect() as con:
            head = con.execute("SELECT * FROM quote_heads WHERE quote_id=?", (quote_id,)).fetchone()
            if not head:
                return None
            ver = con.execute(
                "SELECT snapshot_json FROM quote_versions WHERE quote_id=? AND version=?",
                (quote_id, head["current_version"]),
            ).fetchone()
        return json.loads(ver["snapshot_json"])

    def get_version(self, quote_id: str, version: int) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT snapshot_json FROM quote_versions WHERE quote_id=? AND version=?", (quote_id, version)).fetchone()
        return json.loads(row["snapshot_json"]) if row else None

    def versions(self, quote_id: str) -> list[dict]:
        with self.connect() as con:
            rows = con.execute("SELECT version, created_at, frozen, snapshot_json FROM quote_versions WHERE quote_id=? ORDER BY version", (quote_id,)).fetchall()
        return [{"version": r["version"], "created_at": r["created_at"], "frozen": bool(r["frozen"]), "snapshot": json.loads(r["snapshot_json"])} for r in rows]

    def get_by_public_token(self, token: str, mark_viewed: bool = False) -> dict | None:
        th = token_hash(token)
        with self.connect() as con:
            row = con.execute("SELECT quote_id FROM quote_public_tokens WHERE token_hash=? AND revoked_at IS NULL", (th,)).fetchone()
            if not row:
                return None
            quote_id = row["quote_id"]
            if mark_viewed:
                head = con.execute("SELECT status, current_version FROM quote_heads WHERE quote_id=?", (quote_id,)).fetchone()
                if head and head["status"] in {"DRAFT", "SENT"}:
                    con.execute("UPDATE quote_heads SET status='VIEWED', updated_at=? WHERE quote_id=?", (utcnow(), quote_id))
                    ver = con.execute("SELECT snapshot_json FROM quote_versions WHERE quote_id=? AND version=?", (quote_id, head["current_version"])).fetchone()
                    snap = json.loads(ver["snapshot_json"])
                    snap["status"] = "VIEWED"
                    con.execute("UPDATE quote_versions SET snapshot_json=? WHERE quote_id=? AND version=?", (json.dumps(snap, ensure_ascii=False), quote_id, head["current_version"]))
                    self._event(con, quote_id, head["current_version"], "QUOTE_VIEWED", "customer")
        return self.get(quote_id)

    def rotate_public_token(self, quote_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = utcnow()
        with self.connect() as con:
            head = con.execute("SELECT current_version FROM quote_heads WHERE quote_id=?", (quote_id,)).fetchone()
            if not head:
                raise KeyError(quote_id)
            con.execute("UPDATE quote_public_tokens SET token_hash=?, created_at=?, revoked_at=NULL, token=? WHERE quote_id=?", (token_hash(token), now, token, quote_id))
            self._event(con, quote_id, head["current_version"], "PUBLIC_LINK_ROTATED", "internal")
        return token

    def mark_sent(self, quote_id: str) -> dict:
        with self.connect() as con:
            head = con.execute("SELECT * FROM quote_heads WHERE quote_id=?", (quote_id,)).fetchone()
            if not head:
                raise KeyError(quote_id)
            if head["status"] == "APPROVED":
                raise ValueError("Approved quote is frozen")
            ver = con.execute("SELECT snapshot_json FROM quote_versions WHERE quote_id=? AND version=?", (quote_id, head["current_version"])).fetchone()
            snap = json.loads(ver["snapshot_json"])
            snap["status"] = "SENT"
            now = utcnow()
            con.execute("UPDATE quote_versions SET snapshot_json=? WHERE quote_id=? AND version=?", (json.dumps(snap, ensure_ascii=False), quote_id, head["current_version"]))
            con.execute("UPDATE quote_heads SET status='SENT', updated_at=? WHERE quote_id=?", (now, quote_id))
            self._event(con, quote_id, head["current_version"], "QUOTE_SENT", "internal")
        return snap

    def revise(self, quote_id: str, snapshot: dict, actor: str = "internal", reason: str | None = None) -> dict:
        with self.connect() as con:
            head = con.execute("SELECT * FROM quote_heads WHERE quote_id=?", (quote_id,)).fetchone()
            if not head:
                raise KeyError(quote_id)
            if head["status"] == "APPROVED":
                raise ValueError("Approved quote is frozen and cannot be revised")
            new_version = head["current_version"] + 1
            now = utcnow()
            snapshot = {**snapshot, "quote_id": quote_id, "quote_number": head["quote_number"], "version": new_version, "created_at": now, "status": "MODIFIED"}
            con.execute("INSERT INTO quote_versions VALUES (?, ?, ?, ?, 0)", (quote_id, new_version, json.dumps(snapshot, ensure_ascii=False), now))
            con.execute("UPDATE quote_heads SET current_version=?, status='MODIFIED', updated_at=? WHERE quote_id=?", (new_version, now, quote_id))
            self._event(con, quote_id, new_version, "QUOTE_REVISED", actor, {"reason": reason})
        return snapshot

    def approve(self, quote_id: str, audit: dict) -> dict:
        with self.connect() as con:
            head = con.execute("SELECT * FROM quote_heads WHERE quote_id=?", (quote_id,)).fetchone()
            if not head:
                raise KeyError(quote_id)
            if head["status"] == "APPROVED":
                ver = con.execute("SELECT snapshot_json FROM quote_versions WHERE quote_id=? AND version=?", (quote_id, head["current_version"])).fetchone()
                return json.loads(ver["snapshot_json"])
            if head["status"] not in {"DRAFT", "SENT", "VIEWED", "MODIFIED", "INTERESTED"}:
                raise ValueError(f"Quote cannot be approved from status {head['status']}")
            now = utcnow()
            row = con.execute("SELECT snapshot_json FROM quote_versions WHERE quote_id=? AND version=?", (quote_id, head["current_version"])).fetchone()
            snap = json.loads(row["snapshot_json"])
            snap["status"] = "APPROVED"
            snap["approved_at"] = now
            snap["approval_audit"] = audit
            con.execute("UPDATE quote_versions SET snapshot_json=?, frozen=1 WHERE quote_id=? AND version=?", (json.dumps(snap, ensure_ascii=False), quote_id, head["current_version"]))
            con.execute("UPDATE quote_heads SET status='APPROVED', approved_at=?, approval_audit_json=?, updated_at=? WHERE quote_id=?", (now, json.dumps(audit, ensure_ascii=False), now, quote_id))
            con.execute("INSERT OR IGNORE INTO project_lifecycle(quote_id,state,created_at,updated_at) VALUES (?, 'QUOTE_APPROVED', ?, ?)", (quote_id, now, now))
            self._event(con, quote_id, head["current_version"], "QUOTE_APPROVED", "customer", audit)
        return snap

    def mark_interested(self, quote_id: str, audit: dict) -> dict:
        with self.connect() as con:
            head = con.execute("SELECT * FROM quote_heads WHERE quote_id=?", (quote_id,)).fetchone()
            if not head:
                raise KeyError(quote_id)
            now = utcnow()
            row = con.execute("SELECT snapshot_json FROM quote_versions WHERE quote_id=? AND version=?", (quote_id, head["current_version"])).fetchone()
            snap = json.loads(row["snapshot_json"])
            if snap["status"] != "APPROVED":
                snap["status"] = "INTERESTED"
                snap["interested_at"] = now
                snap["interest_audit"] = audit
                con.execute("UPDATE quote_versions SET snapshot_json=? WHERE quote_id=? AND version=?", (json.dumps(snap, ensure_ascii=False), quote_id, head["current_version"]))
                con.execute("UPDATE quote_heads SET status='INTERESTED', updated_at=? WHERE quote_id=?", (now, quote_id))
            self._event(con, quote_id, head["current_version"], "PROPOSAL_INTERESTED", "customer", audit)
        self._set_lifecycle(quote_id, state="PROPOSAL_INTERESTED", event="PROPOSAL_INTERESTED", payload=audit)
        return self.get(quote_id)

    def events(self, quote_id: str) -> list[dict]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM quote_events WHERE quote_id=? ORDER BY id", (quote_id,)).fetchall()
        return [dict(r) | {"payload": json.loads(r["payload_json"] or "{}")} for r in rows]

    def lifecycle(self, quote_id: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM project_lifecycle WHERE quote_id=?", (quote_id,)).fetchone()
        if not row:
            return None
        return {
            "quote_id": quote_id,
            "state": row["state"],
            "contract": json.loads(row["contract_json"] or "{}"),
            "payment": json.loads(row["payment_json"] or "{}"),
            "onboarding": json.loads(row["onboarding_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _set_lifecycle(self, quote_id: str, *, state: str, contract: dict | None = None, payment: dict | None = None, onboarding: dict | None = None, event: str, payload: dict | None = None) -> dict:
        now = utcnow()
        with self.connect() as con:
            row = con.execute("SELECT * FROM project_lifecycle WHERE quote_id=?", (quote_id,)).fetchone()
            if not row:
                con.execute("INSERT INTO project_lifecycle(quote_id,state,created_at,updated_at) VALUES (?,?,?,?)", (quote_id, state, now, now))
                row = con.execute("SELECT * FROM project_lifecycle WHERE quote_id=?", (quote_id,)).fetchone()
            current_contract = json.loads(row["contract_json"] or "{}")
            current_payment = json.loads(row["payment_json"] or "{}")
            current_onboarding = json.loads(row["onboarding_json"] or "{}")
            if contract is not None:
                current_contract.update(contract)
            if payment is not None:
                current_payment.update(payment)
            if onboarding is not None:
                current_onboarding.update(onboarding)
            con.execute(
                "UPDATE project_lifecycle SET state=?, contract_json=?, payment_json=?, onboarding_json=?, updated_at=? WHERE quote_id=?",
                (state, json.dumps(current_contract, ensure_ascii=False), json.dumps(current_payment, ensure_ascii=False), json.dumps(current_onboarding, ensure_ascii=False), now, quote_id),
            )
            head = con.execute("SELECT current_version FROM quote_heads WHERE quote_id=?", (quote_id,)).fetchone()
            self._event(con, quote_id, head["current_version"] if head else None, event, "system", payload or {})
        return self.lifecycle(quote_id)

    def call_booked(self, quote_id: str, data: dict) -> dict:
        return self._set_lifecycle(quote_id, state="CALL_BOOKED", event="CALL_BOOKED", payload=data)

    def call_cancelled(self, quote_id: str, data: dict) -> dict:
        return self._set_lifecycle(quote_id, state="CALL_CANCELLED", event="CALL_CANCELLED", payload=data)

    def record_email_status(self, quote_id: str, data: dict) -> dict:
        event_type = "QUOTE_EMAIL_SENT" if data.get("status") == "SENT" else "QUOTE_EMAIL_FAILED"
        with self.connect() as con:
            head = con.execute("SELECT current_version FROM quote_heads WHERE quote_id=?", (quote_id,)).fetchone()
            safe_payload = {
                "status": data.get("status"),
                "provider": data.get("provider", "smtp"),
                "message_id": data.get("message_id"),
                "error_code": data.get("error_code"),
                "sent_at": data.get("sent_at") or utcnow(),
            }
            self._event(con, quote_id, head["current_version"] if head else None, event_type, "system", safe_payload)
        return self.lifecycle(quote_id) or {"quote_id": quote_id, "email_status": safe_payload}

    def contract_created(self, quote_id: str, data: dict) -> dict:
        return self._set_lifecycle(quote_id, state="CONTRACT_SENT", contract={"status": "SENT", **data}, event="CONTRACT_SENT", payload=data)

    def contract_signed(self, quote_id: str, data: dict) -> dict:
        return self._set_lifecycle(quote_id, state="CONTRACT_SIGNED", contract={"status": "SIGNED", **data}, event="CONTRACT_SIGNED", payload=data)

    def deposit_created(self, quote_id: str, data: dict) -> dict:
        return self._set_lifecycle(quote_id, state="DEPOSIT_PENDING", payment={"status": "PENDING", **data}, event="DEPOSIT_PENDING", payload=data)

    def deposit_paid(self, quote_id: str, data: dict, onboarding: dict) -> dict:
        return self._set_lifecycle(quote_id, state="ONBOARDING", payment={"status": "PAID", **data}, onboarding=onboarding, event="DEPOSIT_PAID", payload=data)

    def update_checklist(self, quote_id: str, items: list[dict], complete: bool) -> dict:
        state = "PROJECT_READY" if complete else "ONBOARDING"
        return self._set_lifecycle(quote_id, state=state, onboarding={"checklist": items, "complete": complete}, event="ONBOARDING_UPDATED", payload={"complete": complete})
