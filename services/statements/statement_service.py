"""Enterprise Account Statement Service for NovaBank."""

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Tuple, List
import structlog

from database.repositories.banking_repo import BankingRepository
from security.pii import mask_account_number
from services.statements.pdf_generator import generate_statement_pdf, STATEMENTS_STORAGE_DIR

logger = structlog.get_logger(__name__)


class StatementPeriod:
    LAST_6_MONTHS = "LAST_6_MONTHS"
    LAST_3_MONTHS = "LAST_3_MONTHS"
    LAST_MONTH = "LAST_MONTH"
    THIS_WEEK = "THIS_WEEK"
    CUSTOM = "CUSTOM"


def resolve_date_range(
    period_str: Optional[str] = None,
    custom_start: Optional[datetime] = None,
    custom_end: Optional[datetime] = None
) -> Tuple[datetime, datetime, str]:
    """
    Resolves date range from period token or natural language hints.
    Defaults to LAST_6_MONTHS if unspecified.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    p_lower = (period_str or "").lower()

    if "this week" in p_lower or "past week" in p_lower or "7 day" in p_lower:
        start_date = now - timedelta(days=7)
        return start_date, now, StatementPeriod.THIS_WEEK

    if "last month" in p_lower or "1 month" in p_lower or "past month" in p_lower or "30 day" in p_lower:
        start_date = now - timedelta(days=30)
        return start_date, now, StatementPeriod.LAST_MONTH

    if "3 month" in p_lower or "quarter" in p_lower or "90 day" in p_lower:
        start_date = now - timedelta(days=90)
        return start_date, now, StatementPeriod.LAST_3_MONTHS

    if "6 month" in p_lower or "half year" in p_lower or "180 day" in p_lower:
        start_date = now - timedelta(days=180)
        return start_date, now, StatementPeriod.LAST_6_MONTHS

    if custom_start and custom_end:
        return custom_start, custom_end, StatementPeriod.CUSTOM

    # Default to LAST_6_MONTHS as requested in banking requirements
    return now - timedelta(days=180), now, StatementPeriod.LAST_6_MONTHS


class StatementService:
    """Orchestrates statement generation, running balance math, and PDF output."""

    def __init__(self, repo: BankingRepository):
        self.repo = repo

    async def generate_statement(
        self,
        customer_external_id: str,
        period_type: Optional[str] = None,
        account_number: Optional[str] = None,
        custom_start: Optional[datetime] = None,
        custom_end: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Generates account statement for customer and creates downloadable PDF.
        """
        customer = await self.repo.get_customer_by_external_id(customer_external_id)
        if not customer:
            raise ValueError(f"Customer '{customer_external_id}' not found.")

        accounts = await self.repo.get_accounts_by_customer_id(customer.id)
        if not accounts:
            raise ValueError(f"No accounts found for customer '{customer_external_id}'.")

        # Select target account (or default to primary active account)
        target_account = None
        if account_number:
            for acc in accounts:
                if acc.account_number == account_number:
                    target_account = acc
                    break
        if not target_account:
            active_accs = [a for a in accounts if a.status == "ACTIVE"]
            target_account = max(active_accs or accounts, key=lambda a: (a.balance, -a.id))

        # Resolve date boundaries
        start_date, end_date, resolved_period = resolve_date_range(period_type, custom_start, custom_end)

        # Query transactions within date range for target account
        tx_models = await self.repo.get_transactions_in_range(
            customer_id=customer.id,
            start_date=start_date,
            end_date=end_date,
            account_id=target_account.id
        )

        statement_id = f"STMT-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        # Calculate accounting summary and ledger running balances
        total_credits = 0.0
        total_debits = 0.0

        for tx in tx_models:
            if tx.status == "COMPLETED":
                # In current transfer model, transactions from source_account are debits
                total_debits += tx.amount

        current_balance = float(target_account.balance)
        closing_balance = current_balance
        opening_balance = closing_balance + total_debits - total_credits

        # Build chronological ledger entries
        ledger_entries: List[Dict[str, Any]] = []
        running_bal = opening_balance

        for tx in tx_models:
            created_dt = tx.created_at
            date_str = created_dt.strftime("%d %b %Y, %I:%M %p") if hasattr(created_dt, "strftime") else str(created_dt)
            
            bene_name = tx.beneficiary.name if tx.beneficiary else "External Beneficiary"
            
            if tx.status == "COMPLETED":
                running_bal -= tx.amount
                description = f"Funds Transfer to {bene_name}"
                tx_type = "DEBIT"
                amount = tx.amount
            elif tx.status == "DECLINED":
                description = f"Declined: Transfer to {bene_name} ({tx.failure_reason or 'Policy failure'})"
                tx_type = "DECLINED"
                amount = tx.amount
            else:
                description = f"Transfer to {bene_name} ({tx.status})"
                tx_type = tx.status
                amount = tx.amount

            ledger_entries.append({
                "date": date_str,
                "description": description,
                "reference": tx.transaction_ref,
                "type": tx_type,
                "amount": amount,
                "running_balance": running_bal
            })

        net_cashflow = total_credits - total_debits

        statement_data = {
            "statement_id": statement_id,
            "generated_at": datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p"),
            "account_info": {
                "account_number": target_account.account_number,
                "masked_account": mask_account_number(target_account.account_number),
                "account_type": target_account.account_type,
                "status": target_account.status,
                "currency": target_account.currency or "INR"
            },
            "customer_info": {
                "full_name": customer.full_name,
                "customer_external_id": customer.external_id,
                "email": customer.email,
                "company_name": getattr(customer, "company_name", None),
                "gstin": getattr(customer, "gstin", None)
            },
            "period": {
                "period_code": resolved_period,
                "start_date": start_date.strftime("%d %b %Y"),
                "end_date": end_date.strftime("%d %b %Y")
            },
            "summary": {
                "opening_balance": opening_balance,
                "total_credits": total_credits,
                "total_debits": total_debits,
                "net_cashflow": net_cashflow,
                "closing_balance": closing_balance
            },
            "transactions": ledger_entries
        }

        # Generate official PDF file
        pdf_filename = f"{statement_id}.pdf"
        pdf_path = os.path.join(STATEMENTS_STORAGE_DIR, pdf_filename)
        pdf_bytes = generate_statement_pdf(statement_data, output_filename=pdf_path)

        download_url = f"/api/v1/statements/download/{statement_id}.pdf"

        logger.info(
            "statement_generated_successfully",
            statement_id=statement_id,
            customer_id=customer_external_id,
            tx_count=len(ledger_entries),
            pdf_path=pdf_path
        )

        return {
            "statement_id": statement_id,
            "download_url": download_url,
            "file_path": pdf_path,
            "pdf_bytes_len": len(pdf_bytes),
            "account": statement_data["account_info"],
            "period": statement_data["period"],
            "summary": statement_data["summary"],
            "transactions_count": len(ledger_entries),
            "transactions_preview": ledger_entries[-5:] if ledger_entries else []
        }
