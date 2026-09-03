"""Loan calculation, eligibility, and application banking tools."""

import uuid
import math
from typing import Optional, Dict, Any
from database.repositories.banking_repo import BankingRepository
from tools.base import ToolResult


def compute_emi(principal: float, annual_rate_pct: float, tenure_months: int) -> float:
    """Deterministic formula: E = P * r * (1+r)^n / ((1+r)^n - 1)"""
    if principal <= 0 or tenure_months <= 0:
        return 0.0
    monthly_rate = (annual_rate_pct / 100.0) / 12.0
    if monthly_rate == 0:
        return round(principal / tenure_months, 2)

    factor = math.pow(1.0 + monthly_rate, tenure_months)
    emi = principal * monthly_rate * factor / (factor - 1.0)
    return round(emi, 2)


async def calculate_emi_tool(principal: float, tenure_months: int, annual_rate_pct: float = 10.5) -> ToolResult:
    """Calculates exact monthly EMI, total interest, and total payable amount."""
    emi = compute_emi(principal, annual_rate_pct, tenure_months)
    total_payable = round(emi * tenure_months, 2)
    total_interest = round(total_payable - principal, 2)

    return ToolResult(
        success=True,
        data={
            "principal": principal,
            "annual_rate_pct": annual_rate_pct,
            "tenure_months": tenure_months,
            "monthly_emi": emi,
            "total_interest": total_interest,
            "total_payable": total_payable,
            "message": f"For a loan of ₹{principal:,.2f} over {tenure_months} months at {annual_rate_pct:.2f}% p.a., your estimated monthly EMI is ₹{emi:,.2f} (Total interest: ₹{total_interest:,.2f})."
        }
    )


async def check_loan_eligibility_tool(
    monthly_income: float,
    existing_emi: float,
    requested_amount: float,
    tenure_months: int,
    annual_rate_pct: float = 10.5
) -> ToolResult:
    """Evaluates Debt-to-Income (DTI) ratio against standard 50% threshold."""
    new_emi = compute_emi(requested_amount, annual_rate_pct, tenure_months)
    total_projected_emi = existing_emi + new_emi
    max_allowable_emi = monthly_income * 0.50

    is_eligible = total_projected_emi <= max_allowable_emi
    dti_ratio = round((total_projected_emi / monthly_income) * 100, 1) if monthly_income > 0 else 100.0

    return ToolResult(
        success=True,
        data={
            "eligible": is_eligible,
            "projected_emi": new_emi,
            "dti_ratio_pct": dti_ratio,
            "max_allowable_emi": max_allowable_emi,
            "message": (
                f"Eligibility Confirmed: You qualify for this loan. Your projected EMI of ₹{new_emi:,.2f} sits safely within your borrowing limit (DTI: {dti_ratio}%)."
                if is_eligible else
                f"Eligibility Alert: The requested loan exceeds the recommended 50% debt-to-income threshold (Projected DTI: {dti_ratio}%). Consider increasing tenure to lower EMI."
            )
        }
    )


async def apply_loan_tool(
    repo: BankingRepository,
    customer_id: int,
    loan_type: str,
    amount: float,
    tenure_months: int,
    annual_income: float,
    annual_rate_pct: float = 10.5
) -> ToolResult:
    """Creates a formal loan application in the core banking system."""
    emi = compute_emi(amount, annual_rate_pct, tenure_months)
    app_ref = f"LN-APP-{uuid.uuid4().hex[:8].upper()}"

    loan_record = await repo.create_loan_application(
        application_ref=app_ref,
        customer_id=customer_id,
        loan_type=loan_type.upper(),
        amount=amount,
        tenure_months=tenure_months,
        interest_rate=annual_rate_pct,
        monthly_emi=emi,
        annual_income=annual_income
    )

    return ToolResult(
        success=True,
        data={
            "application_ref": loan_record.application_ref,
            "loan_type": loan_record.loan_type,
            "amount": loan_record.amount,
            "tenure_months": loan_record.tenure_months,
            "monthly_emi": loan_record.monthly_emi,
            "status": loan_record.status,
            "message": f"Your {loan_record.loan_type} loan application ({loan_record.application_ref}) for ₹{amount:,.2f} has been submitted! Monthly EMI will be ₹{emi:,.2f}. Our credit underwriting team will review your application within 24 hours."
        }
    )


async def get_loan_status_tool(repo: BankingRepository, customer_id: int) -> ToolResult:
    """Lists existing loan applications for customer."""
    apps = await repo.get_loan_applications(customer_id)
    return ToolResult(
        success=True,
        data={
            "applications": [
                {
                    "application_ref": a.application_ref,
                    "loan_type": a.loan_type,
                    "amount": a.amount,
                    "tenure_months": a.tenure_months,
                    "monthly_emi": a.monthly_emi,
                    "status": a.status,
                    "created_at": a.created_at.isoformat()
                }
                for a in apps
            ]
        }
    )

