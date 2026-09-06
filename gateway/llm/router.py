"""Production-grade Intent Classification, Sub-Intent Resolution, and Entity Extraction Engine."""

import re
import json
import datetime
from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from gateway.llm.client import llm_gateway
from gateway.llm.prompts import build_banking_router_prompt
import structlog

logger = structlog.get_logger(__name__)


class BankingIntent(str, Enum):
    TRANSFER_MONEY = "TRANSFER_MONEY"
    OPEN_ACCOUNT = "OPEN_ACCOUNT"
    BALANCE_CHECK = "BALANCE_CHECK"
    TRANSACTION_INQUIRY = "TRANSACTION_INQUIRY"
    STATEMENT_REQUEST = "STATEMENT_REQUEST"
    CARD_ACTION = "CARD_ACTION"
    LOAN_ACTION = "LOAN_ACTION"
    PAYMENT_ACTION = "PAYMENT_ACTION"
    SPENDING_INSIGHTS = "SPENDING_INSIGHTS"
    WEALTH_ADVISORY = "WEALTH_ADVISORY"
    POLICY_INQUIRY = "POLICY_INQUIRY"
    KNOWLEDGE_FAQ = "KNOWLEDGE_FAQ"
    SUPPORT_DISPUTE = "SUPPORT_DISPUTE"
    TEMPORAL_QUERY = "TEMPORAL_QUERY"
    CONFIRM_YES = "CONFIRM_YES"
    CONFIRM_NO = "CONFIRM_NO"
    GENERAL_CONVERSATION = "GENERAL_CONVERSATION"


class BankingSubIntent(str, Enum):
    # Statements & Ledgers
    DOWNLOAD_STATEMENT = "DOWNLOAD_STATEMENT"

    # Wealth & Investment Advisory
    SIP_PLANNING = "SIP_PLANNING"
    SIP_MANDATE_SETUP = "SIP_MANDATE_SETUP"
    STOCK_MARKET_SEARCH = "STOCK_MARKET_SEARCH"
    PORTFOLIO_RECOMMENDATION = "PORTFOLIO_RECOMMENDATION"

    # Insurance & Banking Policies
    HEALTH_INSURANCE = "HEALTH_INSURANCE"
    LIFE_INSURANCE = "LIFE_INSURANCE"
    GOVERNMENT_SCHEME = "GOVERNMENT_SCHEME"
    BANKING_POLICY = "BANKING_POLICY"

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

    # Transaction Tracking & History
    LATEST_TRANSFER = "LATEST_TRANSFER"
    TRANSFER_HISTORY = "TRANSFER_HISTORY"
    TRACK_TRANSACTION = "TRACK_TRANSACTION"
    EXPLAIN_DECLINE = "EXPLAIN_DECLINE"
    EXPLAIN_LAST_TXN = "EXPLAIN_LAST_TXN"

    # Account & Profile
    SAVINGS_ACCOUNT_OPENING = "SAVINGS_ACCOUNT_OPENING"
    CURRENT_ACCOUNT_OPENING = "CURRENT_ACCOUNT_OPENING"
    KYC_STATUS = "KYC_STATUS"
    LIST_ACCOUNTS = "LIST_ACCOUNTS"
    WEB_SEARCH = "WEB_SEARCH"


    # PFM Analytics
    SPENDING_BREAKDOWN = "SPENDING_BREAKDOWN"
    SUBSCRIPTION_AUDIT = "SUBSCRIPTION_AUDIT"
    CASHFLOW_PREDICTION = "CASHFLOW_PREDICTION"

    # Time & General
    CURRENT_TIME_DATE = "CURRENT_TIME_DATE"
    GREETING = "GREETING"
    THANK_YOU = "THANK_YOU"
    OTHER = "OTHER"


class ExtractedEntities(BaseModel):
    amount: Optional[float] = None
    target_amount: Optional[float] = None
    currency: Optional[str] = "INR"
    beneficiary_name: Optional[str] = None
    beneficiary_account: Optional[str] = None
    ifsc_code: Optional[str] = None
    account_type: Optional[str] = None  # SAVINGS, CURRENT
    card_type: Optional[str] = None  # DEBIT, CREDIT
    biller_name: Optional[str] = None
    tenure_months: Optional[int] = None
    date_of_birth: Optional[str] = None
    transaction_ref: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    period_type: Optional[str] = None  # LAST_6_MONTHS, THIS_WEEK, LAST_MONTH, etc.
    user_persona: Optional[str] = None  # STUDENT, EARLY_CAREER, PROFESSIONAL
    risk_profile: Optional[str] = None  # CONSERVATIVE, MODERATE, AGGRESSIVE
    stock_symbol: Optional[str] = None
    policy_category: Optional[str] = None  # HEALTH, LIFE, GOVT_SCHEME, BANKING_DEPOSIT


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
    "@wealth": (BankingIntent.WEALTH_ADVISORY, BankingSubIntent.SIP_PLANNING),
    "@sip": (BankingIntent.WEALTH_ADVISORY, BankingSubIntent.SIP_PLANNING),
    "@invest": (BankingIntent.WEALTH_ADVISORY, BankingSubIntent.PORTFOLIO_RECOMMENDATION),
    "@stock": (BankingIntent.WEALTH_ADVISORY, BankingSubIntent.STOCK_MARKET_SEARCH),
    "@stocks": (BankingIntent.WEALTH_ADVISORY, BankingSubIntent.STOCK_MARKET_SEARCH),
    "@policy": (BankingIntent.POLICY_INQUIRY, BankingSubIntent.BANKING_POLICY),
    "@insurance": (BankingIntent.POLICY_INQUIRY, BankingSubIntent.HEALTH_INSURANCE),
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

    # 1. Beneficiary account number extraction FIRST
    acc_match = re.search(r"(?:acc(?:ount)?\s*(?:no|num|number)?\s*[-:=]?\s*)([A-Za-z0-9]+)\b", message, re.IGNORECASE)
    if acc_match:
        entities.beneficiary_account = acc_match.group(1).strip()
    else:
        # Check for standalone 9-18 digit account numbers
        raw_digits = re.findall(r"\b(\d{9,18})\b", message)
        if raw_digits:
            entities.beneficiary_account = raw_digits[0]

    # 2. IFSC extraction
    ifsc_match = re.search(r"(?:ifsc(?:\s*code)?\s*[-:=]?\s*)([A-Za-z0-9]+)\b", message, re.IGNORECASE)
    if ifsc_match:
        entities.ifsc_code = ifsc_match.group(1).upper().strip()
    else:
        # Standard IFSC format regex: 4 letters + 0/digit + 6 alphanumeric
        raw_ifsc = re.search(r"\b([A-Za-z]{4}[0-9][0-9A-Za-z]{6})\b", message)
        if raw_ifsc:
            entities.ifsc_code = raw_ifsc.group(1).upper().strip()

    # 3. Amount extraction (excluding account number and IFSC code if present)
    amt_text = message
    if entities.beneficiary_account:
        amt_text = amt_text.replace(entities.beneficiary_account, " ")
    if entities.ifsc_code:
        amt_text = amt_text.replace(entities.ifsc_code, " ")

    lakh_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:lakh|lac)s?", amt_text, re.IGNORECASE)
    if lakh_match:
        entities.amount = float(lakh_match.group(1)) * 100000.0
    else:
        k_match = re.search(r"(\d+(?:\.\d+)?)\s*k\b", amt_text, re.IGNORECASE)
        if k_match:
            entities.amount = float(k_match.group(1)) * 1000.0
        else:
            # Currency symbol match or raw number up to 6 digits
            amt_match = re.search(r"(?:₹|rs\.?|inr)\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)", amt_text, re.IGNORECASE)
            if not amt_match:
                amt_match = re.search(r"\b(\d{1,6}(?:\.\d+)?)\b", amt_text)
            if amt_match:
                val_str = amt_match.group(1).replace(",", "")
                try:
                    val = float(val_str)
                    if val > 0 and val not in [2024, 2025, 2026, 2027]:  # ignore years
                        entities.amount = val
                except ValueError:
                    pass

    # 4. Beneficiary extraction (e.g. "to Rahul", "send Rahul", "pay Rahul", "beneficiary Rahul")
    to_match = re.search(r"\b(?:to|pay|beneficiary|for)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", message)
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

    # Statement period extraction
    msg_low = message.lower()
    if any(k in msg_low for k in ["this week", "past week", "7 day", "current week"]):
        entities.period_type = "THIS_WEEK"
    elif any(k in msg_low for k in ["last month", "1 month", "past month", "30 day", "previous month"]):
        entities.period_type = "LAST_MONTH"
    elif any(k in msg_low for k in ["3 month", "quarter", "90 day", "three month"]):
        entities.period_type = "LAST_3_MONTHS"
    elif any(k in msg_low for k in ["6 month", "half year", "180 day", "six month", "half-year"]):
        entities.period_type = "LAST_6_MONTHS"

    # User persona detection
    if any(k in msg_low for k in ["college", "student", "coioolsge", "sstudnet", "university", "freshman", "pocket money"]):
        entities.user_persona = "STUDENT"
    elif any(k in msg_low for k in ["retired", "senior citizen", "pensioner"]):
        entities.user_persona = "RETIRED"

    # Risk profile detection
    if any(k in msg_low for k in ["aggressive", "high risk", "max return", "small cap"]):
        entities.risk_profile = "AGGRESSIVE"
    elif any(k in msg_low for k in ["conservative", "safe", "low risk", "guaranteed"]):
        entities.risk_profile = "CONSERVATIVE"
    elif any(k in msg_low for k in ["moderate", "balanced"]):
        entities.risk_profile = "MODERATE"

    # Stock ticker / symbol detection
    for sym in ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "TATAMOTORS", "ITC", "NIFTY50"]:
        if re.search(r"\b" + sym + r"\b", message, re.IGNORECASE):
            entities.stock_symbol = sym
            break

    # Policy category detection
    if any(k in msg_low for k in ["health", "mediclaim", "hospital", "doctor", "hralth"]):
        entities.policy_category = "HEALTH"
    elif any(k in msg_low for k in ["term life", "pure term", "life insurance", "term plan"]):
        entities.policy_category = "LIFE"
    elif any(k in msg_low for k in ["pmjjby", "pmsby", "ppf", "nps", "apy", "sukanya", "govt scheme", "government"]):
        entities.policy_category = "GOVT_SCHEME"
    elif any(k in msg_low for k in ["fd", "rd", "fixed deposit", "recurring deposit", "deposit rate"]):
        entities.policy_category = "BANKING_DEPOSIT"

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

    # 3. Dynamic Temporal Context Injection (Current Date, Time & Day)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
    current_time_str = now_ist.strftime("%A, %d-%b-%Y %I:%M %p IST")


    # 4. Contextual Step Fulfillment (e.g. User answering a prompt during onboarding or transfer)
    active_wf = context.get("active_workflow", "NONE")

    acc_step = (context.get("account_data") or {}).get("step")
    is_opening_trigger = any(k in clean_text for k in ["open", "savings", "current", "apply", "register", "novabank"])

    # Explicit domain switch, command, question, or out-of-domain detection
    is_interruption_or_switch = (
        any(k in clean_text for k in [
            "balance", "transfer", "send money", "send ₹", "send rs", "card", "freeze", "unfreeze",
            "block", "limit", "loan", "emi", "borrow", "bill", "power", "broadband", "electricity",
            "recharge", "statement", "download", "dispute", "ticket", "complaint", "fraud",
            "sip", "invest", "stock", "shares", "insurance", "policy", "pmjjby", "pmsby",
            "cake", "bake", "recipe", "weather", "help", "who are you", "what can you do", "menu",
            "who am i", "my name"
        ])
        or any(clean_text.startswith(w) for w in ["what", "how", "can", "why", "where", "tell me", "explain", "who", "which", "is", "are", "do", "before"])
    )

    if active_wf == "OPEN_ACCOUNT" and not is_opening_trigger and not is_interruption_or_switch:
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

    # 4b. Contextual Beneficiary Details Continuation
    transfer_data = context.get("transfer_data") or {}
    transfer_step = transfer_data.get("step")
    if active_wf == "TRANSFER_MONEY" and transfer_step in ["ADD_BENEFICIARY", "RESOLVE"]:
        if not is_interruption_or_switch:
            entities = _extract_entities_fast(raw_text)
            return BankingRoutingDecision(
                intent=BankingIntent.TRANSFER_MONEY,
                sub_intent=BankingSubIntent.DOMESTIC_P2P_TRANSFER,
                confidence=0.98,
                negation_detected=False,
                reasoning="Context continuation for active transfer details collection.",
                entities=entities,
                cleaned_message=raw_text
            )

    # 4c. Direct Beneficiary Account & IFSC submission
    fast_entities = _extract_entities_fast(raw_text)
    if fast_entities.beneficiary_account and fast_entities.ifsc_code:
        return BankingRoutingDecision(
            intent=BankingIntent.TRANSFER_MONEY,
            sub_intent=BankingSubIntent.DOMESTIC_P2P_TRANSFER,
            confidence=0.98,
            negation_detected=False,
            reasoning="Direct beneficiary account and IFSC code submission.",
            entities=fast_entities,
            cleaned_message=raw_text
        )

    # 4d. Contextual SIP Mandate Confirmation & Direct Activation Routing
    wealth_data = context.get("wealth_data") or {}
    wealth_step = wealth_data.get("step")
    if active_wf == "WEALTH_ADVISORY" and wealth_step == "CONFIRM":
        if any(k == clean_text or clean_text.startswith(k) for k in ["yes", "confirm", "proceed", "sure", "authorize", "activate", "yup", "ok", "okay"]):
            return BankingRoutingDecision(
                intent=BankingIntent.CONFIRM_YES,
                confidence=0.99,
                negation_detected=False,
                reasoning="User confirmed SIP mandate authorization.",
                entities=fast_entities,
                cleaned_message=raw_text
            )
        elif any(k == clean_text or clean_text.startswith(k) for k in ["no", "cancel", "stop", "abort", "don't", "dont", "never"]):
            return BankingRoutingDecision(
                intent=BankingIntent.CONFIRM_NO,
                confidence=0.99,
                negation_detected=False,
                reasoning="User declined SIP mandate authorization.",
                entities=fast_entities,
                cleaned_message=raw_text
            )

    is_sip_mandate_trigger = any(k in clean_text for k in [
        "set up automated", "setup automated", "activate sip", "activate mandate", "start sip",
        "set up sip", "setup sip", "sip mandate", "monthly sip mandate", "automated monthly sip",
        "activate the sip"
    ])
    if is_sip_mandate_trigger and not any(clean_text.startswith(w) for w in ["what", "how", "why", "where"]):
        return BankingRoutingDecision(
            intent=BankingIntent.WEALTH_ADVISORY,
            sub_intent=BankingSubIntent.SIP_MANDATE_SETUP,
            confidence=0.99,
            negation_detected=False,
            reasoning="Direct SIP mandate activation request.",
            entities=fast_entities,
            cleaned_message=raw_text
        )

    # 5. LLM Structured Routing Prompt (Segregated in gateway.llm.prompts)
    system_prompt = build_banking_router_prompt(current_time_str, active_wf)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=raw_text)
    ]

    try:
        response = await llm_gateway.invoke_chat(messages, model_tier="routing")
        raw_content = response.content.strip()
        if "```json" in raw_content:
            raw_content = raw_content.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_content:
            raw_content = raw_content.split("```")[1].split("```")[0].strip()
        data = json.loads(raw_content)

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
        elif any(k in clean_text for k in ["invest", "invetsmnet", "sip", "mutual fund", "wealth", "1 cr", "crore", "savings of"]):
            fallback_intent = BankingIntent.WEALTH_ADVISORY
            if any(k in clean_text for k in ["mandate", "activate", "set up", "setup", "start sip"]):
                fallback_sub = BankingSubIntent.SIP_MANDATE_SETUP
            else:
                fallback_sub = BankingSubIntent.SIP_PLANNING

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
