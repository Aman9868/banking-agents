"""Unit and API integration tests for ChatGPT-style session management and history."""

import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from database.init_db import init_database, seed_mock_data


@pytest.fixture(scope="module", autouse=True)
async def setup_db():
    await init_database()
    await seed_mock_data()


@pytest.mark.asyncio
async def test_serve_chat_ui():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text
        assert "NovaBank" in resp.text


@pytest.mark.asyncio
async def test_session_lifecycle_and_history():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        thread_id = f"TEST-SESSION-HIST-{uuid.uuid4().hex[:8]}"

        # 1. Send first message
        chat_res1 = await client.post(
            "/api/v1/chat",
            json={
                "message": "What is my current balance?",
                "thread_id": thread_id,
                "customer_external_id": "CUST-1001"
            }
        )
        assert chat_res1.status_code == 200
        data1 = chat_res1.json()
        assert "Savings account" in data1["response"]

        # 2. List sessions - should contain thread_id
        sess_res = await client.get("/api/v1/chat/sessions?customer_external_id=CUST-1001")
        assert sess_res.status_code == 200
        sessions = sess_res.json()["sessions"]
        found_session = next((s for s in sessions if s["thread_id"] == thread_id), None)
        assert found_session is not None
        assert "What is my current balance" in found_session["title"]

        # 3. Send follow-up turn in same thread
        chat_res2 = await client.post(
            "/api/v1/chat",
            json={
                "message": "Thank you for the balance update",
                "thread_id": thread_id,
                "customer_external_id": "CUST-1001"
            }
        )
        assert chat_res2.status_code == 200

        # 4. Fetch session detail - should have 4 messages (2 user, 2 assistant)
        detail_res = await client.get(f"/api/v1/chat/sessions/{thread_id}?customer_external_id=CUST-1001")
        assert detail_res.status_code == 200
        messages = detail_res.json()["messages"]
        assert len(messages) == 4
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "What is my current balance?"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["role"] == "user"
        assert messages[3]["role"] == "assistant"

        # 5. Delete session
        del_res = await client.delete(f"/api/v1/chat/sessions/{thread_id}?customer_external_id=CUST-1001")
        assert del_res.status_code == 200
        assert del_res.json()["status"] == "deleted"

        # 6. Verify detail is now 404
        detail_after_del = await client.get(f"/api/v1/chat/sessions/{thread_id}?customer_external_id=CUST-1001")
        assert detail_after_del.status_code == 404

