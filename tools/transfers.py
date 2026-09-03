"""Transfer execution banking tools."""

import uuid
from typing import Optional
from database.repositories.banking_repo import BankingRepository
from security.pii import mask_account_number
from database.models.banking import Account
from tools.base import ToolResult


async def initiate_transfer(
    repo: BankingRepository,
    customer_id: int,
    source_account_id: int,
    beneficiary_id: int,
    amount: float,
    idempotency_key: str,
    fraud_score: float = 0.0
) -> ToolResult:
    """
    Executes a transfer against Core Banking ledger.
    Debits the source account and creates an authoritative transaction record.
    """
    if amount <= 0:
        return ToolResult(success=False, error="Transfer amount must be strictly greater than zero.")

    # 1. Check source account
    account = await repo.session.get(Account, source_account_id)
    if not account or account.customer_id != customer_id:
        return ToolResult(success=False, error="Invalid source account or account does not belong to customer.")

    if account.status != "ACTIVE":
        return ToolResult(success=False, error=f"Source account is {account.status}. Transfers not permitted.")

    if account.balance < amount:
        return ToolResult(
            success=False,
            error=f"Insufficient funds. Available balance: ₹{account.balance:,.2f}, Requested: ₹{amount:,.2f}."
        )

    # 2. Debit source account
    debit_success = await repo.update_account_balance(source_account_id, -amount)
    if not debit_success:
        return ToolResult(success=False, error="Failed to debit source account due to concurrency conflict.")

    # 3. Create Transaction record
    tx_ref = f"TXN-{uuid.uuid4().hex[:8].upper()}"
    tx = await repo.create_transaction(
        transaction_ref=tx_ref,
        customer_id=customer_id,
        source_account_id=source_account_id,
        beneficiary_id=beneficiary_id,
        amount=amount,
        status="COMPLETED",
        fraud_score=fraud_score,
        idempotency_key=idempotency_key
    )

    return ToolResult(
        success=True,
        data={
            "transaction_ref": tx.transaction_ref,
            "amount": tx.amount,
            "currency": tx.currency,
            "status": tx.status,
            "remaining_balance": account.balance,
            "message": f"Transfer of ₹{amount:,.2f} completed successfully. Reference ID: {tx.transaction_ref}."
        }
    )
