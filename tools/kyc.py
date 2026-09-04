"""KYC and Identity Verification Tools for NovaBank Agent."""

from typing import Optional, Dict, Any
from database.repositories.banking_repo import BankingRepository
from tools.base import ToolResult
from services.kyc_aml.aadhaar_verifier import verify_aadhaar_document as svc_verify_aadhaar
from services.kyc_aml.gst_verifier import verify_gst_registration as svc_verify_gst
from services.kyc_aml.liveness_verifier import verify_live_kyc as svc_verify_live


async def verify_aadhaar(
    repo: BankingRepository,
    customer_id: int,
    aadhaar_number: str,
    declared_name: str = "",
    image_b64: Optional[str] = None
) -> ToolResult:
    """Verifies customer's Aadhaar card format, Verhoeff checksum, and OCR extraction."""
    res = await svc_verify_aadhaar(
        aadhaar_number=aadhaar_number,
        declared_name=declared_name,
        image_b64=image_b64
    )

    if not res.is_valid:
        return ToolResult(
            success=False,
            error=res.error_message or "Aadhaar verification failed."
        )

    # Persist verified Aadhaar to database
    await repo.update_customer_aadhaar_kyc(
        customer_id=customer_id,
        aadhaar_masked=res.aadhaar_masked,
        aadhaar_data=res.details
    )

    return ToolResult(
        success=True,
        data={
            "aadhaar_masked": res.aadhaar_masked,
            "full_name_matched": res.full_name_matched,
            "dob": res.dob,
            "gender": res.gender,
            "face_photo_present": res.face_photo_present,
            "confidence_score": res.confidence_score,
            "status": "AADHAAR_VERIFIED"
        }
    )


async def verify_live_face_kyc(
    repo: BankingRepository,
    customer_id: int,
    selfie_b64: str,
    aadhaar_b64: Optional[str] = None,
    ear_metrics: Optional[Dict[str, Any]] = None
) -> ToolResult:
    """Verifies live video selfie face & eye liveness and runs biometric comparison with Aadhaar."""
    res = await svc_verify_live(
        selfie_b64=selfie_b64,
        aadhaar_b64=aadhaar_b64,
        ear_metrics=ear_metrics
    )

    if not res.is_approved:
        return ToolResult(
            success=False,
            error=res.observations or "Biometric face verification did not meet confidence threshold.",
            data={
                "liveness_passed": res.liveness_passed,
                "face_match_score": res.face_match_score,
                "confidence_verdict": res.confidence_verdict
            }
        )

    # Update customer record in DB
    selfie_ref = f"selfie_cust_{customer_id}_{res.confidence_verdict.lower()}"
    await repo.update_customer_biometric_kyc(
        customer_id=customer_id,
        selfie_url=selfie_ref,
        face_match_score=res.face_match_score,
        liveness_verified=res.liveness_passed
    )

    return ToolResult(
        success=True,
        data={
            "status": "VIDEO_KYC_VERIFIED",
            "liveness_passed": res.liveness_passed,
            "face_match_score": res.face_match_score,
            "eyes_open": res.eyes_open,
            "blink_verified": res.blink_verified,
            "observations": res.observations
        }
    )


async def verify_gst(
    repo: BankingRepository,
    customer_id: int,
    gstin: str,
    company_name: str,
    business_type: str = "Private Limited",
    certificate_b64: Optional[str] = None
) -> ToolResult:
    """Verifies GSTIN number, State code, Embedded PAN, and Form GST REG-06 certificate."""
    res = await svc_verify_gst(
        gstin=gstin,
        declared_company_name=company_name,
        certificate_b64=certificate_b64
    )

    if not res.is_valid:
        return ToolResult(
            success=False,
            error=res.error_message or "GSTIN verification failed."
        )

    # Update customer record in DB
    await repo.update_customer_business_gst(
        customer_id=customer_id,
        company_name=company_name,
        business_type=business_type,
        gstin=res.gstin,
        gst_details=res.details
    )

    return ToolResult(
        success=True,
        data={
            "status": "GST_VERIFIED",
            "gstin": res.gstin,
            "state_code": res.state_code,
            "state_name": res.state_name,
            "pan_number": res.pan_number,
            "entity_type": res.entity_type,
            "legal_name": res.legal_name,
            "trade_name": res.trade_name,
            "certificate_verified": res.certificate_verified,
            "confidence_score": res.confidence_score
        }
    )

