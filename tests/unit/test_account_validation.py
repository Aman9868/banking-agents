"""Unit and Integration Tests for Production KYC & Profile Validation in Account Opening."""

import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from database.init_db import init_database, seed_mock_data
from agents.account.validators import validate_email, validate_date_of_birth, validate_full_name


@pytest.fixture(scope="module", autouse=True)
async def setup_db():
    await init_database()
    await seed_mock_data()


def test_validate_email_unit():
    """Verify email validator rejects invalid inputs and accepts valid ones."""
    # Rejections
    for invalid in ["na", "N/A", "none", "test", "user@", "@domain.com", "user.domain", "user@domain", "a@b.c", ""]:
        is_valid, cleaned, err = validate_email(invalid)
        assert not is_valid, f"Expected {invalid} to be rejected"
        assert err is not None

    # Acceptances
    for valid in ["user@example.com", "john.doe@novabank.in", "kabir.verma+test@gmail.com", "customer123@yahoo.co.in"]:
        is_valid, cleaned, err = validate_email(valid)
        assert is_valid, f"Expected {valid} to be accepted"
        assert err is None
        assert "@" in cleaned


def test_validate_date_of_birth_unit():
    """Verify DOB validator enforces format, legal age (18+), and plausibility."""
    # Rejections
    for invalid in ["na", "none", "tomorrow", "invalid-date", "2030-01-01", "2024-01-01", "1800-01-01", "32/01/1990"]:
        is_valid, cleaned, err = validate_date_of_birth(invalid)
        assert not is_valid, f"Expected {invalid} to be rejected"
        assert err is not None

    # Acceptances (adults 18+)
    for valid in ["1995-08-15", "15/08/1995", "15-08-1995", "12 March 1997", "12th March 1997", "March 12, 1997"]:
        is_valid, cleaned, err = validate_date_of_birth(valid)
        assert is_valid, f"Expected {valid} to be accepted"
        assert err is None
        assert cleaned is not None
        # Must be standardized YYYY-MM-DD
        assert len(cleaned) == 10
        assert cleaned.count("-") == 2


def test_validate_full_name_unit():
    """Verify name validator rejects placeholders/numbers and formats properly."""
    # Rejections
    for invalid in ["na", "none", "n/a", "test", "12345", "!", "a", ""]:
        is_valid, cleaned, err = validate_full_name(invalid)
        assert not is_valid, f"Expected {invalid} to be rejected"
        assert err is not None

    # Acceptances
    is_valid, cleaned, _ = validate_full_name("golu")
    assert is_valid
    assert cleaned == "Golu"

    is_valid, cleaned, _ = validate_full_name("rohan verma")
    assert is_valid
    assert cleaned == "Rohan Verma"


@pytest.mark.asyncio
async def test_kyc_rejection_and_recovery_flow():
    """Test multi-turn flow where user enters invalid 'na' for DOB and Email and is rejected until valid."""
    transport = ASGITransport(app=app)
    thread_id = f"THREAD-KYC-VAL-{uuid.uuid4().hex[:8]}"
    prospect_id = f"GUEST-VAL-{uuid.uuid4().hex[:6]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Initiate Account Opening
        r1 = await client.post("/api/v1/chat", json={
            "message": "I want to open a new savings account",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r1.status_code == 200
        assert "full name" in r1.json()["response"].lower()

        # 2. Provide Full Name
        r2 = await client.post("/api/v1/chat", json={
            "message": "Golu",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r2.status_code == 200
        assert "date of birth" in r2.json()["response"].lower()

        # 3. Provide INVALID DOB ('na') -> MUST BE REJECTED
        r3 = await client.post("/api/v1/chat", json={
            "message": "na",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r3.status_code == 200
        data3 = r3.json()
        assert "date of birth" in data3["response"].lower() or "valid" in data3["response"].lower()
        # Must NOT have moved to email
        assert "email" not in data3["response"].lower()

        # 4. Provide UNDERAGE DOB (e.g. 2020) -> MUST BE REJECTED
        r4 = await client.post("/api/v1/chat", json={
            "message": "2020-05-15",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r4.status_code == 200
        data4 = r4.json()
        assert "18" in data4["response"]

        # 5. Provide VALID DOB (Adult) -> Moves to Email
        r5 = await client.post("/api/v1/chat", json={
            "message": "15/08/1998",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r5.status_code == 200
        data5 = r5.json()
        assert "email" in data5["response"].lower()

        # 6. Provide INVALID Email ('na') -> MUST BE REJECTED
        r6 = await client.post("/api/v1/chat", json={
            "message": "na",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r6.status_code == 200
        data6 = r6.json()
        assert "email" in data6["response"].lower() or "valid" in data6["response"].lower()
        # Account must NOT have been opened
        assert "congratulations" not in data6["response"].lower()

        # 7. Provide VALID Email -> Account Opens Successfully!
        r7 = await client.post("/api/v1/chat", json={
            "message": "golu.kumar@example.com",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r7.status_code == 200
        data7 = r7.json()
        assert "congratulations" in data7["response"].lower()
        assert data7["widget_type"] == "ACCOUNT_CARD"
        assert data7["widget_data"]["full_name"] == "Golu"
        assert data7["widget_data"]["status"] == "ACTIVE & KYC VERIFIED"
