"""Tests for New User Onboarding & Persona Switching."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from database.init_db import init_database, seed_mock_data
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await init_database()
    await seed_mock_data()


@pytest.mark.asyncio
async def test_list_customers_and_guest_prospect():
    """Verify /api/v1/chat/customers lists active customers and guest prospect."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/chat/customers")
        assert res.status_code == 200
        data = res.json()
        assert "customers" in data
        assert len(data["customers"]) >= 1
        assert any(c["external_id"] == "CUST-1001" for c in data["customers"])
        assert "guest_prospect" in data
        assert data["guest_prospect"]["external_id"] == "GUEST-PROSPECT"


@pytest.mark.asyncio
async def test_new_user_onboarding_multi_turn_flow():
    """Test full conversational onboarding flow for an unregistered prospect."""
    import uuid
    transport = ASGITransport(app=app)
    thread_id = f"THREAD-ONBOARDING-{uuid.uuid4().hex[:8]}"
    prospect_id = f"GUEST-PROSPECT-{uuid.uuid4().hex[:6]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Request account opening
        r1 = await client.post("/api/v1/chat", json={
            "message": "I want to open a new savings account with NovaBank",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r1.status_code == 200
        data1 = r1.json()
        assert "full name" in data1["response"].lower()

        # Step 2: Provide full name
        r2 = await client.post("/api/v1/chat", json={
            "message": "Kabir Verma",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r2.status_code == 200
        data2 = r2.json()
        assert "date of birth" in data2["response"].lower()

        # Step 3: Provide DOB
        r3 = await client.post("/api/v1/chat", json={
            "message": "1994-06-25",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r3.status_code == 200
        data3 = r3.json()
        assert "email" in data3["response"].lower()

        # Step 4: Provide email -> Provisions Account & Customer
        applicant_email = f"kabir.{uuid.uuid4().hex[:6]}@example.com"
        r4 = await client.post("/api/v1/chat", json={
            "message": applicant_email,
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r4.status_code == 200
        data4 = r4.json()
        assert "congratulations" in data4["response"].lower()
        assert data4["widget_type"] == "ACCOUNT_CARD"
        assert data4["widget_data"] is not None
        assert data4["widget_data"]["full_name"] == "Kabir Verma"
        assert data4["widget_data"]["account_number"].startswith("SB")
        assert data4["widget_data"]["status"] == "ACTIVE & KYC VERIFIED"
