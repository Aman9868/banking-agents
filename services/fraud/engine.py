"""Deterministic Fraud Detection & Risk Scoring Engine."""

from typing import List, Dict, Any
from pydantic import BaseModel


class FraudAssessment(BaseModel):
    score: float  # 0.0 to 1.0
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    reason_codes: List[str]


class FraudEngine:
    """Pure deterministic fraud evaluation based on financial velocity, amounts, and beneficiary parameters."""

    def evaluate_transfer(
        self,
        amount: float,
        beneficiary_is_new: bool = False,
        recent_transfer_count_1h: int = 0,
        unusual_device: bool = False
    ) -> FraudAssessment:
        score = 0.05  # Base baseline
        reasons: List[str] = []

        # 1. Amount thresholds
        if amount > 100000:
            score += 0.40
            reasons.append("HIGH_VALUE_TRANSACTION_OVER_100K")
        elif amount > 50000:
            score += 0.20
            reasons.append("ELEVATED_VALUE_TRANSACTION_OVER_50K")

        # 2. Beneficiary cooling period
        if beneficiary_is_new:
            score += 0.35
            reasons.append("BENEFICIARY_RECENTLY_ADDED_COOLING_PERIOD")

        # 3. Velocity check
        if recent_transfer_count_1h >= 3:
            score += 0.30
            reasons.append("HIGH_TRANSACTION_VELOCITY_PAST_HOUR")

        # 4. Device anomaly
        if unusual_device:
            score += 0.25
            reasons.append("UNRECOGNIZED_DEVICE_FINGERPRINT")

        score = min(score, 1.0)

        # Risk level determination
        if score >= 0.80:
            level = "CRITICAL"
        elif score >= 0.60:
            level = "HIGH"
        elif score >= 0.30:
            level = "MEDIUM"
        else:
            level = "LOW"

        return FraudAssessment(
            score=round(score, 2),
            risk_level=level,
            reason_codes=reasons
        )


fraud_engine = FraudEngine()

