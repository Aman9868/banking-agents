"""PII (Personally Identifiable Information) masking and sanitization module."""

import re

# Regex patterns for sensitive financial and identity data
CARD_PATTERN = re.compile(r"\b(?:\d{4}[ -]?){3}(\d{4})\b")
ACCOUNT_PATTERN = re.compile(r"\b([A-Z]{0,4}\d{4,6})(\d{4})\b")
EMAIL_PATTERN = re.compile(r"([a-zA-Z0-9_.+-]{1,3})[a-zA-Z0-9_.+-]*@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)")
PHONE_PATTERN = re.compile(r"\b(?:\+?\d{1,3}[- ]?)?(\d{2,3})\d{4,6}(\d{2,4})\b")


def mask_card_number(text: str) -> str:
    """Mask 16-digit card numbers to ****-****-****-1234."""
    return CARD_PATTERN.sub(r"****-****-****-\1", text)


def mask_account_number(text: str) -> str:
    """Mask account numbers to ****1234."""
    return ACCOUNT_PATTERN.sub(r"****\2", text)


def mask_email(text: str) -> str:
    """Mask email addresses to a***@domain.com."""
    return EMAIL_PATTERN.sub(r"\1***@\2", text)


def mask_phone(text: str) -> str:
    """Mask phone numbers preserving prefix and last 2 digits."""
    return PHONE_PATTERN.sub(r"\1******\2", text)


def sanitize_pii(text: str) -> str:
    """Apply comprehensive PII masking to input text for logging or customer display."""
    if not isinstance(text, str):
        return text
    masked = mask_card_number(text)
    masked = mask_account_number(masked)
    masked = mask_email(masked)
    masked = mask_phone(masked)
    return masked

