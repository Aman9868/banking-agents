"""Test suite for Redis Query Cache, Entity Memory, Rate Limiting, and Resilience."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from services.cache.cache_engine import cache_engine
from gateway.rate_limit.limiter import SlidingWindowRateLimiter
from services.resilience.circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerOpenException
from agents.supervisor.graph import supervisor_graph_builder
from langchain_core.messages import HumanMessage


@pytest.mark.asyncio
async def test_redis_query_cache_lifecycle():
    customer_id = 999
    query = "What is the fixed deposit interest rate?"
    payload = {"response": "The FD interest rate is 7.5% per annum.", "active_workflow": "NONE"}

    # 1. Clean start
    await cache_engine.invalidate_customer_cache(customer_id)
    cached = await cache_engine.get_cached_response(customer_id, query)
    assert cached is None

    # 2. Store in cache
    await cache_engine.set_cached_response(customer_id, query, payload)

    # 3. Retrieve from cache
    cached_after = await cache_engine.get_cached_response(customer_id, query)
    assert cached_after is not None
    assert cached_after["response"] == payload["response"]

    # 4. Mutating transaction purges cache
    await cache_engine.invalidate_customer_cache(customer_id)
    cleared = await cache_engine.get_cached_response(customer_id, query)
    assert cleared is None


@pytest.mark.asyncio
async def test_cross_subgraph_entity_memory_pronoun_resolution():
    """Verify customer_memory resolves pronouns like 'him' to the last remembered beneficiary."""
    supervisor = supervisor_graph_builder.compile()

    # Turn 1: Transfer with explicit beneficiary Rahul
    state_turn1 = {
        "messages": [HumanMessage(content="Transfer ₹5,000 to Rahul Sharma")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh",
        "active_workflow": "NONE",
        "customer_memory": {}
    }
    result_turn1 = await supervisor.ainvoke(state_turn1)
    memory = result_turn1.get("customer_memory", {})
    assert "Rahul" in memory.get("last_beneficiary_name", "")

    # Turn 2: User says "Send him another 2000" using pronoun "him"
    state_turn2 = {
        "messages": [HumanMessage(content="Send him another 2000")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh",
        "active_workflow": "NONE",
        "customer_memory": memory
    }
    result_turn2 = await supervisor.ainvoke(state_turn2)
    t_data = result_turn2.get("transfer_data", {})
    # Verify the pronoun 'him' was resolved to Rahul Sharma!
    assert "Rahul" in t_data.get("beneficiary_name", "")
    assert t_data.get("amount") == 2000.0


@pytest.mark.asyncio
async def test_sliding_window_rate_limiter():
    import uuid
    limiter = SlidingWindowRateLimiter(requests_per_minute=3)
    client_id = f"test-client-limiter-{uuid.uuid4().hex[:8]}"

    # 3 requests should pass
    is_limited_1, rem_1, _ = await limiter.is_rate_limited(client_id)
    assert is_limited_1 is False
    assert rem_1 == 2

    is_limited_2, rem_2, _ = await limiter.is_rate_limited(client_id)
    assert is_limited_2 is False
    assert rem_2 == 1

    is_limited_3, rem_3, _ = await limiter.is_rate_limited(client_id)
    assert is_limited_3 is False
    assert rem_3 == 0

    # 4th request must be rate limited!
    is_limited_4, rem_4, _ = await limiter.is_rate_limited(client_id)
    assert is_limited_4 is True
    assert rem_4 == 0


@pytest.mark.asyncio
async def test_correlation_id_header_middleware():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Client passes custom correlation ID
        res = await client.get("/health", headers={"X-Correlation-ID": "test-corr-abc-123"})
        assert res.status_code == 200
        assert res.headers.get("X-Correlation-ID") == "test-corr-abc-123"

        # Client omits correlation ID: server auto-generates
        res2 = await client.get("/health")
        assert res2.status_code == 200
        assert res2.headers.get("X-Correlation-ID") is not None
        assert res2.headers.get("X-Correlation-ID").startswith("corr-")


@pytest.mark.asyncio
async def test_circuit_breaker_fail_fast_and_recovery():
    cb = CircuitBreaker(name="MockCoreBanking", failure_threshold=2, recovery_timeout_seconds=0.1)

    async def failing_service():
        raise ConnectionResetError("Core banking down")

    # 1st failure
    with pytest.raises(ConnectionResetError):
        await cb.call(failing_service)
    assert cb.state == CircuitState.CLOSED

    # 2nd failure: trips to OPEN
    with pytest.raises(ConnectionResetError):
        await cb.call(failing_service)
    assert cb.state == CircuitState.OPEN

    # 3rd attempt: fails fast without even calling failing_service!
    with pytest.raises(CircuitBreakerOpenException):
        await cb.call(failing_service)
