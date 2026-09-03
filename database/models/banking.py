"""Enterprise Banking Domain Models."""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Boolean,
    Text,
    JSON,
    Index
)
from sqlalchemy.orm import relationship
from database.connection import Base


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(64), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    phone = Column(String(32), nullable=True)
    date_of_birth = Column(String(32), nullable=True)
    kyc_status = Column(String(32), default="PENDING", nullable=False)  # PENDING, VERIFIED, REJECTED
    risk_tier = Column(String(32), default="LOW", nullable=False)       # LOW, MEDIUM, HIGH
    created_at = Column(DateTime, default=utc_now, nullable=False)

    accounts = relationship("Account", back_populates="customer", cascade="all, delete-orphan")
    beneficiaries = relationship("Beneficiary", back_populates="customer", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="customer")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    account_number = Column(String(32), unique=True, index=True, nullable=False)
    account_type = Column(String(32), default="SAVINGS", nullable=False)  # SAVINGS, CURRENT
    balance = Column(Float, default=0.0, nullable=False)
    currency = Column(String(8), default="INR", nullable=False)
    status = Column(String(32), default="ACTIVE", nullable=False)        # ACTIVE, FROZEN, CLOSED
    created_at = Column(DateTime, default=utc_now, nullable=False)

    customer = relationship("Customer", back_populates="accounts")
    transactions = relationship("Transaction", back_populates="source_account")


class Beneficiary(Base):
    __tablename__ = "beneficiaries"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    account_number = Column(String(32), nullable=False)
    ifsc_code = Column(String(16), default="BANK0001234", nullable=False)
    status = Column(String(32), default="ACTIVE", nullable=False)        # ACTIVE, PENDING_VERIFICATION
    created_at = Column(DateTime, default=utc_now, nullable=False)

    customer = relationship("Customer", back_populates="beneficiaries")
    transactions = relationship("Transaction", back_populates="beneficiary")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_ref = Column(String(64), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    source_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    beneficiary_id = Column(Integer, ForeignKey("beneficiaries.id"), nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(8), default="INR", nullable=False)
    status = Column(String(32), default="PENDING", nullable=False)      # PENDING, COMPLETED, DECLINED, REVIEW_REQUIRED
    failure_reason = Column(String(255), nullable=True)
    fraud_score = Column(Float, default=0.0, nullable=False)
    idempotency_key = Column(String(128), unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    customer = relationship("Customer", back_populates="transactions")
    source_account = relationship("Account", back_populates="transactions")
    beneficiary = relationship("Beneficiary", back_populates="transactions")


class HumanReviewTask(Base):
    __tablename__ = "human_review_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_ref = Column(String(64), unique=True, index=True, nullable=False)
    thread_id = Column(String(128), index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    workflow_type = Column(String(64), nullable=False)                   # ACCOUNT_KYC, TRANSFER_FRAUD
    risk_score = Column(Float, default=0.0, nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(32), default="PENDING", nullable=False)       # PENDING, APPROVED, REJECTED
    reviewer_id = Column(String(64), nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    resolved_at = Column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(64), index=True, nullable=False)
    agent_id = Column(String(64), index=True, nullable=False)
    customer_id = Column(Integer, nullable=True)
    thread_id = Column(String(128), nullable=True)
    payload = Column(JSON, nullable=False)
    timestamp = Column(DateTime, default=utc_now, nullable=False)


class Card(Base):
    __tablename__ = "cards"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    card_number = Column(String(32), unique=True, index=True, nullable=False)
    card_type = Column(String(32), default="DEBIT", nullable=False)      # DEBIT, CREDIT
    network = Column(String(32), default="VISA", nullable=False)         # VISA, MASTERCARD, RUPAY
    expiry_date = Column(String(16), default="12/28", nullable=False)
    status = Column(String(32), default="ACTIVE", nullable=False)        # ACTIVE, FROZEN, BLOCKED, EXPIRED
    daily_atm_limit = Column(Float, default=50000.0, nullable=False)
    daily_online_limit = Column(Float, default=75000.0, nullable=False)
    is_international_enabled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class LoanApplication(Base):
    __tablename__ = "loan_applications"

    id = Column(Integer, primary_key=True, index=True)
    application_ref = Column(String(64), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    loan_type = Column(String(32), default="PERSONAL", nullable=False)   # PERSONAL, HOME, AUTO
    amount = Column(Float, nullable=False)
    tenure_months = Column(Integer, nullable=False)
    interest_rate = Column(Float, default=10.5, nullable=False)
    monthly_emi = Column(Float, nullable=False)
    status = Column(String(32), default="IN_REVIEW", nullable=False)     # APPLIED, IN_REVIEW, APPROVED, REJECTED
    annual_income = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class Biller(Base):
    __tablename__ = "billers"

    id = Column(Integer, primary_key=True, index=True)
    biller_code = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(String(64), nullable=False)                        # ELECTRICITY, BROADBAND, WATER, MOBILE, CREDIT_CARD
    min_amount = Column(Float, default=100.0, nullable=False)


class BillPayment(Base):
    __tablename__ = "bill_payments"

    id = Column(Integer, primary_key=True, index=True)
    payment_ref = Column(String(64), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    biller_id = Column(Integer, ForeignKey("billers.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    consumer_number = Column(String(64), nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String(32), default="COMPLETED", nullable=False)     # COMPLETED, FAILED, PENDING
    idempotency_key = Column(String(128), unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True, index=True)
    ticket_ref = Column(String(64), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    subject = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    priority = Column(String(32), default="MEDIUM", nullable=False)      # LOW, MEDIUM, HIGH, URGENT
    status = Column(String(32), default="OPEN", nullable=False)          # OPEN, IN_PROGRESS, RESOLVED
    created_at = Column(DateTime, default=utc_now, nullable=False)


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"

    id = Column(Integer, primary_key=True, index=True)
    doc_id = Column(String(64), unique=True, index=True, nullable=False)
    title = Column(String(255), nullable=False)
    category = Column(String(64), nullable=False)
    content = Column(Text, nullable=False)
    keywords = Column(String(255), nullable=True)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String(128), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), default="New Conversation", nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String(128), index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(32), nullable=False)                            # "user", "assistant", "system"
    content = Column(Text, nullable=False)
    active_workflow = Column(String(64), default="NONE", nullable=False)
    requires_action = Column(String(64), nullable=True)
    action_payload = Column(JSON, nullable=True)
    widget_type = Column(String(64), nullable=True)
    widget_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


