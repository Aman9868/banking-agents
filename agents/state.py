"""Global LangGraph State definitions for Multi-Agent Enterprise Banking (Phases 1-7)."""

from typing import List, Dict, Any, Optional, Annotated
from typing_extensions import TypedDict
import operator
from langchain_core.messages import BaseMessage


class AccountWorkflowData(TypedDict, total=False):
    full_name: Optional[str]
    date_of_birth: Optional[str]
    email: Optional[str]
    account_type: Optional[str]  # SAVINGS, CURRENT
    # Business & Current Account fields
    company_name: Optional[str]
    business_type: Optional[str]
    gstin: Optional[str]
    gst_verified: bool
    gst_certificate_b64: Optional[str]
    # Aadhaar & Biometric Video KYC fields
    aadhaar_number: Optional[str]
    aadhaar_masked: Optional[str]
    aadhaar_verified: bool
    aadhaar_image_b64: Optional[str]
    live_selfie_verified: bool
    face_match_score: Optional[float]
    selfie_image_b64: Optional[str]
    # Workflow progression & Compliance
    kyc_status: str  # PENDING, IN_PROGRESS, VERIFIED, FAILED
    aml_status: str  # PENDING, CLEAR, FLAGGED, REJECTED
    risk_level: str  # LOW, HIGH
    application_id: Optional[str]
    account_number: Optional[str]
    step: str  # NAME, DOB, EMAIL, TYPE, BUSINESS_INFO, GST_VERIFY, AADHAAR_UPLOAD, LIVE_KYC, KYC, AML, COMPLETED



class TransferWorkflowData(TypedDict, total=False):
    amount: Optional[float]
    beneficiary_name: Optional[str]
    beneficiary_id: Optional[int]
    beneficiary_account: Optional[str]
    ifsc_code: Optional[str]
    source_account_id: Optional[int]
    source_account_number: Optional[str]
    fraud_score: float
    fraud_reasons: List[str]
    policy_decision: Optional[str]
    step_up_verified: bool
    user_confirmed: bool
    transaction_ref: Optional[str]
    idempotency_key: Optional[str]
    step: str  # RESOLVE, FRAUD_CHECK, POLICY_CHECK, CONFIRM, EXECUTE, COMPLETED


class CardWorkflowData(TypedDict, total=False):
    action: str  # STATUS, FREEZE, UNFREEZE, REPLACE, SET_LIMIT
    card_type: str  # DEBIT, CREDIT
    online_limit: Optional[float]
    atm_limit: Optional[float]
    reason: Optional[str]
    step: str


class LoanWorkflowData(TypedDict, total=False):
    action: str  # CALCULATE_EMI, CHECK_ELIGIBILITY, APPLY_LOAN, STATUS
    loan_type: str  # PERSONAL, HOME, AUTO
    amount: Optional[float]
    tenure_months: Optional[int]
    annual_income: Optional[float]
    existing_emi: Optional[float]
    monthly_emi: Optional[float]
    application_ref: Optional[str]
    step: str  # AMOUNT, TENURE, INCOME, CONFIRM, SUBMITTED


class PaymentWorkflowData(TypedDict, total=False):
    action: str  # PAY_BILL, FETCH_BILL, UPI_PAY
    biller_name: Optional[str]
    consumer_number: Optional[str]
    amount: Optional[float]
    upi_id: Optional[str]
    source_account_id: Optional[int]
    source_account_number: Optional[str]
    user_confirmed: bool
    payment_ref: Optional[str]
    idempotency_key: Optional[str]
    step: str  # BILLER, CONSUMER, CONFIRM, EXECUTE, COMPLETED


class SupportWorkflowData(TypedDict, total=False):
    action: str  # DISPUTE, FAQ_SEARCH, CREATE_TICKET
    sub_intent: Optional[str]  # CARD_PAYMENT_DECLINED, UPI_PAYMENT_FAILED, UNAUTHORIZED_TRANSACTION, etc.
    query: Optional[str]
    transaction_ref: Optional[str]
    ticket_subject: Optional[str]
    ticket_ref: Optional[str]


class InsightsWorkflowData(TypedDict, total=False):
    action: str  # SPENDING, SUBSCRIPTIONS, CASHFLOW
    days: Optional[int]
    proposed_debit: Optional[float]
    step: str


class WealthWorkflowData(TypedDict, total=False):
    monthly_investment: Optional[float]
    user_persona: Optional[str]  # STUDENT, EARLY_CAREER, PROFESSIONAL, RETIRED
    risk_profile: Optional[str]  # CONSERVATIVE, MODERATE, AGGRESSIVE
    tenure_years: Optional[int]
    query: Optional[str]
    symbol: Optional[str]
    step: str  # ADVICE, SIP_CALC, MARKET_SEARCH, COMPLETED


class PolicyWorkflowData(TypedDict, total=False):
    category: Optional[str]  # HEALTH, LIFE, GOVT_SCHEME, BANKING_DEPOSIT, ALL
    policy_id: Optional[str]
    policy_a_id: Optional[str]
    policy_b_id: Optional[str]
    query: Optional[str]
    step: str  # OVERVIEW, DETAILS, COMPARE, COMPLETED


class BankingSessionState(TypedDict):
    # Chronological conversation messages
    messages: Annotated[List[BaseMessage], operator.add]

    # Authenticated Customer Context
    customer_id: int
    customer_external_id: str
    customer_name: str

    # Active and Paused Workflows for Context Switching
    active_workflow: str  # NONE, OPEN_ACCOUNT, TRANSFER_MONEY, CARD_ACTION, LOAN_ACTION, PAYMENT_ACTION, SUPPORT, INSIGHTS, WEALTH_ADVISORY, POLICY_ACTION
    paused_workflow: Optional[str]  # Saved previous workflow when topic is interrupted

    # Sub-workflow states
    account_data: AccountWorkflowData
    transfer_data: TransferWorkflowData
    card_data: CardWorkflowData
    loan_data: LoanWorkflowData
    payment_data: PaymentWorkflowData
    support_data: SupportWorkflowData
    insights_data: InsightsWorkflowData
    wealth_data: WealthWorkflowData
    policy_data: PolicyWorkflowData

    # Execution routing and HITL
    current_intent: Optional[str]
    current_sub_intent: Optional[str]
    intent_confidence: Optional[float]
    routing_reasoning: Optional[str]
    negation_detected: Optional[bool]
    hitl_task_id: Optional[str]
    hitl_status: Optional[str]  # PENDING, APPROVED, REJECTED
    final_response: Optional[str]

    # Persistent Cross-Subgraph Entity Memory
    customer_memory: Dict[str, Any]

    # LangGraph Parallel Fan-Out Security Evaluation Results
    fraud_check_result: Optional[Dict[str, Any]]
    aml_check_result: Optional[Dict[str, Any]]
    ledger_check_result: Optional[Dict[str, Any]]

    # Generative UI (GenUI) Dynamic Interactive Widgets
    widget_type: Optional[str]  # EMI_SLIDER, TRANSACTION_RECEIPT, SPENDING_CHART, SUBSCRIPTION_LIST, ACCOUNT_CARD, AADHAAR_UPLOAD_WIDGET, LIVE_FACE_KYC_WIDGET, GST_VERIFY_WIDGET, STATEMENT_WIDGET, TRANSACTION_EXPLAIN_WIDGET, SIP_PLANNER_WIDGET, STOCK_MARKET_WIDGET, POLICY_CARD_WIDGET
    widget_data: Optional[Dict[str, Any]]

    # Direct KYC Document & Biometric upload payload
    kyc_payload: Optional[Dict[str, Any]]



