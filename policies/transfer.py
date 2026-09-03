"""Deterministic Transfer Policy Engine."""

from enum import Enum
from typing import Optional, List
from pydantic import BaseModel
from apps.api.config import settings
from services.fraud.engine import FraudAssessment


class PolicyDecision(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_USER_CONFIRMATION = "REQUIRE_USER_CONFIRMATION"
    REQUIRE_STEP_UP_AUTH = "REQUIRE_STEP_UP_AUTH"
    REQUIRE_HITL_REVIEW = "REQUIRE_HITL_REVIEW"
    DENY = "DENY"


class PolicyEvaluationResult(BaseModel):
    decision: PolicyDecision
    reason: str
    requires_human_approval: bool = False
    requires_step_up: bool = False


class TransferPolicyEngine:
    def evaluate(
        self,
        amount: float,
        account_status: str,
        fraud_assessment: FraudAssessment,
        user_confirmed: bool = False,
        step_up_completed: bool = False
    ) -> PolicyEvaluationResult:
        # Rule 1: Inactive / Frozen Account Check
        if account_status != "ACTIVE":
            return PolicyEvaluationResult(
                decision=PolicyDecision.DENY,
                reason=f"Source account is {account_status}. Outbound transfers are prohibited."
            )

        # Rule 2: Excessive Fraud / Risk Score Check -> Trigger HITL
        if fraud_assessment.score >= settings.FRAUD_RISK_HITL_THRESHOLD:
            return PolicyEvaluationResult(
                decision=PolicyDecision.REQUIRE_HITL_REVIEW,
                reason=f"High risk score ({fraud_assessment.score:.2f}) triggered compliance review: {', '.join(fraud_assessment.reason_codes)}",
                requires_human_approval=True
            )

        # Rule 3: High value step-up auth requirement
        if amount >= settings.TRANSFER_STEP_UP_LIMIT and not step_up_completed:
            return PolicyEvaluationResult(
                decision=PolicyDecision.REQUIRE_STEP_UP_AUTH,
                reason=f"Amount exceeds threshold of ₹{settings.TRANSFER_STEP_UP_LIMIT:,.2f}. Step-up verification required.",
                requires_step_up=True
            )

        # Rule 4: Explicit User Confirmation required
        if not user_confirmed:
            return PolicyEvaluationResult(
                decision=PolicyDecision.REQUIRE_USER_CONFIRMATION,
                reason="User confirmation required before initiating transfer."
            )

        # All rules passed
        return PolicyEvaluationResult(
            decision=PolicyDecision.ALLOW,
            reason="All deterministic transfer security policies passed."
        )


transfer_policy_engine = TransferPolicyEngine()

