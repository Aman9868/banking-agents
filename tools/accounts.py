"""Account-related banking tools."""

from typing import Dict, Any
from database.repositories.banking_repo import BankingRepository
from security.pii import mask_account_number
from tools.base import ToolResult


async def get_balance(repo: BankingRepository, customer_id: int, account_number: str = None) -> ToolResult:
    """Retrieves current balance and account status."""
    accounts = await repo.get_accounts_by_customer_id(customer_id)
    if not accounts:
        return ToolResult(success=False, error="No accounts found for customer.")

    target_account = None
    if account_number:
        for acc in accounts:
            if acc.account_number == account_number:
                target_account = acc
                break

    if not target_account:
        # Default to primary active account with highest balance
        target_account = max(accounts, key=lambda a: (a.status == "ACTIVE", a.balance))

    return ToolResult(
        success=True,
        data={
            "account_id": target_account.id,
            "account_number": target_account.account_number,
            "masked_account": mask_account_number(target_account.account_number),
            "account_type": target_account.account_type,
            "balance": target_account.balance,
            "currency": target_account.currency,
            "status": target_account.status
        }
    )


async def get_accounts(repo: BankingRepository, customer_id: int) -> ToolResult:
    """Lists all accounts belonging to customer."""
    accounts = await repo.get_accounts_by_customer_id(customer_id)
    return ToolResult(
        success=True,
        data={
            "accounts": [
                {
                    "account_id": acc.id,
                    "account_number": acc.account_number,
                    "masked_account": mask_account_number(acc.account_number),
                    "account_type": acc.account_type,
                    "balance": acc.balance,
                    "currency": acc.currency,
                    "status": acc.status
                }
                for acc in accounts
            ]
        }
    )

