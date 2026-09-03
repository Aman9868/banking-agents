"""Prompt injection guardrails and output validation module."""

import re
from typing import Tuple

# Known adversarial jailbreak and system-prompt extraction heuristics
PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions",
    r"disregard\s+(?:all\s+)?rules",
    r"you\s+are\s+now\s+(?:a|an)\s+(?:unrestricted|developer|admin|superuser|god)",
    r"override\s+(?:system|safety|security)\s+policy",
    r"print\s+(?:your\s+)?(?:system\s+prompt|instructions|initial\s+prompt)",
    r"execute\s+command\s*:\s*(?:rm|drop|delete|curl|wget)",
    r"system\s*:\s*you\s+must",
    r"<\|\s*im_start\s*\|>",
    r"sudo\s+transfer",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in PROMPT_INJECTION_PATTERNS]


class SecurityViolationError(Exception):
    """Raised when security guardrails detect an adversarial or forbidden payload."""
    pass


def inspect_input(user_prompt: str) -> Tuple[bool, str]:
    """
    Validates user input against prompt injection and malicious override attempts.
    Returns (is_safe, reason).
    """
    if not user_prompt or not isinstance(user_prompt, str):
        return True, ""

    # Check for prompt injection patterns
    for pattern in COMPILED_PATTERNS:
        if pattern.search(user_prompt):
            return False, f"Potentially adversarial prompt pattern detected: {pattern.pattern}"

    # Check for excessive repetition / token bombing attack
    if len(user_prompt) > 4000:
        return False, "Input exceeds maximum allowed length for banking conversation (4000 characters)"

    return True, ""


def inspect_output(llm_output: str) -> str:
    """
    Sanitizes LLM output to ensure no leaked internal system tokens,
    stack traces, or unauthorized execution commands are rendered.
    """
    if not llm_output or not isinstance(llm_output, str):
        return ""

    # Strip dangerous tokens
    cleaned = llm_output.replace("<|im_end|>", "").replace("<|im_start|>", "")

    # Prevent leakage of raw database passwords or internal connection strings
    cleaned = re.sub(r"postgresql(?:\+asyncpg)?://[^@]+@[^\s/]+/\w+", "[DATABASE_CONNECTION_REDACTED]", cleaned)

    return cleaned

