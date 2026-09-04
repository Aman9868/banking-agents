"""Transaction inquiry and history banking tools."""

from typing import Optional
from database.repositories.banking_repo import BankingRepository
from security.pii import mask_account_number
from tools.base import ToolResult


async def get_transaction(repo: BankingRepository, customer_id: int, transaction_ref: str) -> ToolResult:
    """Retrieves transaction details including decline reasons if applicable."""
    tx = await repo.get_transaction_by_ref(transaction_ref)
    if not tx or tx.customer_id != customer_id:
        return ToolResult(
            success=False,
            error=f"Transaction '{transaction_ref}' not found for this customer."
        )

    beneficiary_name = tx.beneficiary.name if tx.beneficiary else "External Beneficiary"
    beneficiary_account = mask_account_number(tx.beneficiary.account_number) if tx.beneficiary else None
    source_account = mask_account_number(tx.source_account.account_number) if tx.source_account else None

    return ToolResult(
        success=True,
        data={
            "transaction_ref": tx.transaction_ref,
            "amount": tx.amount,
            "currency": tx.currency,
            "status": tx.status,
            "beneficiary_name": beneficiary_name,
            "beneficiary_account": beneficiary_account,
            "source_account": source_account,
            "failure_reason": tx.failure_reason,
            "fraud_score": tx.fraud_score,
            "created_at": tx.created_at.strftime("%d %B %Y, %I:%M %p") if hasattr(tx.created_at, "strftime") else str(tx.created_at)
        }
    )


async def get_recent_transactions(repo: BankingRepository, customer_id: int, limit: int = 5) -> ToolResult:
    """Lists recent transactions for customer."""
    txs = await repo.get_recent_transactions(customer_id, limit=limit)
    formatted = []
    for t in txs:
        bene_name = t.beneficiary.name if t.beneficiary else "External Beneficiary"
        bene_acc = mask_account_number(t.beneficiary.account_number) if t.beneficiary else None
        src_acc = mask_account_number(t.source_account.account_number) if t.source_account else None
        formatted.append({
            "transaction_ref": t.transaction_ref,
            "amount": t.amount,
            "currency": t.currency,
            "status": t.status,
            "beneficiary_name": bene_name,
            "beneficiary_account": bene_acc,
            "source_account": src_acc,
            "failure_reason": t.failure_reason,
            "created_at": t.created_at.strftime("%d %B %Y, %I:%M %p") if hasattr(t.created_at, "strftime") else str(t.created_at)
        })

    return ToolResult(
        success=True,
        data={
            "transactions": formatted,
            "total_count": len(formatted)
        }
    )


