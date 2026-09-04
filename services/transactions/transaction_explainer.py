"""Enterprise Transaction & Spending Explainer Service for NovaBank."""

from typing import Dict, Any, Optional, List
import structlog

from database.repositories.banking_repo import BankingRepository
from database.models.banking import Transaction
from security.pii import mask_account_number

logger = structlog.get_logger(__name__)


DECLINE_REASON_EXPLANATIONS = {
    "BENEFICIARY_SECURITY_VERIFICATION_INCOMPLETE": {
        "title": "Beneficiary Cool-Off Security Check Active",
        "plain_explanation": (
            "This transfer was paused and declined because the newly added beneficiary is still undergoing "
            "NovaBank's mandatory cooling-off security period. To protect customer accounts from authorized "
            "push payment fraud, new beneficiaries require a 30-minute verification window before transfers "
            "exceeding standard limits are processed."
        ),
        "actionable_next_step": "Please wait for the cooling period to complete, or transfer a lower initial amount (under ₹10,000)."
    },
    "INSUFFICIENT_FUNDS": {
        "title": "Insufficient Account Balance",
        "plain_explanation": (
            "The transaction could not be completed because your available account balance was less than the requested transfer amount."
        ),
        "actionable_next_step": "Please top up or deposit funds into your account before re-attempting the transfer."
    },
    "DAILY_TRANSFER_LIMIT_EXCEEDED": {
        "title": "Daily Cumulative Transfer Limit Reached",
        "plain_explanation": (
            "This transaction would exceed your standard daily digital transfer ceiling of ₹100,000.00."
        ),
        "actionable_next_step": "You can modify your daily limits in card & security settings or retry tomorrow morning."
    },
    "HIGH_FRAUD_RISK": {
        "title": "Automated Security Guardrail Triggered",
        "plain_explanation": (
            "Our automated fraud prevention engine detected unusual patterns and temporarily held this payment to safeguard your assets."
        ),
        "actionable_next_step": "You can request an officer human review directly in chat or contact NovaBank 24/7 Priority Support."
    }
}


class TransactionExplainer:
    """Diagnoses transaction statuses and produces conversational banking explanations."""

    def __init__(self, repo: BankingRepository):
        self.repo = repo

    async def explain_transaction_or_spending(
        self,
        customer_external_id: str,
        transaction_ref: Optional[str] = None,
        query_type: Optional[str] = None  # "DECLINE_REASON", "LAST_TXN", "SPENDING_SUMMARY"
    ) -> Dict[str, Any]:
        """
        Diagnoses a specific transaction or the latest customer transaction and explains root causes.
        """
        customer = await self.repo.get_customer_by_external_id(customer_external_id)
        if not customer:
            raise ValueError(f"Customer '{customer_external_id}' not found.")

        # If a specific transaction ref is provided, fetch it
        target_tx: Optional[Transaction] = None
        if transaction_ref:
            target_tx = await self.repo.get_transaction_by_ref(transaction_ref)
            if target_tx and target_tx.customer_id != customer.id:
                raise ValueError("Unauthorized: Transaction does not belong to this customer.")

        # Otherwise retrieve recent transactions
        recent_txs = await self.repo.get_recent_transactions(customer.id, limit=10)

        # If user specifically asked about declined transaction, look for the most recent declined one
        if not target_tx:
            if query_type == "DECLINE_REASON" or any(kw in (query_type or "").lower() for kw in ["decline", "failed", "reject"]):
                for t in recent_txs:
                    if t.status in ("DECLINED", "FAILED", "REJECTED"):
                        target_tx = t
                        break

        # Fallback to the latest transaction overall
        if not target_tx and recent_txs:
            target_tx = recent_txs[0]

        if not target_tx:
            return {
                "success": False,
                "message": "No transactions found on your account to analyze.",
                "diagnosis": None
            }

        bene_name = target_tx.beneficiary.name if target_tx.beneficiary else "External Beneficiary"
        bene_acc = mask_account_number(target_tx.beneficiary.account_number) if target_tx.beneficiary else "N/A"
        src_acc = mask_account_number(target_tx.source_account.account_number) if target_tx.source_account else "N/A"
        created_time = target_tx.created_at.strftime("%d %B %Y at %I:%M %p") if hasattr(target_tx.created_at, "strftime") else str(target_tx.created_at)

        is_declined = target_tx.status in ("DECLINED", "FAILED", "REJECTED")

        if is_declined:
            raw_reason = target_tx.failure_reason or "SECURITY_POLICY_CHECK"
            explanation_data = DECLINE_REASON_EXPLANATIONS.get(
                raw_reason,
                {
                    "title": "Transaction Policy Failure",
                    "plain_explanation": f"The transfer was declined by core banking due to: {raw_reason.replace('_', ' ').title()}.",
                    "actionable_next_step": "Please verify beneficiary details or submit a support ticket for banking assistance."
                }
            )

            diagnosis = {
                "transaction_ref": target_tx.transaction_ref,
                "status": target_tx.status,
                "amount": target_tx.amount,
                "formatted_amount": f"₹{target_tx.amount:,.2f}",
                "currency": target_tx.currency,
                "timestamp": created_time,
                "beneficiary": {
                    "name": bene_name,
                    "masked_account": bene_acc
                },
                "source_account": src_acc,
                "reason_title": explanation_data["title"],
                "explanation": explanation_data["plain_explanation"],
                "actionable_remedy": explanation_data["actionable_next_step"],
                "fraud_score": target_tx.fraud_score,
                "is_declined": True
            }

            conversational_text = (
                f"### ⚠️ Transaction Diagnosis: {target_tx.transaction_ref}\n\n"
                f"Your transfer of **₹{target_tx.amount:,.2f}** to **{bene_name}** on {created_time} "
                f"was **{target_tx.status}**.\n\n"
                f"**Root Cause:** {explanation_data['title']}\n"
                f"{explanation_data['plain_explanation']}\n\n"
                f"💡 **Recommended Next Step:** {explanation_data['actionable_next_step']}"
            )
        else:
            diagnosis = {
                "transaction_ref": target_tx.transaction_ref,
                "status": target_tx.status,
                "amount": target_tx.amount,
                "formatted_amount": f"₹{target_tx.amount:,.2f}",
                "currency": target_tx.currency,
                "timestamp": created_time,
                "beneficiary": {
                    "name": bene_name,
                    "masked_account": bene_acc
                },
                "source_account": src_acc,
                "reason_title": "Successfully Processed Transfer",
                "explanation": (
                    f"This was an outgoing money transfer of ₹{target_tx.amount:,.2f} to {bene_name} "
                    f"(Account: {bene_acc}). It was successfully processed via instant settlement."
                ),
                "actionable_remedy": "You can download your account statement or request a transaction receipt if needed.",
                "fraud_score": target_tx.fraud_score,
                "is_declined": False
            }

            conversational_text = (
                f"### ℹ️ Transaction Details: {target_tx.transaction_ref}\n\n"
                f"Your transfer of **₹{target_tx.amount:,.2f}** to **{bene_name}** ({bene_acc}) "
                f"was successfully completed on **{created_time}**.\n\n"
                f"• **Status:** {target_tx.status} ✅\n"
                f"• **Source Account:** {src_acc}\n"
                f"• **UTR / Ref:** `{target_tx.transaction_ref}`\n\n"
                f"If you'd like a formal PDF statement or receipt, simply ask 'generate my statement'."
            )

        return {
            "success": True,
            "transaction_ref": target_tx.transaction_ref,
            "diagnosis": diagnosis,
            "conversational_text": conversational_text,
            "recent_spending_context": {
                "total_recent_transactions": len(recent_txs),
                "last_5_refs": [t.transaction_ref for t in recent_txs[:5]]
            }
        }

