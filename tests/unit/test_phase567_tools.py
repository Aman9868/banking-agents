"""Unit tests for Cards, Loans, Bill Payments, and Knowledge RAG tools."""

import pytest
import math
from database.init_db import init_database, seed_mock_data
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from tools.cards import freeze_card, unfreeze_card, set_card_limits, get_cards
from tools.loans import compute_emi, calculate_emi_tool, check_loan_eligibility_tool, apply_loan_tool
from tools.payments import fetch_bill_tool, verify_upi_id_tool
from tools.knowledge import search_knowledge_base_tool, create_support_ticket_tool


@pytest.fixture(scope="module", autouse=True)
async def setup_db():
    await init_database()
    await seed_mock_data()


def test_emi_mathematical_precision():
    # Test formula: P=500000, r=10.5% (monthly: 10.5/12/100), n=36 months
    principal = 500000.0
    rate = 10.5
    months = 36
    emi = compute_emi(principal, rate, months)
    # Manual verification: 500000 * 0.00875 * (1.00875)^36 / ((1.00875)^36 - 1) ≈ 16254.89
    assert 16200 < emi < 16300


@pytest.mark.asyncio
async def test_card_freeze_and_unfreeze():
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        customer_id = 1

        # 1. Freeze debit card
        freeze_res = await freeze_card(repo, customer_id, card_type="DEBIT")
        assert freeze_res.success is True
        assert freeze_res.data["status"] == "FROZEN"
        assert "frozen" in freeze_res.data["message"].lower()

        # 2. Unfreeze debit card
        unfreeze_res = await unfreeze_card(repo, customer_id, card_type="DEBIT")
        assert unfreeze_res.success is True
        assert unfreeze_res.data["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_card_spending_limit_update():
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        customer_id = 1

        res = await set_card_limits(repo, customer_id, card_type="DEBIT", online_limit=35000.0)
        assert res.success is True
        assert res.data["daily_online_limit"] == 35000.0


@pytest.mark.asyncio
async def test_loan_eligibility_check():
    # High income vs low EMI -> Eligible
    res_eligible = await check_loan_eligibility_tool(
        monthly_income=100000.0,
        existing_emi=10000.0,
        requested_amount=300000.0,
        tenure_months=36
    )
    assert res_eligible.data["eligible"] is True

    # Low income vs high requested amount -> Ineligible
    res_ineligible = await check_loan_eligibility_tool(
        monthly_income=25000.0,
        existing_emi=10000.0,
        requested_amount=1500000.0,
        tenure_months=12
    )
    assert res_ineligible.data["eligible"] is False


@pytest.mark.asyncio
async def test_bill_fetch_and_upi_verification():
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)

        # Bill fetch
        bill_res = await fetch_bill_tool(repo, "Tata Power", "CONS-1002")
        assert bill_res.success is True
        assert bill_res.data["amount_due"] > 0

        # UPI Verification
        upi_res = await verify_upi_id_tool("rahul@okaxis")
        assert upi_res.success is True
        assert upi_res.data["resolved_name"] == "Rahul"

        invalid_upi = await verify_upi_id_tool("notanemail")
        assert invalid_upi.success is False


@pytest.mark.asyncio
async def test_knowledge_base_search_and_ticket_creation():
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)

        # Knowledge search
        kb_res = await search_knowledge_base_tool(repo, "savings interest rate", limit=2)
        assert kb_res.success is True
        assert len(kb_res.data["results"]) > 0

        # Create Ticket
        ticket_res = await create_support_ticket_tool(
            repo,
            customer_id=1,
            subject="Incorrect fee charged",
            description="A fee of 50 rupees was debited yesterday.",
            priority="HIGH"
        )
        assert ticket_res.success is True
        assert ticket_res.data["ticket_ref"].startswith("TCK-")

