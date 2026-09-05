"""Customer Support, Dispute Resolution & Escalation Prompts."""

REASON_TRANSLATIONS = {
    "BENEFICIARY_SECURITY_VERIFICATION_INCOMPLETE": "the beneficiary security verification was not completed",
    "DAILY_TRANSFER_LIMIT_EXCEEDED": "your daily transfer limit was exceeded",
    "SUSPICIOUS_VELOCITY_FLAG": "our fraud monitoring system flagged elevated velocity on the account",
    "INSUFFICIENT_FUNDS": "the account balance was insufficient at the time of execution",
}


def build_fraud_ticket_response(ticket_id: str) -> str:
    """Formats the high-priority fraud/unauthorized activity report."""
    return (
        f"🚨 **High-Priority Fraud Report Logged** (Ref: `{ticket_id}`)\n\n"
        "We take unauthorized charges very seriously. I have escalated this directly to NovaBank's Fraud Investigation Team.\n\n"
        "**Immediate Safety Recommendation:**\n"
        "• Would you like me to **freeze your card immediately** to prevent any further unauthorized activity?\n"
        "• Simply say *'Freeze my card'* or click the Cards menu to lock it instantly."
    )


def build_kb_guidelines_response(articles: list) -> str:
    """Formats grounded knowledge base guidelines."""
    summary = "\n\n".join([f"**{a['title']}**:\n{a['content']}" for a in articles])
    return f"According to our official banking guidelines:\n\n{summary}"


def build_transaction_dispute_response(tx_ref: str, status: str, failure_code: str, amount: float = 0.0) -> str:
    """Formats transaction decline diagnosis or status."""
    friendly_reason = REASON_TRANSLATIONS.get(failure_code, str(failure_code).replace("_", " ").lower())
    if status in ["DECLINED", "FAILED"]:
        return (
            f"I found transaction {tx_ref}.\n"
            f"It was declined because {friendly_reason}."
        )
    return (
        f"Transaction {tx_ref} is currently {status.lower()} "
        f"for the amount of ₹{amount:,.2f}."
    )
