"""Unit and Integration tests for Bank Statements, PDF generation, and Transaction Explainer."""

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from database.connection import AsyncSessionLocal
from database.init_db import init_database, seed_mock_data
from database.repositories.banking_repo import BankingRepository
from services.statements.statement_service import StatementService, resolve_date_range, StatementPeriod
from services.transactions.transaction_explainer import TransactionExplainer
from gateway.tool_gateway.gateway import tool_gateway
from gateway.tool_gateway.permissions import AgentRole
from gateway.llm.router import route_banking_request, BankingIntent, BankingSubIntent
from apps.api.main import app


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Initializes and seeds database before each test run."""
    await init_database()
    await seed_mock_data()


@pytest.mark.asyncio
async def test_date_range_resolution():
    """Verifies natural language date range parsing."""
    s, e, p = resolve_date_range("this week statement")
    assert p == StatementPeriod.THIS_WEEK

    s, e, p = resolve_date_range("last month statement")
    assert p == StatementPeriod.LAST_MONTH

    s, e, p = resolve_date_range("3 months statement")
    assert p == StatementPeriod.LAST_3_MONTHS

    s, e, p = resolve_date_range("last 6 month statement")
    assert p == StatementPeriod.LAST_6_MONTHS

    s, e, p = resolve_date_range("")
    assert p == StatementPeriod.LAST_6_MONTHS


@pytest.mark.asyncio
async def test_statement_service_and_pdf_generation():
    """Verifies statement generation, math reconciliation, and PDF creation."""
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        service = StatementService(repo)

        res = await service.generate_statement(
            customer_external_id="CUST-1001",
            period_type="LAST_6_MONTHS"
        )

        assert res["statement_id"].startswith("STMT-")
        assert res["download_url"].startswith("/api/v1/statements/download/")
        assert os.path.exists(res["file_path"])
        assert res["pdf_bytes_len"] > 1000

        # Verify PDF header magic bytes (%PDF)
        with open(res["file_path"], "rb") as f:
            header = f.read(5)
            assert header == b"%PDF-"

        summary = res["summary"]
        assert "opening_balance" in summary
        assert "closing_balance" in summary
        assert summary["closing_balance"] == 100000.0


@pytest.mark.asyncio
async def test_transaction_explainer_declined_root_cause():
    """Verifies diagnosing declined transaction TXN-10091."""
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        explainer = TransactionExplainer(repo)

        res = await explainer.explain_transaction_or_spending(
            customer_external_id="CUST-1001",
            transaction_ref="TXN-10091",
            query_type="DECLINE_REASON"
        )

        assert res["success"] is True
        diag = res["diagnosis"]
        assert diag["is_declined"] is True
        assert diag["status"] == "DECLINED"
        assert "Cool-Off" in diag["reason_title"] or "Verification" in diag["reason_title"]
        assert "actionable_remedy" in diag
        assert "TXN-10091" in res["conversational_text"]


@pytest.mark.asyncio
async def test_tool_gateway_statement_and_explainer_execution():
    """Verifies RBAC execution of statements and transaction explanation."""
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        customer = await repo.get_customer_by_external_id("CUST-1001")

        # 1. Statement tool execution
        stmt_tool_res = await tool_gateway.execute_tool(
            agent_role=AgentRole.SUPERVISOR.value,
            tool_name="generate_account_statement",
            repo=repo,
            customer_id=customer.id,
            parameters={"period_type": "THIS_WEEK"}
        )
        assert stmt_tool_res.success is True
        assert "statement_id" in stmt_tool_res.data

        # 2. Transaction explanation tool execution
        explain_tool_res = await tool_gateway.execute_tool(
            agent_role=AgentRole.SUPERVISOR.value,
            tool_name="explain_transaction",
            repo=repo,
            customer_id=customer.id,
            parameters={"transaction_ref": "TXN-10091"}
        )
        assert explain_tool_res.success is True
        assert explain_tool_res.data["diagnosis"]["status"] == "DECLINED"


@pytest.mark.asyncio
async def test_router_statement_and_decline_intents():
    """Verifies routing for statements (with typos) and decline questions."""
    # Typo in statement
    dec1 = await route_banking_request("send me my last 6 month sattemnet")
    assert dec1.intent == BankingIntent.STATEMENT_REQUEST
    assert dec1.entities.period_type == "LAST_6_MONTHS"

    # This week statement
    dec2 = await route_banking_request("I need this week account statement")
    assert dec2.intent == BankingIntent.STATEMENT_REQUEST
    assert dec2.entities.period_type == "THIS_WEEK"

    # Why was my transaction declined
    dec3 = await route_banking_request("Why was my last transaction declined?")
    assert dec3.intent == BankingIntent.TRANSACTION_INQUIRY
    assert dec3.sub_intent == BankingSubIntent.EXPLAIN_DECLINE

    # Explain my spending
    dec4 = await route_banking_request("Can you explain my last transaction?")
    assert dec4.intent == BankingIntent.TRANSACTION_INQUIRY
    assert dec4.sub_intent == BankingSubIntent.EXPLAIN_LAST_TXN


@pytest.mark.asyncio
async def test_statement_download_api_endpoint():
    """Verifies PDF download endpoint via HTTP."""
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        service = StatementService(repo)
        stmt = await service.generate_statement(customer_external_id="CUST-1001")
        stmt_id = stmt["statement_id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Download with .pdf
        resp = await client.get(f"/api/v1/statements/download/{stmt_id}.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF-")

        # Download without .pdf
        resp2 = await client.get(f"/api/v1/statements/download/{stmt_id}")
        assert resp2.status_code == 200
        assert resp2.content.startswith(b"%PDF-")

        # Non-existent statement
        resp_404 = await client.get("/api/v1/statements/download/STMT-99999999-XXXXXX.pdf")
        assert resp_404.status_code == 404

