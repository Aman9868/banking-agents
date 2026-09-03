"""Intent classification and entity slot extraction router using LLM Gateway (Phases 1-7)."""

import json
import re
from typing import Dict, Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from gateway.llm.client import llm_gateway
import structlog

logger = structlog.get_logger(__name__)


ROUTING_SYSTEM_PROMPT = """You are an enterprise banking intent classification engine.
Given the customer message, classify the primary intent into one of:
- TRANSFER_MONEY: User wants to transfer or send money to a beneficiary.
- OPEN_ACCOUNT: User wants to open a new savings or current bank account.
- BALANCE_CHECK: User wants to check balance or account status.
- CARD_ACTION: User wants to freeze, unfreeze, replace, set limits, or view cards.
- LOAN_ACTION: User asks about loans, EMI calculation, loan eligibility, or applying for a loan.
- PAYMENT_ACTION: User wants to pay bills (electricity, water, broadband, credit card) or UPI.
- SPENDING_INSIGHTS: User asks about spending breakdown, monthly expenses, subscriptions, or cashflow projections.
- KNOWLEDGE_FAQ: General questions on interest rates, fees, ATM charges, or banking rules.
- SUPPORT_DISPUTE: User is asking about a declined/failed transaction, dispute, or issue.
- CONFIRM_YES: User says yes, confirm, agree, or proceed.
- CONFIRM_NO: User says no, cancel, stop, or decline.
- GENERAL_CONVERSATION: Small talk, greetings, or help menu.

Respond ONLY with a JSON object: {"intent": "<INTENT_NAME>", "confidence": 0.0 - 1.0}"""


async def classify_intent(message: str) -> str:
    """Classifies user intent across all specialized banking capability areas."""
    text = message.lower().strip()

    # Fast heuristics / regex pre-classifier
    if any(k in text for k in ["spending", "spend", "expenses", "expense", "subscriptions", "subscription", "recurring", "cashflow", "how much did i spend", "budget"]):
        return "SPENDING_INSIGHTS"
    if any(k in text for k in ["freeze", "unfreeze", "stolen card", "lost card", "card limit", "replace card", "my cards", "card status"]):
        return "CARD_ACTION"
    if any(k in text for k in ["emi", "personal loan", "home loan", "loan eligibility", "apply loan", "calculate emi", "car loan"]):
        return "LOAN_ACTION"
    if any(k in text for k in ["electricity bill", "pay bill", "broadband bill", "utility", "pay airtel", "pay tata", "upi"]):
        return "PAYMENT_ACTION"
    if any(k in text for k in ["interest rate", "fixed deposit", "atm charges", "fees for", "what are the charges", "policy on"]):
        return "KNOWLEDGE_FAQ"
    if any(k in text for k in ["transfer", "send money", "pay rahul", "send 5000", "send "]):
        return "TRANSFER_MONEY"
    if any(k in text for k in ["open a savings", "open account", "open current", "i want to open", "open a new account", "open bank account", "new account", "create account", "register account", "open savings"]):
        return "OPEN_ACCOUNT"
    if any(k in text for k in ["balance", "account balance", "how much money"]):
        return "BALANCE_CHECK"
    if any(k in text for k in ["declined", "dispute", "failed", "unauthorized", "why was"]):
        return "SUPPORT_DISPUTE"
    if text in ["yes", "confirm", "proceed", "yep", "do it", "sure"]:
        return "CONFIRM_YES"
    if text in ["no", "cancel", "stop", "abort"]:
        return "CONFIRM_NO"

    messages = [
        SystemMessage(content=ROUTING_SYSTEM_PROMPT),
        HumanMessage(content=message)
    ]
    response = await llm_gateway.invoke_chat(messages, model_tier="routing")
    try:
        data = json.loads(response.content.strip())
        return data.get("intent", "GENERAL_CONVERSATION")
    except Exception:
        return "GENERAL_CONVERSATION"


async def extract_slots(message: str) -> Dict[str, Any]:
    """Extracts entity slots such as amounts, tenures, billers, card types, and beneficiaries."""
    slots: Dict[str, Any] = {}

    # Extract amount (check lakh/crore notation first)
    lakh_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:lakh|lac)s?", message, re.IGNORECASE)
    if lakh_match:
        slots["amount"] = float(lakh_match.group(1)) * 100000.0
    else:
        amount_match = re.search(r"(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)", message, re.IGNORECASE)
        if amount_match:
            val_str = amount_match.group(1).replace(",", "")
            try:
                val = float(val_str)
                if val > 0:
                    slots["amount"] = val
            except ValueError:
                pass

    # Extract beneficiary
    to_match = re.search(r"\bto\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", message)
    if to_match:
        slots["beneficiary_name"] = to_match.group(1).strip()

    # Extract tenure (e.g. 3 years, 36 months, 2 yr)
    tenure_match = re.search(r"(\d+)\s*(?:years?|yrs?)", message, re.IGNORECASE)
    if tenure_match:
        slots["tenure_months"] = int(tenure_match.group(1)) * 12
    else:
        month_match = re.search(r"(\d+)\s*(?:months?|mths?)", message, re.IGNORECASE)
        if month_match:
            slots["tenure_months"] = int(month_match.group(1))

    # Extract card type
    if "credit" in message.lower():
        slots["card_type"] = "CREDIT"
    elif "debit" in message.lower():
        slots["card_type"] = "DEBIT"

    # Extract biller name
    for b in ["Tata Power", "Airtel Broadband", "HDFC Credit Card", "Tata", "Airtel"]:
        if b.lower() in message.lower():
            slots["biller_name"] = b
            break

    # Extract DOB
    dob_match = re.search(r"\b(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b", message)
    if dob_match:
        slots["dob"] = dob_match.group(1).strip()

    return slots
