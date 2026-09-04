"""Validation engine for banking entities (Account Numbers, IFSC Codes, Amounts)."""

import re
from typing import Tuple, Optional


def validate_account_number(account_number: str) -> Tuple[bool, str, Optional[str]]:
    """
    Validates Indian bank account numbers.
    Accepts:
      - Standard 9 to 18 digit numeric accounts.
      - Alphanumeric accounts with bank prefix (e.g. SB64237377, NOVA10001234).
    Returns:
      (is_valid, cleaned_account_number, error_message_if_invalid)
    """
    if not account_number or not isinstance(account_number, str):
        return False, "", "Account number cannot be empty. Please provide a valid 9 to 18-digit account number."

    cleaned = re.sub(r"[\s-]", "", account_number).strip()

    # Reject if too short
    if len(cleaned) < 9:
        return (
            False,
            cleaned,
            f"The account number '{cleaned}' is too short ({len(cleaned)} digits). Indian bank account numbers are typically between 9 and 18 digits. Please check and re-enter."
        )
    # Reject if too long
    if len(cleaned) > 20:
        return (
            False,
            cleaned,
            f"The account number '{cleaned}' exceeds the maximum length of 18 digits. Please check and re-enter."
        )

    # Must be either all digits (9-18), or letter prefix (e.g. SB/CA/NOVA) followed by digits
    if not re.match(r"^(?:[A-Za-z]{2,4})?\d{6,18}$", cleaned):
        return (
            False,
            cleaned,
            f"The account number '{cleaned}' contains invalid characters. Account numbers must consist of digits (with an optional 2-4 letter account prefix like SB or CA). Please provide a valid account number."
        )

    return True, cleaned, None


def validate_ifsc_code(ifsc_code: str) -> Tuple[bool, str, Optional[str]]:
    """
    Validates Indian Financial System Code (IFSC).
    Format: 4 uppercase letters + '0' (or digit) + 6 alphanumeric branch characters.
    Strict Length: exactly 11 characters.
    Returns:
      (is_valid, cleaned_ifsc_code, error_message_if_invalid)
    """
    if not ifsc_code or not isinstance(ifsc_code, str):
        return False, "", "IFSC code cannot be empty. Please provide an 11-character IFSC code."

    cleaned = re.sub(r"[\s-]", "", ifsc_code).upper().strip()

    # Reject generic conversational words
    if cleaned in ["BENEFICIARY", "BENEFICIARIES", "TRANSACTION", "TRANSFER", "PAYMENT", "ACCOUNT"]:
        return (
            False,
            cleaned,
            f"'{cleaned}' is not an IFSC code. Please provide an 11-character bank IFSC code (e.g., NOVA0001001 or SBIN0001234)."
        )

    # Length check: Indian IFSC codes must be strictly 11 characters
    if len(cleaned) != 11:
        return (
            False,
            cleaned,
            f"The IFSC code '{cleaned}' has {len(cleaned)} characters, but standard Indian IFSC codes must be exactly 11 characters (4 letters for the bank, '0', followed by 6 characters for the branch, e.g. NOVA0001001 or SBIN0001234)."
        )

    # Bank code check: first 4 characters must be alphabetic
    if not cleaned[:4].isalpha():
        return (
            False,
            cleaned,
            f"The IFSC code '{cleaned}' is invalid. The first 4 characters must be alphabetic letters identifying the bank (e.g., SBIN or NOVA)."
        )

    # 5th character is typically '0' (zero) in standard RBI IFSC
    if not cleaned[4].isdigit():
        return (
            False,
            cleaned,
            f"The IFSC code '{cleaned}' is invalid. In Indian banking, the 5th character of an IFSC code must be a digit (typically '0'), followed by the 6-character branch code (e.g. SBIN0001234 or NOVA0001001)."
        )

    # Full structure check
    if not re.match(r"^[A-Z]{4}[0-9][A-Z0-9]{6}$", cleaned):
        return (
            False,
            cleaned,
            f"The IFSC code '{cleaned}' has an invalid format. A valid IFSC code is 11 characters in the format 'AAAA0BBBBBB' (e.g. NOVA0001001 or SBIN0001234)."
        )

    return True, cleaned, None

