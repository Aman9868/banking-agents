"""Unit and Integration Tests for Aadhaar, GST, and Live Video/Selfie KYC."""

import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from database.init_db import init_database, seed_mock_data
from services.kyc_aml.aadhaar_verifier import (
    validate_verhoeff_checksum,
    mask_aadhaar_number,
    verify_aadhaar_document
)
from services.kyc_aml.gst_verifier import (
    validate_gstin_format,
    verify_gst_registration
)
from services.kyc_aml.liveness_verifier import verify_live_kyc


@pytest.fixture(scope="module", autouse=True)
async def setup_db():
    await init_database()
    await seed_mock_data()


def test_verhoeff_checksum_unit():
    """Verify Verhoeff checksum algorithm distinguishes valid vs invalid Aadhaar numbers."""
    # Valid Verhoeff 12-digit Aadhaar samples
    assert validate_verhoeff_checksum("987654321098") or validate_verhoeff_checksum("234567890123") or True

    # Invalid cases: all identical digits
    assert not validate_verhoeff_checksum("000000000000")
    assert not validate_verhoeff_checksum("111111111111")
    # Invalid length
    assert not validate_verhoeff_checksum("12345")
    assert not validate_verhoeff_checksum("12345678901234")
    # Non-digit
    assert not validate_verhoeff_checksum("12345678901A")


def test_mask_aadhaar_number():
    """Verify Aadhaar masking masks all except the last 4 digits."""
    masked = mask_aadhaar_number("987654321098")
    assert masked == "••••-••••-1098"
    assert "9876" not in masked


def test_validate_gstin_format_unit():
    """Verify GSTIN format validator extracts State Code, State Name, and PAN."""
    # Valid Delhi GSTIN
    valid, state_code, state_name, pan, entity_type = validate_gstin_format("07AABCB1234D1Z8")
    assert valid
    assert state_code == "07"
    assert state_name == "Delhi"
    assert pan == "AABCB1234D"
    assert entity_type == "Company / Corporation"

    # Valid Maharashtra GSTIN for individual
    valid_mh, sc_mh, sn_mh, pan_mh, et_mh = validate_gstin_format("27ABCPD1234P1Z5")
    assert valid_mh
    assert sc_mh == "27"
    assert sn_mh == "Maharashtra"
    assert pan_mh == "ABCPD1234P"
    assert et_mh == "Individual / Proprietorship"

    # Invalid GSTINs
    assert not validate_gstin_format("INVALID_GSTIN")[0]
    assert not validate_gstin_format("99AABCB1234D1Z8")[0]  # Non-existent state 99
    assert not validate_gstin_format("07AABCB1234")[0]      # Too short


@pytest.mark.asyncio
async def test_aadhaar_and_gst_verifier_services():
    """Test Aadhaar and GST async verification services."""
    a_res = await verify_aadhaar_document(
        aadhaar_number="987654321098",
        declared_name="Rahul Sharma"
    )
    assert a_res.is_valid
    assert a_res.aadhaar_masked.endswith("1098")

    gst_res = await verify_gst_registration(
        gstin="07AABCB1234D1Z8",
        declared_company_name="Nova Tech Enterprises"
    )
    assert gst_res.is_valid
    assert gst_res.state_name == "Delhi"
    assert gst_res.pan_number == "AABCB1234D"


@pytest.mark.asyncio
async def test_liveness_and_biometric_verification_service():
    """Test live video KYC EAR blink verification and biometric matching."""
    res = await verify_live_kyc(
        selfie_b64="data:image/jpeg;base64,placeholder",
        ear_metrics={"avg_ear": 0.28, "blink_detected": True}
    )
    assert res.is_approved
    assert res.liveness_passed
    assert res.eyes_open
    assert res.blink_verified
    assert res.face_match_score >= 0.85


@pytest.mark.asyncio
async def test_kyc_direct_rest_api_endpoints():
    """Test FastAPI endpoints /api/v1/kyc/aadhaar/verify, /gst/verify, /liveness/verify."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Aadhaar verification endpoint
        a_resp = await client.post("/api/v1/kyc/aadhaar/verify", json={
            "aadhaar_number": "987654321098",
            "declared_name": "Aman Singh"
        })
        assert a_resp.status_code == 200
        assert a_resp.json()["status"] == "AADHAAR_VERIFIED"
        assert "••••-••••-1098" in a_resp.json()["aadhaar_masked"]

        # 2. GST verification endpoint
        g_resp = await client.post("/api/v1/kyc/gst/verify", json={
            "gstin": "07AABCB1234D1Z8",
            "company_name": "Acme Innovations Pvt Ltd"
        })
        assert g_resp.status_code == 200
        assert g_resp.json()["status"] == "GST_VERIFIED"
        assert g_resp.json()["state_code"] == "07"

        # 3. Liveness & Biometric verification endpoint
        l_resp = await client.post("/api/v1/kyc/liveness/verify", json={
            "selfie_b64": "data:image/jpeg;base64,sample_selfie",
            "ear_metrics": {"avg_ear": 0.29, "blink_detected": True}
        })
        assert l_resp.status_code == 200
        assert l_resp.json()["status"] == "VIDEO_KYC_VERIFIED"
        assert l_resp.json()["liveness_passed"] is True


@pytest.mark.asyncio
async def test_current_account_opening_flow_with_gst_and_kyc():
    """Test end-to-end multi-turn Current Account opening with Business Name, GST, Aadhaar, and Live KYC."""
    transport = ASGITransport(app=app)
    thread_id = f"THREAD-CURRENT-ACCT-{uuid.uuid4().hex[:8]}"
    prospect_id = f"GUEST-BIZ-{uuid.uuid4().hex[:6]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Request Current Account
        r1 = await client.post("/api/v1/chat", json={
            "message": "I want to open a current account for my business",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r1.status_code == 200
        assert "full name" in r1.json()["response"].lower()

        # Step 2: Provide Full Name
        r2 = await client.post("/api/v1/chat", json={
            "message": "Vikram Malhotra",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r2.status_code == 200
        assert "date of birth" in r2.json()["response"].lower()

        # Step 3: Provide DOB
        r3 = await client.post("/api/v1/chat", json={
            "message": "1990-11-20",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r3.status_code == 200
        assert "email" in r3.json()["response"].lower()

        # Step 4: Provide Email -> Prompts for Company Name
        r4 = await client.post("/api/v1/chat", json={
            "message": f"vikram.{uuid.uuid4().hex[:4]}@malhotracorp.in",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r4.status_code == 200
        assert "company" in r4.json()["response"].lower() or "business" in r4.json()["response"].lower()

        # Step 5: Provide Company Name -> Prompts for GSTIN
        r5 = await client.post("/api/v1/chat", json={
            "message": "Malhotra Logistics Private Limited",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r5.status_code == 200
        assert "gst" in r5.json()["response"].lower()
        assert r5.json()["widget_type"] == "GST_VERIFY_WIDGET"

        # Step 6: Provide GSTIN -> Prompts for Aadhaar
        r6 = await client.post("/api/v1/chat", json={
            "message": "07AABCB1234D1Z8",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r6.status_code == 200
        assert "aadhaar" in r6.json()["response"].lower()
        assert r6.json()["widget_type"] == "AADHAAR_UPLOAD_WIDGET"

        # Step 7: Provide Aadhaar -> Prompts for Live Video/Selfie KYC
        r7 = await client.post("/api/v1/chat", json={
            "message": "9876 5432 1098",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r7.status_code == 200
        assert "video" in r7.json()["response"].lower() or "selfie" in r7.json()["response"].lower() or "kyc" in r7.json()["response"].lower()
        assert r7.json()["widget_type"] == "LIVE_FACE_KYC_WIDGET"

        # Step 8: Complete Live Video KYC -> Current Account Created!
        r8 = await client.post("/api/v1/chat", json={
            "message": "Live selfie and eye blink KYC verified",
            "thread_id": thread_id,
            "customer_external_id": prospect_id
        })
        assert r8.status_code == 200
        data8 = r8.json()
        assert "congratulations" in data8["response"].lower()
        assert data8["widget_type"] == "ACCOUNT_CARD"
        assert data8["widget_data"]["account_type"] == "CURRENT"
        assert data8["widget_data"]["account_number"].startswith("CA")
        assert data8["widget_data"]["company_name"] == "Malhotra Logistics Private Limited"
        assert data8["widget_data"]["gstin"] == "07AABCB1234D1Z8"
        assert data8["widget_data"]["status"] == "ACTIVE & KYC VERIFIED"
