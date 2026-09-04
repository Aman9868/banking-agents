"""REST API Endpoints for Direct KYC & Biometric Identity Verification."""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from services.kyc_aml.aadhaar_verifier import verify_aadhaar_document
from services.kyc_aml.gst_verifier import verify_gst_registration
from services.kyc_aml.liveness_verifier import verify_live_kyc
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/kyc", tags=["KYC Verification"])


class AadhaarVerifyRequest(BaseModel):
    aadhaar_number: str = Field(..., description="12-digit Indian Aadhaar number")
    declared_name: Optional[str] = Field("", description="Cardholder legal full name")
    image_b64: Optional[str] = Field(None, description="Base64 encoded Aadhaar card image")
    customer_id: Optional[int] = Field(None, description="Database customer ID")


class GSTVerifyRequest(BaseModel):
    gstin: str = Field(..., description="15-character GSTIN")
    company_name: str = Field(..., description="Registered Business or Company Name")
    business_type: Optional[str] = Field("Private Limited Company", description="Constitution of Business")
    certificate_b64: Optional[str] = Field(None, description="Base64 encoded Form GST REG-06 certificate")
    customer_id: Optional[int] = Field(None, description="Database customer ID")


class LivenessVerifyRequest(BaseModel):
    selfie_b64: str = Field(..., description="Live webcam selfie capture base64")
    aadhaar_b64: Optional[str] = Field(None, description="Aadhaar document base64 for face match")
    ear_metrics: Optional[Dict[str, Any]] = Field(None, description="Eye Aspect Ratio blink metrics")
    customer_id: Optional[int] = Field(None, description="Database customer ID")


@router.post("/aadhaar/verify")
async def handle_verify_aadhaar(req: AadhaarVerifyRequest):
    """Verifies Aadhaar number with Verhoeff checksum and multimodal Gemini Vision OCR."""
    res = await verify_aadhaar_document(
        aadhaar_number=req.aadhaar_number,
        declared_name=req.declared_name or "",
        image_b64=req.image_b64
    )
    if not res.is_valid:
        raise HTTPException(status_code=400, detail=res.error_message or "Aadhaar verification failed.")

    if req.customer_id:
        async with AsyncSessionLocal() as session:
            repo = BankingRepository(session)
            await repo.update_customer_aadhaar_kyc(
                customer_id=req.customer_id,
                aadhaar_masked=res.aadhaar_masked,
                aadhaar_data=res.details
            )
            await session.commit()

    return {
        "success": True,
        "aadhaar_masked": res.aadhaar_masked,
        "full_name_matched": res.full_name_matched,
        "dob": res.dob,
        "gender": res.gender,
        "confidence_score": res.confidence_score,
        "status": "AADHAAR_VERIFIED"
    }


@router.post("/gst/verify")
async def handle_verify_gst(req: GSTVerifyRequest):
    """Verifies 15-char GSTIN, State code, Embedded PAN, and Form GST REG-06 certificate."""
    res = await verify_gst_registration(
        gstin=req.gstin,
        declared_company_name=req.company_name,
        certificate_b64=req.certificate_b64
    )
    if not res.is_valid:
        raise HTTPException(status_code=400, detail=res.error_message or "GSTIN verification failed.")

    if req.customer_id:
        async with AsyncSessionLocal() as session:
            repo = BankingRepository(session)
            await repo.update_customer_business_gst(
                customer_id=req.customer_id,
                company_name=req.company_name,
                business_type=req.business_type or "Private Limited Company",
                gstin=res.gstin,
                gst_details=res.details
            )
            await session.commit()

    return {
        "success": True,
        "gstin": res.gstin,
        "state_code": res.state_code,
        "state_name": res.state_name,
        "pan_number": res.pan_number,
        "entity_type": res.entity_type,
        "legal_name": res.legal_name,
        "trade_name": res.trade_name,
        "certificate_verified": res.certificate_verified,
        "confidence_score": res.confidence_score,
        "status": "GST_VERIFIED"
    }


@router.post("/liveness/verify")
async def handle_verify_liveness(req: LivenessVerifyRequest):
    """Executes live video selfie liveness checking and biometric face match using Gemini Vision."""
    res = await verify_live_kyc(
        selfie_b64=req.selfie_b64,
        aadhaar_b64=req.aadhaar_b64,
        ear_metrics=req.ear_metrics
    )
    if not res.is_approved:
        raise HTTPException(status_code=400, detail=res.observations or "Biometric verification failed.")

    if req.customer_id:
        async with AsyncSessionLocal() as session:
            repo = BankingRepository(session)
            await repo.update_customer_biometric_kyc(
                customer_id=req.customer_id,
                selfie_url=f"selfie_cust_{req.customer_id}_verified.jpg",
                face_match_score=res.face_match_score,
                liveness_verified=res.liveness_passed
            )
            await session.commit()

    return {
        "success": True,
        "liveness_passed": res.liveness_passed,
        "face_match_score": res.face_match_score,
        "confidence_verdict": res.confidence_verdict,
        "eyes_open": res.eyes_open,
        "blink_verified": res.blink_verified,
        "observations": res.observations,
        "status": "VIDEO_KYC_VERIFIED"
    }

