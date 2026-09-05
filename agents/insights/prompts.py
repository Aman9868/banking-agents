"""Personal Financial Management (PFM) Insights Prompts and Templates."""

def build_spending_breakdown_response(info: dict) -> str:
    """Formats spending breakdown summary."""
    lines = [
        f"📊 **Monthly Spending Breakdown (Last {info['period_days']} Days)**",
        f"**Total Outflow:** ₹{info['total_spent']:,.2f}\n"
    ]
    for item in info["breakdown"]:
        lines.append(f"• **{item['category']}**: ₹{item['amount']:,.2f} ({item['percentage']}%)")

    lines.append(f"\n💡 *Top expense driver:* **{info['top_category']}**.")
    return "\n".join(lines)


def build_subscriptions_response(info: dict) -> str:
    """Formats recurring subscriptions audit."""
    lines = [
        f"🔄 **Active Recurring Subscriptions Detected ({info['count']})**",
        f"**Total Monthly Commitment:** ₹{info['total_monthly_commitment']:,.2f}",
        f"**Projected Annual Cost:** ₹{info['annual_projected_cost']:,.2f}\n"
    ]
    for sub in info["subscriptions"]:
        lines.append(f"• **{sub['name']}**: ₹{sub['amount']:,.2f}/mo (Last paid: {sub['last_paid']})")

    return "\n".join(lines)
