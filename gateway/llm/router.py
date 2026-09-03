"""Production-grade Intent Classification, Sub-Intent Resolution, and Entity Extraction Engine."""

import re
import json
import datetime
from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from gateway.llm.client import llm_gateway
import structlog

logger = structlog.get_logger(__name__)


class BankingIntent(str, Enum):
    TRANSFER_MONEY = "TRANSFER_MONEY"
    OPEN_ACCOUNT = "OPEN_ACCOUNT"
    BALANCE_CHECK = "BALANCE_CHECK"
    CARD_ACTION = "CARD_ACTION"
    LOAN_ACTION = "LOAN_ACTION"
    PAYMENT_ACTION = "PAYMENT_ACTION"
    SPENDING_INSIGHTS = "SPENDING_INSIGHTS"
    KNOWLEDGE_FAQ = "KNOWLEDGE_FAQ"
    SUPPORT_DISPUTE = "SUPPORT_DISPUTE"
    TEMPORAL_QUERY = "TEMPORAL_QUERY"
    CONFIRM_YES = "CONFIRM_YES"
    CONFIRM_NO = "CONFIRM_NO"
    GENERAL_CONVERSATION = "GENERAL_CONVERSATION"


class BankingSubIntent(str, Enum):
    # Support & Disputes
    CARD_PAYMENT_DECLINED = "CARD_PAYMENT_DECLINED"
    UPI_PAYMENT_FAILED = "UPI_PAYMENT_FAILED"
    TRANSFER_FAILED = "TRANSFER_FAILED"
    ATM_WITHDRAWAL_FAILED = "ATM_WITHDRAWAL_FAILED"
    UNAUTHORIZED_TRANSACTION = "UNAUTHORIZED_TRANSACTION"
    FEE_DISPUTE = "FEE_DISPUTE"
    CREATE_TICKET = "CREATE_TICKET"

    # Card Actions
    FREEZE_CARD = "FREEZE_CARD"
    UNFREEZE_CARD = "UNFREEZE_CARD"
    REPLACE_CARD = "REPLACE_CARD"
    SET_LIMIT = "SET_LIMIT"
    CARD_STATUS = "CARD_STATUS"

    # Loan Actions
    EMI_CALCULATION = "EMI_CALCULATION"
    LOAN_ELIGIBILITY = "LOAN_ELIGIBILITY"
    APPLY_LOAN = "APPLY_LOAN"

    # Transfer & Payments
    DOMESTIC_P2P_TRANSFER = "DOMESTIC_P2P_TRANSFER"
    ELECTRICITY_BILL = "ELECTRICITY_BILL"
    BROADBAND_BILL = "BROADBAND_BILL"
    CREDIT_CARD_BILL = "CREDIT_CARD_BILL"
    UPI_PAYMENT = "UPI_PAYMENT"

    # Account Opening
    SAVINGS_ACCOUNT_OPENING = "SAVINGS_ACCOUNT_OPENING"
    CURRENT_ACCOUNT_OPENING = "CURRENT_ACCOUNT_OPENING"

    # PFM Analytics
    SPENDING_BREAKDOWN = "SPENDING_BREAKDOWN"
    SUBSCRIPTION_AUDIT = "SUBSCRIPTION_AUDIT"
    CASHFLOW_PREDICTION = "CASHFLOW_PREDICTION"

    # Time & General
    CURRENT_TIME_DATE = "CURRENT_TIME_DATE"
    GREETING = "GREETING"
    OTHER = "OTHER"


class ExtractedEntities(BaseModel):
    amount: Optional[float] = None
    currency: Optional[str] = "INR"
    beneficiary_name: Optional[str] = None
    account_type: Optional[str] = None  # SAVINGS, CURRENT
    card_type: Optional[str] = None  # DEBIT, CREDIT
    biller_name: Optional[str] = None
    tenure_months: Optional[int] = None
    date_of_birth: Optional[str] = None
    transaction_ref: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None


class BankingRoutingDecision(BaseModel):
    intent: BankingIntent
    sub_intent: Optional[BankingSubIntent] = None
    confidence: float = Field(default=0.95, ge=0.0, le=1.0)
    negation_detected: bool = Field(default=False, description="True if the user explicitly negates the action")
    reasoning: str = Field(default="", description="Audit explanation for compliance trace")
    entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    requires_clarification: bool = Field(default=False, description="True if query is ambiguous or confidence < 0.65")
    clarification_prompt: Optional[str] = None
    target_agent_mention: Optional[str] = None
    cleaned_message: str = ""


# Direct @mention agent routing map
MENTION_ROUTING_MAP = {
    "@support": (BankingIntent.SUPPORT_DISPUTE, BankingSubIntent.CREATE_TICKET),
    "@loan": (BankingIntent.LOAN_ACTION, BankingSubIntent.EMI_CALCULATION),
    "@card": (BankingIntent.CARD_ACTION, BankingSubIntent.CARD_STATUS),
    "@cards": (BankingIntent.CARD_ACTION, BankingSubIntent.CARD_STATUS),
    "@transfer": (BankingIntent.TRANSFER_MONEY, BankingSubIntent.DOMESTIC_P2P_TRANSFER),
    "@pay": (BankingIntent.PAYMENT_ACTION, BankingSubIntent.ELECTRICITY_BILL),
    "@payment": (BankingIntent.PAYMENT_ACTION, BankingSubIntent.ELECTRICITY_BILL),
    "@insights": (BankingIntent.SPENDING_INSIGHTS, BankingSubIntent.SPENDING_BREAKDOWN),
    "@pfm": (BankingIntent.SPENDING_INSIGHTS, BankingSubIntent.SPENDING_BREAKDOWN),
    "@account": (BankingIntent.OPEN_ACCOUNT, BankingSubIntent.SAVINGS_ACCOUNT_OPENING),
}


def _extract_mention(message: str):
    """Extracts @mention prefix from user input if present."""
    words = message.strip().split()
    if words and words[0].lower() in MENTION_ROUTING_MAP:
        mention = words[0].lower()
        cleaned = " ".join(words[1:]).strip()
        return mention, cleaned
    return None, message.strip()


def _extract_entities_fast(message: str) -> ExtractedEntities:
    """Deterministic regex entity extractor to supplement and validate LLM outputs."""
    entities = ExtractedEntities()

    # Amount extraction (handles lakh, lac, cr, k, and commas)
    lakh_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:lakh|lac)s?", message, re.IGNORECASE)
    if lakh_match:
        entities.amount = float(lakh_match.group(1)) * 100000.0
    else:
        k_match = re.search(r"(\d+(?:\.\d+)?)\s*k\b", message, re.IGNORECASE)
        if k_match:
            entities.amount = float(k_match.group(1)) * 1000.0
        else:
            amt_match = re.search(r"(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)", message, re.IGNORECASE)
            if amt_match:
                val_str = amt_match.group(1).replace(",", "")
                try:
                    val = float(val_str)
                    if val > 0 and val != 2026:  # ignore year
                        entities.amount = val
                except ValueError:
                    pass

    # Beneficiary extraction (e.g. "to Rahul", "send Rahul", "pay Rahul")
    to_match = re.search(r"\b(?:to|pay)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", message)
    if to_match:
        entities.beneficiary_name = to_match.group(1).strip()

    # Tenure extraction
    tenure_match = re.search(r"(\d+)\s*(?:years?|yrs?)", message, re.IGNORECASE)
    if tenure_match:
        entities.tenure_months = int(tenure_match.group(1)) * 12
    else:
        month_match = re.search(r"(\d+)\s*(?:months?|mths?)", message, re.IGNORECASE)
        if month_match:
            entities.tenure_months = int(month_match.group(1))

    # Card type
    if "credit" in message.lower():
        entities.card_type = "CREDIT"
    elif "debit" in message.lower():
        entities.card_type = "DEBIT"

    # Biller name
    for b in ["Tata Power", "Airtel Broadband", "HDFC Credit Card", "Tata", "Airtel"]:
        if b.lower() in message.lower():
            entities.biller_name = b
            break

    # DOB extraction
    dob_match = re.search(r"\b(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b", message)
    if dob_match:
        entities.date_of_birth = dob_match.group(1).strip()

    # Transaction reference (e.g. TXN-100234)
    txn_match = re.search(r"\b(TXN-[A-Za-z0-9]+)\b", message, re.IGNORECASE)
    if txn_match:
        entities.transaction_ref = txn_match.group(1).upper()

    return entities


async def route_banking_request(
    message: str,
    context: Optional[Dict[str, Any]] = None
) -> BankingRoutingDecision:
    """
    Enterprise-grade production banking intent router:
    1. Handles direct @mention overrides.
    2. Deterministic fast-paths strictly for 1-token confirmations.
    3. LLM-based structured classification with sub-intents, typo resilience, and negation detection.
    4. Real-time temporal context awareness (UTC/IST).
    5. Confidence thresholding with automatic disambiguation generation.
    """
    context = context or {}
    raw_text = message.strip()
    clean_text = raw_text.lower()

    # 1. Direct @mention parsing
    mention, stripped_msg = _extract_mention(raw_text)
    if mention and mention in MENTION_ROUTING_MAP:
        prim_intent, sub_intent = MENTION_ROUTING_MAP[mention]
        entities = _extract_entities_fast(stripped_msg)
        return BankingRoutingDecision(
            intent=prim_intent,
            sub_intent=sub_intent,
            confidence=1.0,
            negation_detected=False,
            reasoning=f"Explicit agent mention directed by user: {mention}",
            entities=entities,
            target_agent_mention=mention,
            cleaned_message=stripped_msg
        )

    # 2. Deterministic single-token confirmation / negation fast paths
    if clean_text in ["yes", "confirm", "proceed", "yep", "sure", "approve", "do it", "yup"]:
        return BankingRoutingDecision(
            intent=BankingIntent.CONFIRM_YES,
            sub_intent=BankingSubIntent.OTHER,
            confidence=1.0,
            negation_detected=False,
            reasoning="Exact affirmative confirmation token.",
            cleaned_message=raw_text
        )
    if clean_text in ["no", "cancel", "stop", "abort", "reject", "decline"]:
        return BankingRoutingDecision(
            intent=BankingIntent.CONFIRM_NO,
            sub_intent=BankingSubIntent.OTHER,
            confidence=1.0,
            negation_detected=True,
            reasoning="Exact cancellation/negation token.",
            cleaned_message=raw_text
        )

    # 3. Dynamic Temporal Injection (Current Date, Time & Day)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
    current_time_str = now_ist.strftime("%A, %d-%b-%Y %I:%M %p IST")

    # Fast temporal query check
    if any(q in clean_text for q in ["what is the time", "what time is it", "what date is today", "what is today's date", "todays date", "current time", "what day is today"]):
        return BankingRoutingDecision(
            intent=BankingIntent.TEMPORAL_QUERY,
            sub_intent=BankingSubIntent.CURRENT_TIME_DATE,
            confidence=1.0,
            negation_detected=False,
            reasoning=f"Inquiry regarding current time/date: {current_time_str}",
            cleaned_message=raw_text
        )

    # 4. Contextual Step Fulfillment (e.g. User answering a prompt during onboarding or transfer)
    active_wf = context.get("active_workflow", "NONE")
    acc_step = (context.get("account_data") or {}).get("step")
    is_opening_trigger = any(k in clean_text for k in ["open", "savings", "current", "apply", "register", "novabank"])

    if active_wf == "OPEN_ACCOUNT" and not is_opening_trigger:
        entities = _extract_entities_fast(raw_text)
        if acc_step == "NAME":
            entities.full_name = raw_text
        elif acc_step == "DOB":
            entities.date_of_birth = raw_text
        elif acc_step == "EMAIL":
            entities.email = raw_text

        return BankingRoutingDecision(
            intent=BankingIntent.OPEN_ACCOUNT,
            sub_intent=BankingSubIntent.SAVINGS_ACCOUNT_OPENING,
            confidence=0.98,
            negation_detected=False,
            reasoning="Context continuation for active OPEN_ACCOUNT slot collection.",
            entities=entities,
            cleaned_message=raw_text
        )

    # 5. LLM Structured Routing Prompt
    system_prompt = f"""You are NovaBank's enterprise banking intent classification and entity router.
Current Temporal Context: {current_time_str}
Active Conversation Workflow: {active_wf}

CRITICAL RULES:
1. TYPO & SLANG RESILIENCE:
   The user may make spelling errors or use abbreviations (e.g. 'trnasfer', 'balence', 'freze', 'persoanl lon', 'wht is my bal', '5k').
   Understand the intent by meaning, not rigid string matching.

2. NEGATION DETECTION:
   If the user states they DO NOT want to perform an action (e.g., 'I do not want to transfer money', 'Don't freeze my card', 'Cancel payment'):
   Set negation_detected: true. DO NOT route to mutating intent. Set intent to GENERAL_CONVERSATION.

3. DISPUTE & SUPPORT SUB-INTENT DISCRIMINATION:
   Differentiate between:
   - CARD_PAYMENT_DECLINED: card declined, swipe failed, POS declined.
   - UPI_PAYMENT_FAILED: UPI failed, GPay/PhonePe error.
   - TRANSFER_FAILED: NEFT/RTGS/IMPS wire transfer bounced or rejected.
   - ATM_WITHDRAWAL_FAILED: ATM didn't dispense cash.
   - UNAUTHORIZED_TRANSACTION: fraud, suspicious debit, stolen money.
   - CREATE_TICKET: user wants to talk to a human agent, speak with support, open/raise a ticket, or file a complaint.

4. CONFIDENCE THRESHOLDING:
   If the query is ambiguous between multiple banking actions, set requires_clarification: true and provide clarification_prompt.

Allowed Intents:
TRANSFER_MONEY, OPEN_ACCOUNT, BALANCE_CHECK, CARD_ACTION, LOAN_ACTION, PAYMENT_ACTION,
SPENDING_INSIGHTS, KNOWLEDGE_FAQ, SUPPORT_DISPUTE, TEMPORAL_QUERY, CONFIRM_YES, CONFIRM_NO, GENERAL_CONVERSATION.

Respond ONLY with a JSON object matching this schema:
{{
  "intent": "<INTENT_NAME>",
  "sub_intent": "<SUB_INTENT_NAME>",
  "confidence": 0.0 to 1.0,
  "negation_detected": true/false,
  "reasoning": "<brief explanation>",
  "entities": {{
    "amount": null or float,
    "currency": "INR",
    "beneficiary_name": null or str,
    "account_type": null or "SAVINGS" or "CURRENT",
    "card_type": null or "DEBIT" or "CREDIT",
    "biller_name": null or str,
    "tenure_months": null or int,
    "transaction_ref": null or str
  }},
  "requires_clarification": false,
  "clarification_prompt": null
}}"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=raw_text)
    ]

    try:
        response = await llm_gateway.invoke_chat(messages, model_tier="routing")
        data = json.loads(response.content.strip())

        intent_raw = data.get("intent")
        intent_enum = BankingIntent(intent_raw) if intent_raw in BankingIntent._value2member_map_ else BankingIntent.GENERAL_CONVERSATION

        sub_raw = data.get("sub_intent")
        sub_enum = BankingSubIntent(sub_raw) if sub_raw in BankingSubIntent._value2member_map_ else None

        # Direct override if customer requested human support or ticket creation
        if any(k in clean_text for k in ["human", "agent", "ticket", "escalate", "representative", "file a complaint"]):
            intent_enum = BankingIntent.SUPPORT_DISPUTE
            sub_enum = BankingSubIntent.CREATE_TICKET

        # Canonical fallback sub-intent inference if LLM omitted sub_intent
        if not sub_enum:
            if intent_enum == BankingIntent.CARD_ACTION:
                sub_enum = BankingSubIntent.FREEZE_CARD if any(k in clean_text for k in ["freeze", "freze", "lock", "lost", "stolen"]) else BankingSubIntent.CARD_STATUS
            elif intent_enum == BankingIntent.LOAN_ACTION:
                sub_enum = BankingSubIntent.EMI_CALCULATION if any(k in clean_text for k in ["emi", "calculate"]) else BankingSubIntent.LOAN_ELIGIBILITY
            elif intent_enum == BankingIntent.TRANSFER_MONEY:
                sub_enum = BankingSubIntent.DOMESTIC_P2P_TRANSFER
            elif intent_enum == BankingIntent.OPEN_ACCOUNT:
                sub_enum = BankingSubIntent.SAVINGS_ACCOUNT_OPENING
            elif intent_enum == BankingIntent.SPENDING_INSIGHTS:
                sub_enum = BankingSubIntent.SPENDING_BREAKDOWN
            elif intent_enum == BankingIntent.SUPPORT_DISPUTE:
                if any(k in clean_text for k in ["card", "swipe", "pos"]):
                    sub_enum = BankingSubIntent.CARD_PAYMENT_DECLINED
                elif any(k in clean_text for k in ["upi", "gpay", "phonepe"]):
                    sub_enum = BankingSubIntent.UPI_PAYMENT_FAILED
                elif any(k in clean_text for k in ["unauthorized", "fraud", "stolen", "suspicious"]):
                    sub_enum = BankingSubIntent.UNAUTHORIZED_TRANSACTION
                elif any(k in clean_text for k in ["transfer", "wire", "neft", "rtgs"]):
                    sub_enum = BankingSubIntent.TRANSFER_FAILED
                else:
                    sub_enum = BankingSubIntent.CREATE_TICKET

        decision = BankingRoutingDecision(
            intent=intent_enum,
            sub_intent=sub_enum,
            confidence=float(data.get("confidence", 0.9)),
            negation_detected=bool(data.get("negation_detected", False)),
            reasoning=data.get("reasoning", "LLM routing classification"),
            entities=ExtractedEntities(**(data.get("entities") or {})),
            requires_clarification=bool(data.get("requires_clarification", False)),
            clarification_prompt=data.get("clarification_prompt"),
            cleaned_message=raw_text
        )

        # Do not block valid dispute investigations with clarification prompts
        if intent_enum == BankingIntent.SUPPORT_DISPUTE and any(k in clean_text for k in ["declined", "failed", "last transaction", "unauthorized", "why was"]):
            decision.requires_clarification = False

        # Merge with fast entity extractor to ensure zero missing numbers
        fast_entities = _extract_entities_fast(raw_text)
        if not decision.entities.amount and fast_entities.amount:
            decision.entities.amount = fast_entities.amount
        if not decision.entities.beneficiary_name and fast_entities.beneficiary_name:
            decision.entities.beneficiary_name = fast_entities.beneficiary_name
        if not decision.entities.tenure_months and fast_entities.tenure_months:
            decision.entities.tenure_months = fast_entities.tenure_months
        if not decision.entities.card_type and fast_entities.card_type:
            decision.entities.card_type = fast_entities.card_type
        if not decision.entities.biller_name and fast_entities.biller_name:
            decision.entities.biller_name = fast_entities.biller_name
        if not decision.entities.transaction_ref and fast_entities.transaction_ref:
            decision.entities.transaction_ref = fast_entities.transaction_ref

        return decision

    except Exception as exc:
        logger.warning("Structured routing LLM parsing failed, using deterministic adapter", error=str(exc))
        fast_entities = _extract_entities_fast(raw_text)
        fallback_intent = BankingIntent.GENERAL_CONVERSATION
        fallback_sub = None
        if any(k in clean_text for k in ["transfer", "trnasfer", "send"]):
            fallback_intent = BankingIntent.TRANSFER_MONEY
            fallback_sub = BankingSubIntent.DOMESTIC_P2P_TRANSFER
        elif any(k in clean_text for k in ["balance", "balence"]):
            fallback_intent = BankingIntent.BALANCE_CHECK
        elif any(k in clean_text for k in ["freeze", "freze"]):
            fallback_intent = BankingIntent.CARD_ACTION
            fallback_sub = BankingSubIntent.FREEZE_CARD

        return BankingRoutingDecision(
            intent=fallback_intent,
            sub_intent=fallback_sub,
            confidence=0.8,
            reasoning="Fallback recovery",
            entities=fast_entities,
            cleaned_message=raw_text
        )


# Backward-compatible adapter functions for existing imports
async def classify_intent(message: str) -> str:
    """Backward-compatible adapter returning intent string."""
    decision = await route_banking_request(message)
    if decision.negation_detected and decision.intent == BankingIntent.TRANSFER_MONEY:
        return "GENERAL_CONVERSATION"
    return decision.intent.value


async def extract_slots(message: str) -> Dict[str, Any]:
    """Backward-compatible adapter returning dictionary of extracted entities."""
    entities = _extract_entities_fast(message)
    result = {}
    if entities.amount:
        result["amount"] = entities.amount
    if entities.beneficiary_name:
        result["beneficiary_name"] = entities.beneficiary_name
    if entities.tenure_months:
        result["tenure_months"] = entities.tenure_months
    if entities.card_type:
        result["card_type"] = entities.card_type
    if entities.biller_name:
        result["biller_name"] = entities.biller_name
    if entities.date_of_birth:
        result["dob"] = entities.date_of_birth
    if entities.transaction_ref:
        result["transaction_ref"] = entities.transaction_ref
    return result
