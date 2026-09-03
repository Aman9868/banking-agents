"""Pydantic schemas for Chat and Admin HITL API."""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, description="Customer message")
    thread_id: Optional[str] = Field(None, description="Conversation session / thread ID for stateful checkpointing")
    customer_external_id: Optional[str] = Field("CUST-1001", description="External customer reference ID")


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    active_workflow: str
    requires_action: Optional[str] = None  # None, "CONFIRMATION_REQUIRED", "HITL_PENDING", "SLOT_FILLING"
    action_payload: Optional[Dict[str, Any]] = None
    widget_type: Optional[str] = None  # "EMI_SLIDER", "TRANSACTION_RECEIPT", "SPENDING_CHART", "SUBSCRIPTION_LIST"
    widget_data: Optional[Dict[str, Any]] = None


class HITLReviewActionRequest(BaseModel):
    approved: bool = Field(..., description="Whether the bank officer approves or rejects the task")
    reviewer_id: str = Field(..., description="Officer employee ID")
    notes: Optional[str] = Field(None, description="Compliance reviewer notes")


class HITLReviewResponse(BaseModel):
    task_ref: str
    status: str
    message: str


class ChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    active_workflow: str
    requires_action: Optional[str] = None
    action_payload: Optional[Dict[str, Any]] = None
    widget_type: Optional[str] = None
    widget_data: Optional[Dict[str, Any]] = None
    created_at: str


class ChatSessionResponse(BaseModel):
    thread_id: str
    title: str
    created_at: str
    updated_at: str


class SessionListResponse(BaseModel):
    sessions: List[ChatSessionResponse]


class SessionDetailResponse(BaseModel):
    thread_id: str
    title: str
    messages: List[ChatMessageResponse]


