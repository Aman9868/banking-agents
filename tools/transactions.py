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

    return ToolResult(
        success=True,
        data={
            "transaction_ref": tx.transaction_ref,
            "amount": tx.amount,
            "currency": tx.currency,
            "status": tx.status,
            "failure_reason": tx.failure_reason,
            "fraud_score": tx.fraud_score,
            "created_at": tx.created_at.isoformat()
        }
    )


async def get_recent_transactions(repo: BankingRepository, customer_id: int, limit: int = 5) -> ToolResult:
    """Lists recent transactions for customer."""
    txs = await repo.get_recent_transactions(customer_id, limit=limit)
    return ToolResult(
        success=True,
        data={
            "transactions": [
                {
                    "transaction_ref": t.transaction_ref,
                    "amount": t.amount,
                    "currency": t.currency,
                    "status": t.status,
                    "failure_reason": t.failure_reason,
                    "created_at": t.created_at.isoformat()
                }
                for t in txs
            ]
        }
    )

