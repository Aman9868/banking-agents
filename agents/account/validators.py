"""Production KYC & Customer Profile Validators for Account Onboarding."""

import re
import datetime
from typing import Tuple, Optional

# Standard RFC 5322 compliant regex for email validation
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}$"
)

# Common placeholder / dismissive answers that should never pass KYC
INVALID_PLACEHOLDERS = {
    "na", "n/a", "none", "no", "test", "null", "nil", "unknown", "idk",
    "nope", "nothing", "not applicable", "n.a", "n.a.", "skip", "pass",
    "xyz", "asdf", "dummy", "fake", "temp"
}


def validate_email(email_raw: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validates an email address according to production banking standards.
    
    Returns:
        (is_valid, cleaned_email, error_message)
    """
    if not email_raw or not isinstance(email_raw, str):
        return False, None, "Please provide your email address to receive your official account details."

    cleaned = email_raw.strip().lower()

    if cleaned in INVALID_PLACEHOLDERS:
        return (
            False,
            None,
            "A valid email address is required for official account correspondence. "
            "Please provide a real email address (e.g., yourname@example.com)."
        )

    if len(cleaned) < 6 or len(cleaned) > 254:
        return (
            False,
            None,
            "Email address must be between 6 and 254 characters. Please check and re-enter."
        )

    if not EMAIL_REGEX.match(cleaned):
        return (
            False,
            None,
            "That doesn't appear to be a valid email format. Please provide an email address like name@example.com."
        )

    # Disallow consecutive dots or invalid domain structure
    parts = cleaned.split("@")
    if len(parts) != 2:
        return False, None, "Invalid email format. Please include an '@' and valid domain."

    local_part, domain_part = parts
    if ".." in local_part or ".." in domain_part:
        return False, None, "Email address cannot contain consecutive periods."

    domain_segments = domain_part.split(".")
    if len(domain_segments) < 2 or any(len(seg) == 0 for seg in domain_segments):
        return False, None, "Please provide an email with a valid domain (e.g. gmail.com, company.com)."

    tld = domain_segments[-1]
    if len(tld) < 2 or not tld.isalpha():
        return False, None, "Please provide an email with a valid top-level domain (e.g., .com, .in, .org)."

    return True, cleaned, None


def validate_date_of_birth(dob_raw: str, min_age: int = 18, max_age: int = 120) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validates and standardizes date of birth for bank account KYC.
    Enforces minimum legal banking age (default: 18 years old).
    
    Returns:
        (is_valid, formatted_dob_iso, error_message)
    """
    if not dob_raw or not isinstance(dob_raw, str):
        return False, None, "Please provide your date of birth in DD/MM/YYYY or YYYY-MM-DD format."

    cleaned = dob_raw.strip().lower()

    if cleaned in INVALID_PLACEHOLDERS:
        return (
            False,
            None,
            "Date of birth is mandatory for regulatory KYC verification. "
            "Please provide your actual date of birth in DD/MM/YYYY or YYYY-MM-DD format."
        )

    # Strip ordinal suffixes (1st, 2nd, 3rd, 4th, 12th, etc.)
    cleaned_date_str = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", cleaned, flags=re.IGNORECASE).strip()

    # List of common input date formats
    date_formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%b %d %Y",
        "%d-%b-%Y",
        "%d/%b/%Y",
        "%Y/%m/%d",
    ]

    parsed_date = None
    for fmt in date_formats:
        try:
            parsed_date = datetime.datetime.strptime(cleaned_date_str, fmt).date()
            break
        except ValueError:
            continue

    if not parsed_date:
        return (
            False,
            None,
            "I could not recognize that date format. Please enter your date of birth "
            "using DD/MM/YYYY, YYYY-MM-DD, or Month Day Year (e.g. 15/08/1995 or 12 March 1997)."
        )

    today = datetime.date.today()

    if parsed_date >= today:
        return (
            False,
            None,
            "Date of birth cannot be today or in the future. Please provide your actual date of birth."
        )

    # Calculate exact age in years
    age = today.year - parsed_date.year - (
        (today.month, today.day) < (parsed_date.month, parsed_date.day)
    )

    if age < min_age:
        return (
            False,
            None,
            f"Applicants must be at least {min_age} years old to open an independent NovaBank account "
            f"(calculated age is {age} years). Minor accounts require a guardian at a branch."
        )

    if age > max_age:
        return (
            False,
            None,
            f"Please verify your date of birth (applicant age cannot exceed {max_age} years)."
        )

    # Standardize to ISO format YYYY-MM-DD
    return True, parsed_date.strftime("%Y-%m-%d"), None


def validate_full_name(name_raw: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validates and sanitizes customer full name for KYC.
    
    Returns:
        (is_valid, cleaned_name, error_message)
    """
    if not name_raw or not isinstance(name_raw, str):
        return False, None, "Please provide your full legal name as it appears on your government ID."

    cleaned = name_raw.strip()
    cleaned_lower = cleaned.lower()

    if cleaned_lower in INVALID_PLACEHOLDERS:
        return (
            False,
            None,
            "Please provide your actual legal name as it appears on your government-issued ID."
        )

    if len(cleaned) < 2:
        return (
            False,
            None,
            "Full name must be at least 2 characters long. Please provide your legal name."
        )

    # Ensure name contains alphabetic characters and not just numbers/symbols
    alpha_chars = [c for c in cleaned if c.isalpha()]
    if len(alpha_chars) < 2:
        return (
            False,
            None,
            "Please provide a valid full name containing alphabetic characters (e.g., Priya Sharma)."
        )

    # Check for disallowed characters (no digits, email, URLs, or code symbols)
    if re.search(r"[\d@#$%^*=<>\[\]{}|\\]", cleaned):
        return (
            False,
            None,
            "Name cannot contain numbers or special characters. Please provide your official legal name."
        )

    # Properly format name casing (Title Case)
    formatted_name = " ".join(word.capitalize() for word in cleaned.split())
    return True, formatted_name, None
