"""Bill Payments and UPI banking tools."""

import uuid
import re
from typing import Optional, Dict, Any
from database.repositories.banking_repo import BankingRepository
from tools.base import ToolResult


async def get_billers_tool(repo: BankingRepository, category: Optional[str] = None) -> ToolResult:
    """Lists supported utility and credit card billers."""
    billers = await repo.get_billers(category=category)
    return ToolResult(
        success=True,
        data={
            "billers": [
                {
                    "biller_id": b.id,
                    "code": b.biller_code,
                    "name": b.name,
                    "category": b.category,
                    "min_amount": b.min_amount
                }
                for b in billers
            ]
        }
    )


async def fetch_bill_tool(repo: BankingRepository, biller_name: str, consumer_number: str) -> ToolResult:
    """Fetches outstanding bill amount for the given consumer number."""
    biller = await repo.find_biller_by_name(biller_name)
    if not biller:
        return ToolResult(success=False, error=f"Biller '{biller_name}' is not registered in bill payment network.")

    # High-fidelity mock bill provider: generates predictable realistic bill based on consumer number
    simulated_bill_amount = 1450.0 if "elec" in biller.category.lower() else 999.0

    return ToolResult(
        success=True,
        data={
            "biller_id": biller.id,
            "biller_name": biller.name,
            "category": biller.category,
            "consumer_number": consumer_number,
            "amount_due": simulated_bill_amount,
            "due_date": "2026-09-20",
            "message": f"Outstanding bill for {biller.name} (Consumer No: {consumer_number}) is ₹{simulated_bill_amount:,.2f}, due on 2026-09-20."
        }
    )


async def pay_bill_tool(
    repo: BankingRepository,
    customer_id: int,
    biller_name: str,
    consumer_number: str,
    amount: float,
    source_account_id: int,
    idempotency_key: str
) -> ToolResult:
    """Debits source account and executes bill settlement with utility provider."""
    biller = await repo.find_biller_by_name(biller_name)
    if not biller:
        return ToolResult(success=False, error=f"Biller '{biller_name}' not found.")

    if amount <= 0:
        return ToolResult(success=False, error="Bill payment amount must be positive.")

    # 1. Check account balance and debit
    from database.models.banking import Account
    account = await repo.session.get(Account, source_account_id)
    if not account or account.customer_id != customer_id:
        return ToolResult(success=False, error="Invalid payment account.")

    if account.balance < amount:
        return ToolResult(
            success=False,
            error=f"Insufficient funds in account to pay bill. Balance: ₹{account.balance:,.2f}, Due: ₹{amount:,.2f}."
        )

    debit_ok = await repo.update_account_balance(source_account_id, -amount)
    if not debit_ok:
        return ToolResult(success=False, error="Failed to debit payment account.")

    # 2. Create Bill Payment record
    pay_ref = f"BIL-TXN-{uuid.uuid4().hex[:8].upper()}"
    payment = await repo.create_bill_payment(
        payment_ref=pay_ref,
        customer_id=customer_id,
        biller_id=biller.id,
        account_id=source_account_id,
        consumer_number=consumer_number,
        amount=amount,
        idempotency_key=idempotency_key
    )

    return ToolResult(
        success=True,
        data={
            "payment_ref": payment.payment_ref,
            "biller_name": biller.name,
            "consumer_number": consumer_number,
            "amount_paid": amount,
            "remaining_balance": account.balance,
            "status": "COMPLETED",
            "message": f"Bill payment of ₹{amount:,.2f} to {biller.name} successful! Reference ID: {payment.payment_ref}."
        }
    )


async def verify_upi_id_tool(upi_id: str) -> ToolResult:
    """Verifies UPI virtual payment address (VPA) format and resolves VPA title."""
    upi_pattern = r"^[\w\.\-]+@[\w\-]+$"
    if not re.match(upi_pattern, upi_id):
        return ToolResult(
            success=False,
            error=f"'{upi_id}' is not a valid UPI format. Expected format: username@bankhandle (e.g. rahul@okaxis)."
        )

    # Simulated NPCI VPA directory lookup
    resolved_name = upi_id.split("@")[0].replace(".", " ").title()
    return ToolResult(
        success=True,
        data={
            "upi_id": upi_id,
            "resolved_name": resolved_name,
            "status": "VERIFIED",
            "message": f"Verified UPI handle: {upi_id} registered to {resolved_name}."
        }
    )

