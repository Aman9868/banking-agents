"""Card Operations & Security Prompts and Response Templates."""

def build_cards_list_response(cards: list) -> str:
    """Formats the active cards list response."""
    lines = ["Here are your active NovaBank cards:\n"]
    for c in cards:
        status_icon = "🟢 ACTIVE" if c.get("status") == "ACTIVE" else "🔴 FROZEN"
        lines.append(
            f"• **{c.get('card_type', 'DEBIT')} Card** (`{c.get('masked_number', '****')}`)\n"
            f"  Status: {status_icon} | Daily Limit: ₹{c.get('daily_limit', 0):,.2f} | Online: {'Enabled' if c.get('online_txn_enabled') else 'Disabled'}"
        )
    lines.append("\nYou can freeze/unfreeze, report lost, or set custom limits anytime!")
    return "\n".join(lines)


def build_freeze_card_response(card_type: str, message: str = "Card has been frozen.") -> str:
    return f"🔒 **Security Update**: {message} Your {card_type} card has been locked immediately to protect your account."


def build_unfreeze_card_response(card_type: str, message: str = "Card has been unfrozen.") -> str:
    return f"🔓 **Security Update**: {message} Your {card_type} card is now active and ready for transactions."


def build_replace_card_response(card_type: str, message: str = "Replacement card has been ordered.") -> str:
    return f"💳 **Card Replacement**: {message} A new {card_type} card will be dispatched to your registered address."


def build_set_limits_response(card_type: str, online_limit: float) -> str:
    return f"⚙️ **Card Limits Updated**: Online spending limit for your {card_type} card has been set to **₹{online_limit:,.2f}**."
