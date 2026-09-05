"""Bill Payments & UPI Transfer Prompts and Response Templates."""

def build_upi_verified_response(upi_id: str, resolved_name: str) -> str:
    """Formats UPI ID verification response."""
    return (
        f"✅ **UPI Handle Verified**: `{upi_id}` ({resolved_name})\n\n"
        f"Instant UPI payment rail is linked and ready. Please confirm the amount you would like to transfer."
    )


def build_bill_details_prompt(
    biller_name: str,
    consumer_number: str,
    amount: float,
    due_date: str,
    bill_id: str
) -> str:
    """Formats bill details fetch and confirmation prompt."""
    return (
        f"🧾 **Bill Details Retrieved**\n\n"
        f"• **Biller:** {biller_name}\n"
        f"• **Consumer/Account ID:** `{consumer_number}`\n"
        f"• **Bill Reference:** `{bill_id}`\n"
        f"• **Amount Due:** ₹{amount:,.2f}\n"
        f"• **Due Date:** {due_date}\n\n"
        f"Would you like me to proceed with paying this bill from your primary account? "
        f"Please reply **'Yes, pay bill'** to authenticate or **'No'** to cancel."
    )
