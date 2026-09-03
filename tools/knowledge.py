"""Knowledge base RAG search and customer support escalation tools."""

import uuid
from typing import Optional, Dict, Any
from database.repositories.banking_repo import BankingRepository
from tools.base import ToolResult


async def search_knowledge_base_tool(repo: BankingRepository, query: str, limit: int = 3) -> ToolResult:
    """Searches official bank policies, interest rates, charges, and FAQ articles."""
    docs = await repo.search_knowledge_docs(query_text=query, limit=limit)
    if not docs:
        return ToolResult(
            success=False,
            error=f"No banking policy documents found matching query '{query}'."
        )

    return ToolResult(
        success=True,
        data={
            "query": query,
            "results": [
                {
                    "doc_id": d.doc_id,
                    "title": d.title,
                    "category": d.category,
                    "content": d.content
                }
                for d in docs
            ]
        }
    )


async def create_support_ticket_tool(
    repo: BankingRepository,
    customer_id: int,
    subject: str,
    description: str,
    priority: str = "MEDIUM"
) -> ToolResult:
    """Creates an escalated human support ticket for banking issues."""
    ticket_ref = f"TCK-{uuid.uuid4().hex[:8].upper()}"
    ticket = await repo.create_support_ticket(
        ticket_ref=ticket_ref,
        customer_id=customer_id,
        subject=subject,
        description=description,
        priority=priority.upper()
    )

    return ToolResult(
        success=True,
        data={
            "ticket_ref": ticket.ticket_ref,
            "subject": ticket.subject,
            "priority": ticket.priority,
            "status": ticket.status,
            "message": f"Support ticket {ticket.ticket_ref} created successfully. Our customer support team will follow up within 2 hours."
        }
    )

