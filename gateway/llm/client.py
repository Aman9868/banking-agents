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
        if "classify the intent" in system_instruction.lower() or model_tier == "routing":
            if any(k in text_lower for k in ["transfer", "send money", "pay "]):
                return json.dumps({
                    "intent": "TRANSFER_MONEY",
                    "confidence": 0.95
                })
            elif any(k in text_lower for k in ["open", "savings account", "current account", "open account"]):
                return json.dumps({
                    "intent": "OPEN_ACCOUNT",
                    "confidence": 0.95
                })
            elif any(k in text_lower for k in ["balance", "how much money", "account balance"]):
                return json.dumps({
                    "intent": "BALANCE_CHECK",
                    "confidence": 0.98
                })
            elif any(k in text_lower for k in ["declined", "dispute", "failed", "unauthorized", "why was"]):
                return json.dumps({
                    "intent": "SUPPORT_DISPUTE",
                    "confidence": 0.95
                })
            elif text_lower in ["yes", "confirm", "proceed", "sure", "yep", "do it"]:
                return json.dumps({
                    "intent": "CONFIRM_YES",
                    "confidence": 0.99
                })
            elif text_lower in ["no", "cancel", "stop", "nevermind", "abort"]:
                return json.dumps({
                    "intent": "CONFIRM_NO",
                    "confidence": 0.99
                })
            else:
                return json.dumps({
                    "intent": "GENERAL_CONVERSATION",
                    "confidence": 0.80
                })

        # Conversational generation fallback
        return f"I understand your request regarding '{last_user_msg}'. How can I assist further?"


llm_gateway = LLMGateway()

