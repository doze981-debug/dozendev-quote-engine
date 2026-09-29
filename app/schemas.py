from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field


class Customer(BaseModel):
    id: str | None = None
    business_name: str
    vat_number: str | None = None
    tax_code: str | None = None
    address: str | None = None
    contact_name: str | None = None
    email: str
    pec: str | None = None


class QuoteItemRequest(BaseModel):
    code: str
    quantity: Decimal = Field(default=Decimal("1"), gt=0)


class DiscountRequest(BaseModel):
    code: str | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    percent: Decimal | None = Field(default=None, ge=0, le=100)
    reason: str | None = None


class QuoteCreateRequest(BaseModel):
    customer: Customer
    project_name: str
    project_type: str = "web"
    items: list[QuoteItemRequest]
    discount: DiscountRequest | None = None
    valid_days: int = Field(default=14, ge=1, le=90)
    notes: str | None = None
    delivery_weeks: str | None = None
    acceptance_criteria: list[str] = []
    exclusions: list[str] = []
    external_lead_id: str | None = None
    source: str | None = "website_quote_form"
    source_data: dict = {}


class QuoteRevisionRequest(BaseModel):
    items: list[QuoteItemRequest]
    discount: DiscountRequest | None = None
    notes: str | None = None
    reason: str | None = None
    delivery_weeks: str | None = None
    acceptance_criteria: list[str] | None = None
    exclusions: list[str] | None = None


class PublicConfigureRequest(BaseModel):
    selected_optional_codes: list[str] = []


class QuoteItem(BaseModel):
    code: str
    name: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    taxable: bool = True
    contract_tags: list[str] = []
    customer_configurable: bool = False


class QuoteTotals(BaseModel):
    subtotal: Decimal
    discount: Decimal
    net_total: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    gross_total: Decimal


class QuoteApproveRequest(BaseModel):
    accepted_by: str
    accepted_email: str
    confirm_business_authority: bool = True
    client_ip: str | None = None
    user_agent: str | None = None


class ProposalInterestRequest(BaseModel):
    accepted_by: str | None = None
    accepted_email: str | None = None
    accepted_phone: str | None = None
    notes: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None


class CallBookingRequest(BaseModel):
    external_booking_id: str | None = None
    booking_url: str | None = None
    scheduled_at: datetime | str | None = None
    raw: dict = {}


class CallCancelRequest(BaseModel):
    external_booking_id: str | None = None
    cancellation_reason: str | None = None
    raw: dict = {}


class EmailStatusRequest(BaseModel):
    status: Literal["SENT", "FAILED"]
    provider: str = "smtp"
    message_id: str | None = None
    error_code: str | None = None
    sent_at: datetime | str | None = None


class ContractProviderCreatedRequest(BaseModel):
    provider: str = "generic"
    external_envelope_id: str
    signing_url: str | None = None
    raw: dict = {}


class SignatureCompletedRequest(BaseModel):
    provider: str = "generic"
    external_envelope_id: str | None = None
    signed_document_url: str | None = None
    audit_trail_url: str | None = None
    signed_at: datetime | None = None
    general_signature_completed: bool = False
    specific_1341_1342_completed: bool = False
    raw: dict = {}


class DepositCreatedRequest(BaseModel):
    provider: str = "generic"
    external_payment_id: str
    checkout_url: str | None = None
    amount: Decimal | None = None
    raw: dict = {}


class DepositPaidRequest(BaseModel):
    provider: str = "generic"
    external_payment_id: str | None = None
    amount: Decimal | None = None
    paid_at: datetime | None = None
    raw: dict = {}


class ChecklistItem(BaseModel):
    code: str
    label: str
    required: bool = True
    completed: bool = False
    value: str | None = None


class ChecklistUpdateRequest(BaseModel):
    items: list[ChecklistItem]


class LifecycleView(BaseModel):
    quote_id: str
    state: str
    contract: dict = {}
    payment: dict = {}
    onboarding: dict = {}
    updated_at: datetime
