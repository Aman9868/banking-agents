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

    # 2b. Deterministic Gratitude & Appreciation fast paths ("thank you", "thanks", "thanku", "thx")
    gratitude_tokens = [
        "thank you", "thanks", "thanku", "thx", "ty", "thank u", "many thanks",
        "great thanks", "thanks a lot", "thank you so much", "thank u so much",
        "thanks bot", "thnx", "appreciate it", "thankyou", "thanks a million",
        "thanks!", "thank you!", "thanku!", "thx!"
    ]
    if (
        clean_text in gratitude_tokens
        or clean_text.rstrip("!.,") in gratitude_tokens
        or any(clean_text.startswith(p) for p in ["thank you", "thanks", "thanku", "appreciate it", "thank u"])
    ):
        return BankingRoutingDecision(
            intent=BankingIntent.GENERAL_CONVERSATION,
            sub_intent=BankingSubIntent.THANK_YOU,
            confidence=1.0,
            negation_detected=False,
            reasoning="Customer expressed gratitude or appreciation for banking assistance.",
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

    # Fast multi-account / list accounts inquiry check (e.g. "how many account i ahve", "my accounts")
    acc_list_triggers = [
        "how many account", "how many accounts", "how many acc", "how many accs",
        "how many account i have", "how many accounts i have", "how many account i ahve", "how many accounts do i have",
        "how many account do i have", "how many accounts do i got", "how many acc i have",
        "list my account", "list my accounts", "list accounts", "list account",
        "show my accounts", "show my account", "show accounts", "show account",
        "what accounts do i have", "what account do i have", "what are my accounts", "which accounts do i have",
        "my accounts", "all my accounts", "all accounts", "my account list",
        "account portfolio", "portfolio of accounts", "account summary", "view my accounts", "view accounts"
    ]
    is_acc_keyword = any(w in clean_text for w in ["account", "accounts", "acocunt", "acocunts", "acc", "accs"])
    is_count_or_list_keyword = any(w in clean_text for w in ["how many", "list", "show", "what", "which", "tell", "view", "all my", "all"])
    if (
        any(q in clean_text for q in acc_list_triggers)
        or clean_text in ["accounts", "my accounts", "my accs", "acc list", "account list"]
        or (is_acc_keyword and is_count_or_list_keyword and not any(k in clean_text for k in ["open", "create", "new", "apply", "register", "transfer", "send"]))
    ):
        return BankingRoutingDecision(
            intent=BankingIntent.BALANCE_CHECK,
            sub_intent=BankingSubIntent.LIST_ACCOUNTS,
            confidence=1.0,
            negation_detected=False,
            reasoning="Direct user inquiry to list registered bank accounts and total portfolio balance.",
            cleaned_message=raw_text
        )

    # Fast balance query check (Interruption-safe before contextual steps)
    bal_triggers = [
        "what is my balance", "what's my balance", "check balance", "current balance",
        "account balance", "how much money do i have", "how much is in my account",
        "show balance", "balance check", "view balance", "my balance", "check my balance"
    ]
    if any(q in clean_text for q in bal_triggers) or clean_text in ["balance", "bal", "my bal"]:
        return BankingRoutingDecision(
            intent=BankingIntent.BALANCE_CHECK,
            sub_intent=BankingSubIntent.OTHER,
            confidence=1.0,
            negation_detected=False,
            reasoning="Direct user inquiry for account balance.",
            cleaned_message=raw_text
        )

    # Fast Web / Financial Search check
    web_search_triggers = [
        "search web for", "search web", "web search", "google search", "search internet",
        "latest rbi repo rate", "rbi repo rate", "current repo rate", "repo rate",
        "dicgc insurance limit", "section 80ccd limit", "upi daily limit"
    ]
    if any(q in clean_text for q in web_search_triggers) or (clean_text.startswith("search ") and not any(w in clean_text for w in ["statement", "transaction", "faq", "ticket"])):
        return BankingRoutingDecision(
            intent=BankingIntent.KNOWLEDGE_FAQ,
            sub_intent=BankingSubIntent.WEB_SEARCH,
            confidence=1.0,
            negation_detected=False,
            reasoning="User inquiry requesting live web or regulatory financial search.",
            cleaned_message=raw_text
        )


    # Fast KYC status inquiry check
    kyc_triggers = [
        "is my kyc done", "is kyc done", "my kyc status", "kyc status", "check kyc",
        "check my kyc", "is my account verified", "am i kyc verified", "kyc verification status"
    ]
    if any(q in clean_text for q in kyc_triggers):
        return BankingRoutingDecision(
            intent=BankingIntent.OPEN_ACCOUNT,
            sub_intent=BankingSubIntent.KYC_STATUS,
            confidence=1.0,
            negation_detected=False,
            reasoning="User inquiry for account KYC and verification status.",
            cleaned_message=raw_text
        )

    # Fast Account Statement inquiry check
    stmt_triggers = [
        "statement", "sattemnet", "statemnt", "statment", "account statement", "pdf statement",
        "download statement", "send statement", "get statement", "email statement", "bank statement"
    ]
    if any(q in clean_text for q in stmt_triggers):
        entities = _extract_entities_fast(raw_text)
        return BankingRoutingDecision(
            intent=BankingIntent.STATEMENT_REQUEST,
            sub_intent=BankingSubIntent.DOWNLOAD_STATEMENT,
            confidence=1.0,
            negation_detected=False,
            reasoning=f"User requested bank account statement (Period: {entities.period_type or 'LAST_6_MONTHS'}).",
            entities=entities,
            cleaned_message=raw_text
        )

    # Fast Transaction Inquiry, Diagnosis & Transfer Tracking check
    decline_triggers = [
        "why was my last transaction declined", "why is my last transaction declined",
        "why was my transaction declined", "why was it declined", "why did transaction fail",
        "why my transfer failed", "why was it rejected", "why did it get declined",
        "reason for decline", "reason for failure", "explain decline"
    ]
    explain_triggers = [
        "explain my last transaction", "explain my transaction", "explain transaction",
        "explain my spending", "why did my balance decrease", "why balance decreased"
    ]
    is_dispute_keyword = any(k in clean_text for k in ["card", "upi", "merchant", "pos", "atm", "swipe", "unauthorized", "fraud", "stolen", "store"])
    if not is_dispute_keyword and (any(q in clean_text for q in decline_triggers) or (("why" in clean_text or "reason" in clean_text) and any(w in clean_text for w in ["decline", "declined", "failed", "reject", "rejected"]))):
        entities = _extract_entities_fast(raw_text)
        return BankingRoutingDecision(
            intent=BankingIntent.TRANSACTION_INQUIRY,
            sub_intent=BankingSubIntent.EXPLAIN_DECLINE,
            confidence=1.0,
            negation_detected=False,
            reasoning="User inquiry diagnosing transaction decline root cause and next steps.",
            entities=entities,
            cleaned_message=raw_text
        )
    if any(q in clean_text for q in explain_triggers):
        entities = _extract_entities_fast(raw_text)
        return BankingRoutingDecision(
            intent=BankingIntent.TRANSACTION_INQUIRY,
            sub_intent=BankingSubIntent.EXPLAIN_LAST_TXN,
            confidence=1.0,
            negation_detected=False,
            reasoning="User inquiry requesting explanation of latest transaction or spending impact.",
            entities=entities,
            cleaned_message=raw_text
        )

    txn_triggers = [
        "latest amount i transferred", "latest amount transferred", "last transfer",
        "latest transfer", "what was my last transfer", "what was the latest amount",
        "last amount transferred", "last transaction", "latest transaction",
        "recent transfers", "transfer history", "transaction history", "track transfer",
        "transfer status", "check my transfers", "where is my transfer", "did my transfer go through"
    ]
    is_txn_inquiry = any(q in clean_text for q in txn_triggers) or (
        ("transfer" in clean_text or "amount" in clean_text or "trasnfer" in clean_text) and any(w in clean_text for w in ["latest", "last", "recent", "status", "track", "history", "laets"])
    )
    if is_txn_inquiry or (re.search(r"\b(TXN-[A-Za-z0-9]+)\b", raw_text, re.IGNORECASE) and not any(w in clean_text for w in ["unauthorized", "stolen", "fraud", "dispute"])):
        sub = BankingSubIntent.LATEST_TRANSFER if any(w in clean_text for w in ["latest", "last", "laets"]) else (
            BankingSubIntent.TRACK_TRANSACTION if "TXN-" in raw_text.upper() else BankingSubIntent.TRANSFER_HISTORY
        )
        entities = _extract_entities_fast(raw_text)
        return BankingRoutingDecision(
            intent=BankingIntent.TRANSACTION_INQUIRY,
            sub_intent=sub,
            confidence=1.0,
            negation_detected=False,
            reasoning="User inquiry for transfer tracking, latest transfer, or transaction history.",
            entities=entities,
            cleaned_message=raw_text
        )

    # Fast Wealth Advisory, SIP Planning & Stock Market check
    wealth_triggers = [
        "sip", "sidp", "mutual fund", "mutual funds", "best sip", "sip plan", "start sip",
        "invest", "investment", "wealth plan", "grow money", "compounding", "portfolio"
    ]
    stock_triggers = [
        "best stock", "best stocks", "stocks to buy", "share market", "stock market",
        "stock price", "share price", "live price", "quote for", "market price", "buy stock"
    ]
    is_student_persona = any(s in clean_text for s in ["college student", "coioolsge", "sstudnet", "college", "student"])
    is_wealth_query = (
        any(q in clean_text for q in wealth_triggers)
        or (is_student_persona and any(w in clean_text for w in ["monthly", "income", "money", "save", "invest", "amount", "amoiut"]))
        or any(q in clean_text for q in stock_triggers)
    )
    if is_wealth_query:
        entities = _extract_entities_fast(raw_text)
        if any(q in clean_text for q in stock_triggers) or (entities.stock_symbol and not any(w in clean_text for w in ["sip", "mutual fund"])):
            sub = BankingSubIntent.STOCK_MARKET_SEARCH
            reasoning = "User requested stock market research or live quote analysis."
        elif any(w in clean_text for w in ["recommend", "portfolio", "allocation"]):
            sub = BankingSubIntent.PORTFOLIO_RECOMMENDATION
            reasoning = "User requested portfolio allocation strategy."
        else:
            sub = BankingSubIntent.SIP_PLANNING
            reasoning = "User requested SIP investment planning and compounding advisory."

        return BankingRoutingDecision(
            intent=BankingIntent.WEALTH_ADVISORY,
            sub_intent=sub,
            confidence=1.0,
            negation_detected=False,
            reasoning=reasoning,
            entities=entities,
            cleaned_message=raw_text
        )

    # Fast Policy & Insurance Inquiry check
    policy_triggers = [
        "health insurance", "life insurance", "mediclaim", "pmjjby", "pmsby", "ppf", "nps", "apy",
        "sukanya", "general policy", "banking policy", "insurance policy", "best policy", "tell policy",
        "show policies", "policy", "policies", "poilcuy", "poclice", "hralth", "insurance"
    ]
    is_policy_query = (
        any(q in clean_text for q in policy_triggers)
        and not any(w in clean_text for w in ["transfer policy", "card policy", "password policy", "security policy", "policy_check"])
    )
    if is_policy_query:
        entities = _extract_entities_fast(raw_text)
        cat = entities.policy_category or "ALL"
        if cat == "HEALTH":
            sub = BankingSubIntent.HEALTH_INSURANCE
        elif cat == "LIFE":
            sub = BankingSubIntent.LIFE_INSURANCE
        elif cat == "GOVT_SCHEME":
            sub = BankingSubIntent.GOVERNMENT_SCHEME
        else:
            sub = BankingSubIntent.BANKING_POLICY

        return BankingRoutingDecision(
            intent=BankingIntent.POLICY_INQUIRY,
            sub_intent=sub,
            confidence=1.0,
            negation_detected=False,
            reasoning=f"User inquiry for {cat} insurance or banking policy catalog.",
            entities=entities,
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

    # 4b. Contextual Beneficiary Details Continuation
    transfer_data = context.get("transfer_data") or {}
    transfer_step = transfer_data.get("step")
    if active_wf == "TRANSFER_MONEY" and transfer_step in ["ADD_BENEFICIARY", "RESOLVE"]:
        is_interruption_or_question = any(clean_text.startswith(w) for w in ["what ", "how ", "can ", "why ", "where ", "tell me "])
        if not is_interruption_or_question:
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

5. TRANSFER TRACKING & TRANSACTION INQUIRY:
   Queries asking about past transfers, latest transferred amount, transaction history, or tracking a transfer (e.g. 'what was my last transfer', 'latest amount transferred', 'status of transfer') -> TRANSACTION_INQUIRY.

6. MULTI-ACCOUNT & BALANCE QUERIES:
   Queries asking about how many accounts the user has, listing accounts, or portfolio summary -> BALANCE_CHECK with sub_intent LIST_ACCOUNTS.
   Queries asking for live web search or external banking/economic/RBI questions -> KNOWLEDGE_FAQ with sub_intent WEB_SEARCH.

Allowed Intents:
TRANSFER_MONEY, OPEN_ACCOUNT, BALANCE_CHECK, TRANSACTION_INQUIRY, STATEMENT_REQUEST, CARD_ACTION, LOAN_ACTION, PAYMENT_ACTION,
SPENDING_INSIGHTS, WEALTH_ADVISORY, POLICY_INQUIRY, KNOWLEDGE_FAQ, SUPPORT_DISPUTE, TEMPORAL_QUERY, CONFIRM_YES, CONFIRM_NO, GENERAL_CONVERSATION.


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
