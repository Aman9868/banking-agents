"""Admin & Bank Officer HITL (Human-in-the-Loop) Review API."""

from datetime import datetime
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from langgraph.types import Command
from apps.api.schemas.chat import HITLReviewActionRequest, HITLReviewResponse
from database.connection import AsyncSessionLocal
from database.models.banking import HumanReviewTask
from apps.api.routes.chat import get_banking_app
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["Admin HITL"])


@router.get("/reviews")
async def list_pending_reviews():
    """Lists all pending compliance and risk review tasks."""
    async with AsyncSessionLocal() as session:
        query = (
            select(HumanReviewTask)
            .where(HumanReviewTask.status == "PENDING")
            .order_by(HumanReviewTask.created_at.desc())
        )
        res = await session.execute(query)
        tasks = res.scalars().all()

        return [
            {
                "task_ref": t.task_ref,
                "thread_id": t.thread_id,
                "customer_id": t.customer_id,
                "workflow_type": t.workflow_type,
                "risk_score": t.risk_score,
                "reason": t.reason,
                "payload": t.payload,
                "status": t.status,
                "created_at": t.created_at.isoformat()
            }
            for t in tasks
        ]


@router.post("/reviews/{task_ref}/action", response_model=HITLReviewResponse)
async def act_on_review(task_ref: str, action: HITLReviewActionRequest):
    """
    Approves or rejects a paused task and resumes the LangGraph execution
    checkpoint via Command(resume=...).
    """
    async with AsyncSessionLocal() as session:
        query = select(HumanReviewTask).where(HumanReviewTask.task_ref == task_ref)
        res = await session.execute(query)
        task = res.scalar_one_or_none()

        if not task:
            raise HTTPException(status_code=404, detail=f"Review task '{task_ref}' not found")

        if task.status != "PENDING":
            raise HTTPException(status_code=400, detail=f"Task '{task_ref}' is already {task.status}")

        new_status = "APPROVED" if action.approved else "REJECTED"
        task.status = new_status
        task.reviewer_id = action.reviewer_id
        task.reviewer_notes = action.notes
        task.resolved_at = datetime.utcnow()
        await session.commit()

        thread_id = task.thread_id

    # Resume the paused LangGraph execution
    app = await get_banking_app()
    config = {"configurable": {"thread_id": thread_id}}

    try:
        resume_payload = {"approved": action.approved, "notes": action.notes}
        await app.ainvoke(Command(resume=resume_payload), config=config)
        logger.info("Resumed LangGraph checkpoint successfully", task_ref=task_ref, approved=action.approved)
    except Exception as exc:
        logger.error("Error resuming LangGraph checkpoint", error=str(exc))

    return HITLReviewResponse(
        task_ref=task_ref,
        status=new_status,
        message=f"Task {task_ref} has been {new_status.lower()} and workflow resumed."
    )

