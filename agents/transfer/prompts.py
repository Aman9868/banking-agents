"""Transfer Agent System Prompts, Intent Guidance, and Conversational Extraction Templates."""

from typing import Dict, Any

TRANSFER_ENTITY_EXTRACTION_SYSTEM_PROMPT = """You are a conversational entity extractor for a banking fund transfer system.
Analyze the user's message and extract transfer parameters based on the current dialog state.

Current transfer state:
- Beneficiary Name: {beneficiary_name}
- Beneficiary Account: {beneficiary_account}
- IFSC Code: {ifsc_code}
- Amount: {amount}
- Previous assistant question: "{previous_question}"

User message: "{last_msg}"

Rules:
1. If the previous question asked for a beneficiary name, and user provided a name (e.g. "Rahul", "Priya", "John Smith"), extract as "beneficiary_name".
2. If the user provided an amount (e.g. "500", "5k", "₹10,000", "two thousand"), parse and return float as "amount".
3. If the user provided a bank account number (9 to 18 digits) or phone/UPI number (10 digits), extract as "account_number".
4. If the user provided an IFSC code (11 characters starting with 4 letters), extract as "ifsc_code".

Respond strictly with valid JSON:
{{
  "beneficiary_name": null,
  "amount": null,
  "account_number": null,
  "ifsc_code": null
}}"""


def build_transfer_entity_extraction_prompt(
    current_data: Dict[str, Any],
    previous_question: str,
    last_msg: str
) -> str:
    """Builds dynamic entity extraction prompt for transfer multi-turn dialogues."""
    return TRANSFER_ENTITY_EXTRACTION_SYSTEM_PROMPT.format(
        beneficiary_name=current_data.get('beneficiary_name') or 'Not provided',
        beneficiary_account=current_data.get('beneficiary_account') or 'Not provided',
        ifsc_code=current_data.get('ifsc_code') or 'Not provided',
        amount=current_data.get('amount') or 'Not provided',
        previous_question=previous_question,
        last_msg=last_msg
    )
