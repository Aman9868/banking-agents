"""Account Opening & Onboarding Prompts and Templates."""

def prompt_full_name() -> str:
    return "Absolutely! I can help you open a new bank account. May I have your full name?"


def prompt_date_of_birth(full_name: str) -> str:
    return f"Thanks, {full_name}. What is your date of birth?"


def prompt_email() -> str:
    return "What email address would you like to use for your account?"


def prompt_business_name() -> str:
    return "Thank you! To open a **NovaBank Current Account**, please share your registered **Company or Business Name** (e.g. Acme Tech Solutions Private Limited)."


def prompt_gstin(company_name: str) -> str:
    return f"Please provide your 15-character **GSTIN** (Goods & Services Tax Number) or upload your Form GST REG-06 registration certificate for **{company_name}**."


def prompt_aadhaar_kyc() -> str:
    return (
        "Now let's complete your official Identity Verification (KYC).\n\n"
        "Please provide your **12-digit Aadhaar Number** or upload a photo/PDF of your Aadhaar card."
    )


def prompt_video_kyc() -> str:
    return (
        "Identity document verified! The final step is a quick **Live Video / Biometric KYC**.\n\n"
        "Please click below to activate your camera for a 3-second live face match and blink verification."
    )
