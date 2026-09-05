"""Loan Advisory & Application Prompts and Response Templates."""

def build_loan_application_response(loan_type: str, amount: float, tenure_months: int, message: str) -> str:
    """Formats loan application submission response."""
    return (
        f"📋 **Loan Application Submitted**\n\n"
        f"• **Facility:** {loan_type.capitalize()} Loan\n"
        f"• **Requested Amount:** ₹{amount:,.2f}\n"
        f"• **Tenure:** {tenure_months} months ({tenure_months // 12} years)\n"
        f"• **Status:** Under Review with Credit Risk Committee\n\n"
        f"{message}"
    )


def build_loan_eligibility_response(loan_type: str, requested_amount: float, message: str) -> str:
    """Formats loan eligibility evaluation response."""
    return (
        f"🎯 **Loan Eligibility Assessment**\n\n"
        f"• **Product:** {loan_type.capitalize()} Loan\n"
        f"• **Target Amount:** ₹{requested_amount:,.2f}\n\n"
        f"{message}"
    )


def build_emi_estimate_response(
    loan_type: str,
    principal: float,
    interest_rate: float,
    tenure_months: int,
    monthly_emi: float,
    total_interest: float,
    total_payable: float
) -> str:
    """Formats EMI calculator estimate response."""
    return (
        f"Here is your **{loan_type.capitalize()} Loan** estimate:\n\n"
        f"• **Loan Amount:** ₹{principal:,.2f}\n"
        f"• **Interest Rate:** {interest_rate:.2f}% p.a.\n"
        f"• **Tenure:** {tenure_months} months ({tenure_months // 12} years)\n"
        f"• **Estimated Monthly EMI:** ₹{monthly_emi:,.2f}\n"
        f"• **Total Interest Payable:** ₹{total_interest:,.2f}\n"
        f"• **Total Outflow:** ₹{total_payable:,.2f}\n\n"
        f"Would you like to check your detailed eligibility or submit an application today?"
    )
