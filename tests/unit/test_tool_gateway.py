"""Unit tests for Tool Gateway RBAC and Idempotency manager."""

import pytest
from gateway.tool_gateway.permissions import authorize_tool_execution, ToolPermissionDeniedError, AgentRole
from gateway.tool_gateway.idempotency import IdempotencyManager


def test_agent_rbac_permitted_actions():
    assert authorize_tool_execution(AgentRole.TRANSFER_AGENT.value, "initiate_transfer") is True
    assert authorize_tool_execution(AgentRole.TRANSFER_AGENT.value, "get_balance") is True
    assert authorize_tool_execution(AgentRole.SUPPORT_AGENT.value, "get_transaction") is True
    assert authorize_tool_execution(AgentRole.SUPERVISOR.value, "get_balance") is True


def test_agent_rbac_denies_unauthorized_action():
    # Support agent must NEVER be allowed to initiate a transfer
    with pytest.raises(ToolPermissionDeniedError) as exc_info:
        authorize_tool_execution(AgentRole.SUPPORT_AGENT.value, "initiate_transfer")
    assert "not authorized" in str(exc_info.value)

    # Card agent must not be allowed to initiate transfer
    with pytest.raises(ToolPermissionDeniedError):
        authorize_tool_execution(AgentRole.CARD_AGENT.value, "initiate_transfer")


import uuid


@pytest.mark.asyncio
async def test_idempotency_manager_lock_and_replay():
    mgr = IdempotencyManager()
    key = f"TEST-IDEMP-{uuid.uuid4().hex}"

    # 1. First acquisition succeeds
    acquired = await mgr.acquire_lock(key)
    assert acquired is True

    # 2. Duplicate concurrent acquisition fails
    acquired_dup = await mgr.acquire_lock(key)
    assert acquired_dup is False

    # 3. Store terminal result
    mock_res = {"tx_ref": "TXN-999", "amount": 1000}
    await mgr.set_result(key, mock_res)

    # 4. Retrieval returns completed result
    cached = await mgr.get_result(key)
    assert cached is not None
    assert cached["status"] == "COMPLETED"
    assert cached["result"]["tx_ref"] == "TXN-999"
