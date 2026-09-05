"""Supervisor Orchestrator System Prompts, Conversational Menus, and Interruption Templates."""

from typing import Dict, Any, Tuple


SUPERVISOR_MENU_PROMPT_TEMPLATE = """Hello {cust_display_name}! I am your AI Banking Assistant. I can assist you with:
• Transfers & Beneficiaries: Send money, UPI payments, balance checks
• Wealth & Investments: Systematic SIP planner, compounding calculators, live stock market search
• Insurance & Policies: Health shields, pure term life, PMJJBY, PMSBY, PPF & NPS
• Statements & Ledgers: Official PDF statements with running balances & decline diagnosis
• Cards Management: Instant freeze/unfreeze, report lost card, set limits
• Loans & Advisory: EMI calculators, loan eligibility, application submission
• Bill Payments: Pay electricity, broadband, mobile, and credit card bills
• Account Opening: Conversational savings and current account opening with video KYC
• Support & FAQs: Dispute investigation, interest rates, and customer support escalation"""


def build_supervisor_default_menu(customer_name: str = "") -> str:
    """Returns the formatted main banking assistant menu."""
    first_name = customer_name.split(" ")[0].capitalize() if customer_name else "there"
    return SUPERVISOR_MENU_PROMPT_TEMPLATE.format(cust_display_name=first_name)


def build_interruption_continuation_prompt(
    base_msg: str,
    active_wf: str,
    state: Dict[str, Any]
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Appends a conversational prompt to resume an interrupted active multi-turn workflow
    (such as fund transfer, account opening, or loan application) after an informational interruption.
    """
    if active_wf == "TRANSFER_MONEY":
        t_data = dict(state.get("transfer_data") or {})
        t_step = t_data.get("step", "RESOLVE")
        bene = t_data.get("beneficiary_name", "the beneficiary")
        amt = t_data.get("amount")
        acc = t_data.get("beneficiary_account")
        ifsc = t_data.get("ifsc_code")

        if t_step == "ADD_BENEFICIARY":
            if acc and not ifsc:
                prompt = (
                    f"\n\nNow, continuing with adding **{bene}** as a beneficiary: "
                    "Please provide their **11-character IFSC Code** (e.g. SBIN0001234 or NOVA0001001) to proceed with the transfer."
                )
            elif ifsc and not acc:
                prompt = (
                    f"\n\nNow, continuing with adding **{bene}** as a beneficiary: "
                    "Please provide their **Account Number** (9 to 18 digits) to proceed with the transfer."
                )
            else:
                prompt = (
                    f"\n\nNow, continuing with your transfer to **{bene}**: "
                    "Please provide their **Account Number** and **IFSC Code** to add them as a beneficiary."
                )
        elif t_step == "CONFIRM":
            amt_str = f"₹{amt:,.2f}" if amt else "the funds"
            prompt = (
                f"\n\nNow, continuing with your transfer: Would you like to proceed with transferring "
                f"**{amt_str}** to **{bene}**? (Please reply 'Yes' to confirm or 'No' to cancel)."
            )
        elif t_step == "RESOLVE":
            if not amt:
                prompt = f"\n\nNow, continuing with your transfer to **{bene}**: How much would you like to transfer?"
            else:
                prompt = f"\n\nNow, continuing with your transfer: Who would you like to transfer funds to?"
        else:
            prompt = f"\n\nWould you like to continue with your transfer to **{bene}**?"

        return base_msg + prompt, "TRANSFER_MONEY", {"transfer_data": t_data}

    elif active_wf == "OPEN_ACCOUNT":
        acc_data = dict(state.get("account_data") or {})
        step = acc_data.get("step", "NAME")
        if step == "DOB":
            prompt = "\n\nNow, continuing with your account application: What is your date of birth?"
        elif step == "EMAIL":
            prompt = "\n\nNow, continuing with your account application: What is your email address?"
        else:
            prompt = "\n\nNow, continuing with your account application: What is your full name?"
        return base_msg + prompt, "OPEN_ACCOUNT", {"account_data": acc_data}

    elif active_wf == "PAYMENT_ACTION":
        bill_data = dict(state.get("bill_data") or {})
        biller = bill_data.get("biller_name", "your bill")
        prompt = f"\n\nNow, continuing with your bill payment for **{biller}**: Please provide the consumer number or confirm payment."
        return base_msg + prompt, "PAYMENT_ACTION", {"bill_data": bill_data}

    elif active_wf == "WEALTH_ADVISORY":
        w_data = dict(state.get("wealth_data") or {})
        amt = w_data.get("monthly_investment", 1000.0)
        prompt = f"\n\nNow, continuing with your SIP investment planning of ₹{amt:,.2f}/month: Would you like to view our recommended funds or adjust the tenure?"
        return base_msg + prompt, "WEALTH_ADVISORY", {"wealth_data": w_data}

    elif active_wf == "POLICY_ACTION":
        p_data = dict(state.get("policy_data") or {})
        cat = p_data.get("category", "insurance")
        prompt = f"\n\nNow, continuing with your {cat} policy exploration: Would you like more details or a comparison between specific plans?"
        return base_msg + prompt, "POLICY_ACTION", {"policy_data": p_data}

    return base_msg, "NONE", {}


def build_gratitude_response(last_ai_content: str, customer_name: str) -> str:
    """Builds a warm, contextual gratitude reply based on the preceding assistant action."""
    name_str = customer_name.split(" ")[0].capitalize() if customer_name else "there"

    if any(k in last_ai_content for k in ["Transferred", "transfer of", "Payment sent", "Transaction ID"]):
        return f"You're very welcome, {name_str}! 😊 Glad I could help get that money transferred safely. Let me know if you need anything else!"
    elif any(k in last_ai_content for k in ["Card has been frozen", "freeze_card", "unfrozen", "Card limit"]):
        return f"You're very welcome, {name_str}! Your card security is always our top priority. Let me know if you need any other card management assistance."
    elif any(k in last_ai_content for k in ["Account Statement", "statement_id", "Official PDF"]):
        return f"Happy to help, {name_str}! Your official statement download is ready whenever you need it. Let me know if you have questions about any transactions."
    elif any(k in last_ai_content for k in ["Available Balance", "Net Worth", "Total Consolidated Balance"]):
        return f"You're most welcome, {name_str}! Keep track of your finances anytime. Let me know if you'd like to make a transfer, pay bills, or invest."
    elif any(k in last_ai_content for k in ["EMI", "Monthly Installment", "Loan Eligibility"]):
        return f"Happy to help with your loan calculations, {name_str}! Feel free to reach out when you're ready to proceed with an application or explore other options. 😊"
    elif any(k in last_ai_content for k in ["Paid to", "bill payment", "Electricity Bill"]):
        return f"You're very welcome, {name_str}! Glad that payment is all sorted. Let me know if you have other bills or transfers to take care of."
    elif any(k in last_ai_content for k in ["SIP", "Compounding", "Student Starter", "Nifty 50", "Asset Allocation"]):
        return f"You're very welcome, {name_str}! Starting your investment journey early is the best decision you can make. Let me know whenever you'd like to adjust your SIP or explore other funds! 🚀"
    elif any(k in last_ai_content for k in ["Health Shield", "PMJJBY", "Insurance", "Policy Catalog", "Health & Medical"]):
        return f"Always glad to help secure your financial future, {name_str}! Reach out anytime you have questions about policies or coverage benefits. 🌟"
    elif any(k in last_ai_content for k in ["Live Market Quote", "Financial & Stock Market"]):
        return f"You're very welcome, {name_str}! Happy to provide real-time market data. Let me know if you need quotes or insights on any other stocks!"
    else:
        return f"You're very welcome, {name_str}! 😊 It's always my pleasure to assist you. Just let me know whenever you need anything else with NovaBank!"


def build_chatgpt_style_fallback_response(user_query: str = "", customer_name: str = "") -> str:
    """
    ChatGPT-style intelligent conversational fallback when a query is ambiguous, unrecognized,
    or does not match a specific transaction schema.
    """
    first_name = customer_name.split(" ")[0].capitalize() if customer_name else ""
    greeting = f"Hello {first_name}! " if first_name else "Hello! "

    clean_query = (user_query or "").strip()
    if clean_query:
        query_snippet = f" regarding *'{clean_query}'*" if len(clean_query) < 60 else ""
        return (
            f"{greeting}I understand you're asking{query_snippet}, but I need a little more clarity to help you accurately.\n\n"
            "Here are some of the things I can help you with right away:\n"
            "• **Money Transfers & UPI**: Send funds, verify UPI IDs, or check/add beneficiaries\n"
            "• **Accounts & Balances**: Check account balance, view account numbers, or download official statements\n"
            "• **Cards & Limits**: Freeze/unfreeze debit/credit cards or set online transaction limits\n"
            "• **Wealth & Investments**: Plan monthly SIPs, compound growth calculators, or search live stock prices\n"
            "• **Loans & EMI**: Calculate EMI estimates or verify loan eligibility\n"
            "• **Bills & Disputes**: Pay electricity/utility bills or investigate declined transactions\n\n"
            "Could you please tell me which of these you'd like to proceed with, or rephrase your request?"
        )
    else:
        return (
            f"{greeting}I'm NovaBank's AI Banking Assistant. How can I help you today?\n\n"
            "You can ask me about your account balance, transferring money, managing cards, planning investments, or paying bills."
        )


def build_system_error_fallback_response() -> str:
    """
    Polite, helpful ChatGPT-style fallback response when an unexpected system error or timeout occurs.
    """
    return (
        "I apologize, but I encountered a temporary issue while processing your request.\n\n"
        "Please try asking again or rephrasing your question. If you need urgent assistance with your account, "
        "such as freezing a card, reporting an unauthorized transaction, or checking your balance, please let me know right away."
    )
