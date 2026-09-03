"""Unit tests for Deterministic Transfer Policy Engine and Fraud Engine."""

import pytest
from services.fraud.engine import FraudEngine, FraudAssessment
from policies.transfer import TransferPolicyEngine, PolicyDecision


def test_fraud_engine_low_risk():
    engine = FraudEngine()
    assessment = engine.evaluate_transfer(
        amount=5000.0,
        beneficiary_is_new=False,
        recent_transfer_count_1h=0
    )
    assert assessment.score <= 0.20
    assert assessment.risk_level == "LOW"
    assert len(assessment.reason_codes) == 0


def test_fraud_engine_high_risk_signals():
    engine = FraudEngine()
    assessment = engine.evaluate_transfer(
        amount=150000.0,
        beneficiary_is_new=True,
        recent_transfer_count_1h=4,
        unusual_device=True
    )
    assert assessment.score >= 0.80
    assert assessment.risk_level == "CRITICAL"
    assert "HIGH_VALUE_TRANSACTION_OVER_100K" in assessment.reason_codes
    assert "BENEFICIARY_RECENTLY_ADDED_COOLING_PERIOD" in assessment.reason_codes


def test_policy_inactive_account_denied():
    policy = TransferPolicyEngine()
    assessment = FraudAssessment(score=0.1, risk_level="LOW", reason_codes=[])
    result = policy.evaluate(
        amount=5000.0,
        account_status="FROZEN",
        fraud_assessment=assessment,
        user_confirmed=True
    )
    assert result.decision == PolicyDecision.DENY
    assert "FROZEN" in result.reason


def test_policy_high_fraud_triggers_hitl():
    policy = TransferPolicyEngine()
    assessment = FraudAssessment(score=0.88, risk_level="CRITICAL", reason_codes=["HIGH_VALUE"])
    result = policy.evaluate(
        amount=200000.0,
        account_status="ACTIVE",
        fraud_assessment=assessment,
        user_confirmed=True
    )
    assert result.decision == PolicyDecision.REQUIRE_HITL_REVIEW
    assert result.requires_human_approval is True


def test_policy_requires_user_confirmation():
    policy = TransferPolicyEngine()
    assessment = FraudAssessment(score=0.1, risk_level="LOW", reason_codes=[])
    result = policy.evaluate(
        amount=5000.0,
        account_status="ACTIVE",
        fraud_assessment=assessment,
        user_confirmed=False
    )
    assert result.decision == PolicyDecision.REQUIRE_USER_CONFIRMATION


def test_policy_allow_when_all_rules_pass():
    policy = TransferPolicyEngine()
    assessment = FraudAssessment(score=0.15, risk_level="LOW", reason_codes=[])
    result = policy.evaluate(
        amount=5000.0,
        account_status="ACTIVE",
        fraud_assessment=assessment,
        user_confirmed=True
    )
    assert result.decision == PolicyDecision.ALLOW

