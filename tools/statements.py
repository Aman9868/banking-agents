"""Account Statement & Transaction Explanation Banking Tools."""

from typing import Optional, Dict, Any
from database.repositories.banking_repo import BankingRepository
from services.statements.statement_service import StatementService
from services.transactions.transaction_explainer import TransactionExplainer
from tools.base import ToolResult
import structlog

logger = structlog.get_logger(__name__)


async def generate_account_statement(
    repo: BankingRepository,
    customer_external_id: str,
    period_type: Optional[str] = None,
    account_number: Optional[str] = None
) -> ToolResult:
    """
    Generates an official NovaBank account statement with financial summary,
    chronological ledger, running balances, and downloadable PDF.
    """
    try:
        service = StatementService(repo)
        result = await service.generate_statement(
            customer_external_id=customer_external_id,
            period_type=period_type,
            account_number=account_number
        )
        return ToolResult(
            success=True,
            data=result
        )
    except Exception as e:
        logger.error("generate_account_statement_failed", error=str(e), customer_id=customer_external_id)
        return ToolResult(
            success=False,
            error=f"Failed to generate statement: {str(e)}"
        )


async def explain_transaction(
    repo: BankingRepository,
    customer_external_id: str,
    transaction_ref: Optional[str] = None,
    query_type: Optional[str] = None
) -> ToolResult:
    """
    Analyzes and explains a specific or latest transaction, detailing
    decline root causes, cooling-off policies, or spending breakdowns.
    """
    try:
        explainer = TransactionExplainer(repo)
        result = await explainer.explain_transaction_or_spending(
            customer_external_id=customer_external_id,
            transaction_ref=transaction_ref,
            query_type=query_type
        )
        if not result.get("success"):
            return ToolResult(
                success=False,
                error=result.get("message", "Unable to analyze transaction.")
            )
        return ToolResult(
            success=True,
            data=result
        )
    except Exception as e:
        logger.error("explain_transaction_failed", error=str(e), customer_id=customer_external_id)
        return ToolResult(
            success=False,
            error=f"Failed to explain transaction: {str(e)}"
        )

