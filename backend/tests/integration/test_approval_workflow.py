import pytest
from fastapi.testclient import TestClient
from httpx import HTTPStatusError, Request, Response
from unittest.mock import patch, AsyncMock
from backend.config import settings
from backend.main import app

client = TestClient(app)
VALID_API_KEY = settings.API_KEY
HEADERS = {"X-API-Key": VALID_API_KEY}

@pytest.fixture(autouse=True)
def mock_settings(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")

def test_repair_endpoint_unauthorized():
    response = client.post("/api/pr/123/repair", json={"edited_summary": "new"})
    assert response.status_code == 401

@patch("backend.database.execute_query", new_callable=AsyncMock)
def test_repair_endpoint_success(mock_execute):
    mock_execute.return_value = 1
    response = client.post(
        "/api/pr/123/repair?repo=test/repo", 
        json={"edited_summary": "This is repaired"},
        headers=HEADERS
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Summary updated."
    args = mock_execute.call_args[0][1]
    assert args[0] == "This is repaired"
    assert args[1] is False

@patch("backend.routers.api.fetch_one", new_callable=AsyncMock)
@patch("backend.services.ai_engine.AIEngine.compare_summaries", new_callable=AsyncMock)
def test_compare_summaries_endpoint(mock_compare, mock_fetch):
    mock_fetch.return_value = {
        "original_summary": "Original",
        "summary": "Edited"
    }
    mock_compare.return_value = {"differences_detected": True, "recommendation": "Keep edit"}
    
    response = client.get("/api/pr/123/compare?repo=test/repo", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["differences_detected"] is True

@patch("backend.database.execute_query", new_callable=AsyncMock)
@patch("backend.routers.api.generate_and_push_changelog", new_callable=AsyncMock)
def test_approve_triggers_changelog(mock_push, mock_execute):
    mock_execute.return_value = 1
    mock_push.return_value = {"version": "v1.0.1"}
    
    response = client.post("/api/pr/123/approve?repo=test/repo", headers=HEADERS)
    assert response.status_code == 200
    assert "changelog pushed" in response.json()["message"]
    mock_push.assert_called_once_with(123, "test/repo")

@pytest.mark.asyncio
async def test_failover_routing():
    from backend.services.routing_service import MultiProviderRouter
    router = MultiProviderRouter()
    
    provider1_mock = AsyncMock()
    provider1_mock.chat.completions.create.side_effect = Exception("429 Too Many Requests")
    
    provider2_mock = AsyncMock()
    class MockMsg:
        content = '{"status": "fallback_success"}'
    class MockChoice:
        message = MockMsg()
    class MockResponse:
        choices = [MockChoice()]
        
    provider2_mock.chat.completions.create.return_value = MockResponse()
    
    router.providers = [
        {"name": "fail_api", "client": provider1_mock, "model": "fail_model"},
        {"name": "fallback_api", "client": provider2_mock, "model": "good_model"}
    ]
    
    res = await router.chat_completion(messages=[])
    assert res == '{"status": "fallback_success"}'
    assert provider1_mock.chat.completions.create.call_count == 1
    assert provider2_mock.chat.completions.create.call_count == 1
