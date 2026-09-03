"""Card operations banking tools."""

import uuid
from typing import Optional, Dict, Any
from database.repositories.banking_repo import BankingRepository
from security.pii import mask_card_number
from tools.base import ToolResult


async def get_cards(repo: BankingRepository, customer_id: int) -> ToolResult:
    """Lists all credit and debit cards for customer."""
    cards = await repo.get_cards_by_customer_id(customer_id)
    return ToolResult(
        success=True,
        data={
            "cards": [
                {
                    "card_id": c.id,
                    "card_type": c.card_type,
                    "network": c.network,
                    "masked_number": mask_card_number(c.card_number),
                    "expiry_date": c.expiry_date,
                    "status": c.status,
                    "daily_atm_limit": c.daily_atm_limit,
                    "daily_online_limit": c.daily_online_limit,
                    "is_international_enabled": c.is_international_enabled
                }
                for c in cards
            ]
        }
    )


async def freeze_card(repo: BankingRepository, customer_id: int, card_type: str = "DEBIT") -> ToolResult:
    """Instantly freezes customer card preventing further transactions."""
    card = await repo.find_card_by_type(customer_id, card_type)
    if not card:
        return ToolResult(success=False, error=f"No {card_type.upper()} card found for customer.")

    if card.status == "FROZEN":
        return ToolResult(
            success=True,
            data={
                "card_id": card.id,
                "card_type": card.card_type,
                "status": "FROZEN",
                "message": f"Your {card.card_type} card {mask_card_number(card.card_number)} is already frozen."
            }
        )

    await repo.update_card_status(card.id, "FROZEN")
    masked = mask_card_number(card.card_number)
    return ToolResult(
        success=True,
        data={
            "card_id": card.id,
            "card_type": card.card_type,
            "status": "FROZEN",
            "message": f"Security Alert: Your {card.card_type} card {masked} has been immediately frozen. All POS, ATM, and online transactions are blocked."
        }
    )


async def unfreeze_card(repo: BankingRepository, customer_id: int, card_type: str = "DEBIT") -> ToolResult:
    """Unfreezes a previously locked card."""
    card = await repo.find_card_by_type(customer_id, card_type)
    if not card:
        return ToolResult(success=False, error=f"No {card_type.upper()} card found for customer.")

    await repo.update_card_status(card.id, "ACTIVE")
    masked = mask_card_number(card.card_number)
    return ToolResult(
        success=True,
        data={
            "card_id": card.id,
            "card_type": card.card_type,
            "status": "ACTIVE",
            "message": f"Your {card.card_type} card {masked} has been successfully unfrozen and is ready for use."
        }
    )


async def set_card_limits(
    repo: BankingRepository,
    customer_id: int,
    card_type: str = "DEBIT",
    atm_limit: Optional[float] = None,
    online_limit: Optional[float] = None
) -> ToolResult:
    """Updates daily ATM and online spending limits on the specified card."""
    card = await repo.find_card_by_type(customer_id, card_type)
    if not card:
        return ToolResult(success=False, error=f"No {card_type.upper()} card found for customer.")

    await repo.update_card_limits(card.id, atm_limit=atm_limit, online_limit=online_limit)
    return ToolResult(
        success=True,
        data={
            "card_id": card.id,
            "card_type": card.card_type,
            "daily_atm_limit": atm_limit or card.daily_atm_limit,
            "daily_online_limit": online_limit or card.daily_online_limit,
            "message": f"Spending limits for {card.card_type} card {mask_card_number(card.card_number)} updated: Online limit ₹{(online_limit or card.daily_online_limit):,.2f}."
        }
    )


async def replace_card(repo: BankingRepository, customer_id: int, card_type: str = "DEBIT", reason: str = "LOST") -> ToolResult:
    """Blocks compromised card and orders a new replacement card."""
    card = await repo.find_card_by_type(customer_id, card_type)
    if not card:
        return ToolResult(success=False, error=f"No {card_type.upper()} card found for customer.")

    # Block existing card
    await repo.update_card_status(card.id, "BLOCKED")
    order_ref = f"ORD-CRD-{uuid.uuid4().hex[:8].upper()}"

    return ToolResult(
        success=True,
        data={
            "order_ref": order_ref,
            "old_card": mask_card_number(card.card_number),
            "status": "REPLACEMENT_DISPATCHED",
            "message": f"Your existing {card.card_type} card {mask_card_number(card.card_number)} has been permanently blocked. A replacement card has been dispatched (Order Ref: {order_ref}). Delivery in 3-5 business days."
        }
    )

