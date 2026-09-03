"""Beneficiary-related banking tools."""

from typing import Optional
from database.repositories.banking_repo import BankingRepository
from security.pii import mask_account_number
from tools.base import ToolResult


async def get_beneficiary(repo: BankingRepository, customer_id: int, name: str) -> ToolResult:
    """Finds a registered beneficiary by name for the given customer."""
    bene = await repo.find_beneficiary_by_name(customer_id, name)
    if not bene:
        return ToolResult(
            success=False,
            error=f"No beneficiary found matching name '{name}'."
        )

    return ToolResult(
        success=True,
        data={
            "beneficiary_id": bene.id,
            "name": bene.name,
            "account_number": bene.account_number,
            "masked_account": mask_account_number(bene.account_number),
            "ifsc_code": bene.ifsc_code,
            "status": bene.status
        }
    )


async def list_beneficiaries(repo: BankingRepository, customer_id: int) -> ToolResult:
    """Lists all registered beneficiaries for the customer."""
    benes = await repo.get_beneficiaries(customer_id)
    return ToolResult(
        success=True,
        data={
            "beneficiaries": [
                {
                    "beneficiary_id": b.id,
                    "name": b.name,
                    "masked_account": mask_account_number(b.account_number),
                    "ifsc_code": b.ifsc_code,
                    "status": b.status
                }
                for b in benes
            ]
        }
    )

