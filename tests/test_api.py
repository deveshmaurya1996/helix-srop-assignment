import pytest


@pytest.mark.asyncio
async def test_create_session(client):
    resp = await client.post("/v1/sessions", json={"user_id": "u_test_001"})
    assert resp.status_code == 200
    assert "session_id" in resp.json()


@pytest.mark.asyncio
async def test_knowledge_query_routes_correctly(client, mock_adk):
    sess = await client.post("/v1/sessions", json={"user_id": "u_test_002", "plan_tier": "pro"})
    session_id = sess.json()["session_id"]

    q = {"content": "How do I rotate a deploy key?"}
    r1 = await client.post(f"/v1/chat/{session_id}", json=q)
    assert r1.status_code == 200
    assert r1.json()["routed_to"] == "knowledge"
    trace_id = r1.json()["trace_id"]

    trace = await client.get(f"/v1/traces/{trace_id}")
    assert trace.status_code == 200
    assert len(trace.json()["retrieved_chunk_ids"]) > 0

    r2 = await client.post(f"/v1/chat/{session_id}", json={"content": "What is my plan tier?"})
    assert r2.status_code == 200
    assert "pro" in r2.json()["reply"].lower()


@pytest.mark.asyncio
async def test_session_not_found_returns_404(client):
    resp = await client.post("/v1/chat/nonexistent-id", json={"content": "hello"})
    assert resp.status_code == 404
