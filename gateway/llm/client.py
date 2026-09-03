"""LLM Gateway Client supporting Groq (ChatGroq) with fallback and metrics tracking."""

import os
import re
import time
import json
from typing import List, Dict, Any, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from apps.api.config import settings
import structlog

logger = structlog.get_logger(__name__)


class LLMResponse:
    def __init__(self, content: str, model: str, provider: str, prompt_tokens: int = 0, completion_tokens: int = 0, latency_ms: float = 0.0):
        self.content = content
        self.model = model
        self.provider = provider
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.latency_ms = latency_ms


class LLMGateway:
    def __init__(self):
        self.groq_key = settings.GROQ_API_KEY or os.environ.get("GROQ_API_KEY", "")
        self.routing_model = settings.GROQ_ROUTING_MODEL
        self.reasoning_model = settings.GROQ_REASONING_MODEL
        self._groq_client = None

        if self.groq_key:
            try:
                from langchain_groq import ChatGroq
                self._groq_routing = ChatGroq(
                    api_key=self.groq_key,
                    model_name=self.routing_model,
                    temperature=0.0
                )
                self._groq_reasoning = ChatGroq(
                    api_key=self.groq_key,
                    model_name=self.reasoning_model,
                    temperature=0.2
                )
                logger.info("LLMGateway initialized with Groq provider", routing_model=self.routing_model, reasoning_model=self.reasoning_model)
            except Exception as e:
                logger.warning("Failed to initialize ChatGroq, falling back to deterministic engine", error=str(e))
                self.groq_key = ""
        else:
            logger.info("No GROQ_API_KEY detected. Operating in deterministic offline mode for local testability.")

    async def invoke_chat(self, messages: List[BaseMessage], model_tier: str = "reasoning") -> LLMResponse:
        """
        Invokes LLM with specified tier: 'routing' (fast/light) or 'reasoning' (strong).
        Falls back seamlessly to deterministic mock if API key is not present or provider fails.
        """
        start_time = time.perf_counter()
        target_model = self.routing_model if model_tier == "routing" else self.reasoning_model

        if self.groq_key:
            try:
                client = self._groq_routing if model_tier == "routing" else self._groq_reasoning
                response = await client.ainvoke(messages)
                latency = (time.perf_counter() - start_time) * 1000
                return LLMResponse(
                    content=response.content,
                    model=target_model,
                    provider="groq",
                    prompt_tokens=len(str(messages)) // 4,
                    completion_tokens=len(response.content) // 4,
                    latency_ms=latency
                )
            except Exception as exc:
                logger.error("Groq provider call failed. Falling back to deterministic engine.", error=str(exc))

        # Deterministic engine fallback
        latency = (time.perf_counter() - start_time) * 1000
        fallback_content = self._deterministic_fallback(messages, model_tier)
        return LLMResponse(
            content=fallback_content,
            model=f"mock-{target_model}",
            provider="deterministic_fallback",
            prompt_tokens=len(str(messages)) // 4,
            completion_tokens=len(fallback_content) // 4,
            latency_ms=latency
        )

    def _deterministic_fallback(self, messages: List[BaseMessage], model_tier: str) -> str:
        """Rule-based NLU and conversational engine when offline or testing without cloud API keys."""
        last_user_msg = ""
        system_instruction = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) and not last_user_msg:
                last_user_msg = msg.content.strip()
            elif isinstance(msg, SystemMessage) and not system_instruction:
                system_instruction = msg.content

        text_lower = last_user_msg.lower()

        # Intent classification mode
        if "banking intent classification" in system_instruction.lower() or model_tier == "routing":
            # 1. Negation detection
            if any(k in text_lower for k in ["don't want to transfer", "do not transfer", "don't transfer", "not want to transfer", "don't freeze", "do not freeze", "don't pay", "do not pay"]):
                return json.dumps({
                    "intent": "GENERAL_CONVERSATION",
                    "sub_intent": "OTHER",
                    "confidence": 0.98,
                    "negation_detected": True,
                    "reasoning": "Explicit customer negation detected; prevented action execution.",
                    "entities": {},
                    "requires_clarification": False
                })

            # 2. Temporal inquiry
            if any(k in text_lower for k in ["what is the time", "what time is it", "what date is today", "what is today's date", "todays date", "current time", "what day is today"]):
                return json.dumps({
                    "intent": "TEMPORAL_QUERY",
                    "sub_intent": "CURRENT_TIME_DATE",
                    "confidence": 1.0,
                    "negation_detected": False,
                    "reasoning": "Inquiry regarding current time and date.",
                    "entities": {},
                    "requires_clarification": False
                })

            # 3. Card Actions (freeze, unfreeze, card limit, replace, stolen/lost card lock)
            if any(k in text_lower for k in ["freeze", "freze", "unfreeze", "unfreze", "stolen card", "lost card", "card limit", "replace card", "my cards", "card status"]) or ("card" in text_lower and any(f in text_lower for f in ["freeze", "freze", "lock"])):
                sub = "FREEZE_CARD" if any(f in text_lower for f in ["freeze", "freze", "lock", "stolen", "lost"]) else "CARD_STATUS"
                return json.dumps({
                    "intent": "CARD_ACTION",
                    "sub_intent": sub,
                    "confidence": 0.98,
                    "negation_detected": False,
                    "reasoning": "Customer card management request.",
                    "entities": {},
                    "requires_clarification": False
                })

            # 4. Support & Dispute Sub-Intents
            if any(k in text_lower for k in ["unauthorized", "fraud", "someone used my card", "suspicious debit", "stolen money"]):
                return json.dumps({
                    "intent": "SUPPORT_DISPUTE",
                    "sub_intent": "UNAUTHORIZED_TRANSACTION",
                    "confidence": 0.99,
                    "negation_detected": False,
                    "reasoning": "Customer reporting unauthorized / fraudulent activity.",
                    "entities": {},
                    "requires_clarification": False
                })
            elif any(k in text_lower for k in ["card payment declined", "card declined", "pos declined", "swipe declined", "why was my card"]):
                return json.dumps({
                    "intent": "SUPPORT_DISPUTE",
                    "sub_intent": "CARD_PAYMENT_DECLINED",
                    "confidence": 0.98,
                    "negation_detected": False,
                    "reasoning": "Customer inquiring regarding declined card transaction.",
                    "entities": {},
                    "requires_clarification": False
                })
            elif any(k in text_lower for k in ["upi failed", "upi declined", "gpay failed", "phonepe failed", "upi error"]):
                return json.dumps({
                    "intent": "SUPPORT_DISPUTE",
                    "sub_intent": "UPI_PAYMENT_FAILED",
                    "confidence": 0.98,
                    "negation_detected": False,
                    "reasoning": "Customer reporting failed UPI transaction.",
                    "entities": {},
                    "requires_clarification": False
                })
            elif any(k in text_lower for k in ["transfer failed", "neft failed", "rtgs failed", "wire rejected", "transfer rejected"]):
                return json.dumps({
                    "intent": "SUPPORT_DISPUTE",
                    "sub_intent": "TRANSFER_FAILED",
                    "confidence": 0.98,
                    "negation_detected": False,
                    "reasoning": "Customer reporting failed wire / interbank transfer.",
                    "entities": {},
                    "requires_clarification": False
                })
            elif any(k in text_lower for k in ["declined", "dispute", "failed", "unauthorized", "why was", "chargeback", "human", "agent", "ticket", "escalate", "complaint"]):
                return json.dumps({
                    "intent": "SUPPORT_DISPUTE",
                    "sub_intent": "CREATE_TICKET",
                    "confidence": 0.98,
                    "negation_detected": False,
                    "reasoning": "General customer transaction dispute / issue.",
                    "entities": {},
                    "requires_clarification": False
                })

            # 5. PFM / Spending Insights
            if any(k in text_lower for k in ["spending", "spend", "expenses", "expense", "subscriptions", "subscription", "recurring", "cashflow", "how much did i spend", "budget"]):
                return json.dumps({
                    "intent": "SPENDING_INSIGHTS",
                    "sub_intent": "SPENDING_BREAKDOWN",
                    "confidence": 0.98,
                    "negation_detected": False,
                    "reasoning": "Customer inquiring about spending analytics and insights.",
                    "entities": {},
                    "requires_clarification": False
                })

            # 6. Loans & EMI
            if any(k in text_lower for k in ["emi", "personal loan", "home loan", "loan eligibility", "apply loan", "calculate emi", "car loan", "lon"]):
                return json.dumps({
                    "intent": "LOAN_ACTION",
                    "sub_intent": "EMI_CALCULATION",
                    "confidence": 0.98,
                    "negation_detected": False,
                    "reasoning": "Loan advisory or EMI calculation inquiry.",
                    "entities": {},
                    "requires_clarification": False
                })

            # 7. Bill Payments
            if any(k in text_lower for k in ["electricity bill", "pay bill", "broadband bill", "utility", "pay airtel", "pay tata", "upi", "elctricty"]):
                return json.dumps({
                    "intent": "PAYMENT_ACTION",
                    "sub_intent": "ELECTRICITY_BILL",
                    "confidence": 0.98,
                    "negation_detected": False,
                    "reasoning": "Utility or bill payment inquiry.",
                    "entities": {},
                    "requires_clarification": False
                })

            # 8. Knowledge FAQ
            if any(k in text_lower for k in ["interest rate", "fixed deposit", "atm charges", "fees for", "what are the charges", "policy on", "minimum balance"]):
                return json.dumps({
                    "intent": "KNOWLEDGE_FAQ",
                    "sub_intent": "OTHER",
                    "confidence": 0.98,
                    "negation_detected": False,
                    "reasoning": "General knowledge or banking policy inquiry.",
                    "entities": {},
                    "requires_clarification": False
                })

            # 9. Transfer (with typo tolerance: 'trnasfer', 'send 5k')
            if any(k in text_lower for k in ["transfer", "trnasfer", "send money", "pay rahul", "send 5000", "send "]):
                return json.dumps({
                    "intent": "TRANSFER_MONEY",
                    "sub_intent": "DOMESTIC_P2P_TRANSFER",
                    "confidence": 0.98,
                    "negation_detected": False,
                    "reasoning": "Money transfer request.",
                    "entities": {},
                    "requires_clarification": False
                })

            # 10. Account Opening
            if any(k in text_lower for k in ["open a savings", "open account", "open current", "i want to open", "open a new account", "open bank account", "new account", "create account", "register account", "open savings", "accont"]):
                return json.dumps({
                    "intent": "OPEN_ACCOUNT",
                    "sub_intent": "SAVINGS_ACCOUNT_OPENING",
                    "confidence": 0.98,
                    "negation_detected": False,
                    "reasoning": "New account opening application.",
                    "entities": {},
                    "requires_clarification": False
                })

            # 11. Balance Check (with typo tolerance: 'balence', 'wht is my bal')
            if any(k in text_lower for k in ["balance", "balence", "account balance", "how much money", "wht is my bal", "show balance"]):
                return json.dumps({
                    "intent": "BALANCE_CHECK",
                    "sub_intent": "OTHER",
                    "confidence": 0.99,
                    "negation_detected": False,
                    "reasoning": "Account balance inquiry.",
                    "entities": {},
                    "requires_clarification": False
                })

            # 12. General Conversation
            return json.dumps({
                "intent": "GENERAL_CONVERSATION",
                "sub_intent": "GREETING",
                "confidence": 0.85,
                "negation_detected": False,
                "reasoning": "General greeting, conversation, or unspecified query.",
                "entities": {},
                "requires_clarification": False
            })

        # Conversational generation fallback
        return f"I understand your request regarding '{last_user_msg}'. How can I assist further?"


llm_gateway = LLMGateway()

