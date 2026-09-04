"""Official Bank Account Statement API Endpoints."""

import os
import re
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import structlog

from services.statements.pdf_generator import STATEMENTS_STORAGE_DIR
from database.connection import get_db_session
from database.repositories.banking_repo import BankingRepository
from services.statements.statement_service import StatementService
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/statements", tags=["Account Statements"])


class StatementGenerateRequest(BaseModel):
    customer_external_id: str = Field(..., description="Customer external ID (e.g. CUST-1001)")
    period_type: Optional[str] = Field("LAST_6_MONTHS", description="Period type: LAST_6_MONTHS, LAST_3_MONTHS, LAST_MONTH, THIS_WEEK")
    account_number: Optional[str] = Field(None, description="Optional account number override")


@router.get("/download/{statement_id}")
async def download_statement_pdf(statement_id: str):
    """
    Secure download endpoint for official NovaBank statement PDF documents.
    Validates identifier format to prevent directory traversal.
    """
    # Strip optional .pdf extension if provided
    clean_id = statement_id[:-4] if statement_id.endswith(".pdf") else statement_id

    # Sanitize input: only alphanumeric and hyphen allowed
    if not re.match(r"^STMT-[A-Za-z0-9\-]+$", clean_id):
        raise HTTPException(status_code=400, detail="Invalid statement identifier format.")

    pdf_path = os.path.join(STATEMENTS_STORAGE_DIR, f"{clean_id}.pdf")

    # Guard against directory traversal
    resolved_path = os.path.realpath(pdf_path)
    if not resolved_path.startswith(os.path.realpath(STATEMENTS_STORAGE_DIR)):
        raise HTTPException(status_code=403, detail="Access denied.")

    if not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail="Statement PDF document not found or expired.")

    logger.info("statement_pdf_downloaded", statement_id=clean_id, path=resolved_path)

    return FileResponse(
        path=resolved_path,
        media_type="application/pdf",
        filename=f"NovaBank_Statement_{clean_id}.pdf",
        headers={
            "Content-Disposition": f"attachment; filename=NovaBank_Statement_{clean_id}.pdf",
            "Cache-Control": "private, max-age=3600"
        }
    )


@router.post("/generate")
async def generate_statement_endpoint(
    req: StatementGenerateRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Generates an account statement and PDF via REST API."""
    repo = BankingRepository(session)
    service = StatementService(repo)
    try:
        result = await service.generate_statement(
            customer_external_id=req.customer_external_id,
            period_type=req.period_type,
            account_number=req.account_number
        )
        return result
    except ValueError as val_err:
        raise HTTPException(status_code=404, detail=str(val_err))
    except Exception as exc:
        logger.error("api_generate_statement_error", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to generate account statement.")

