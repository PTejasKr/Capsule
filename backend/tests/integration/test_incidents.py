import pytest
import json
import httpx
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings
from backend.tests.integration.test_webhooks import generate_github_signature

client = TestClient(app)

@pytest.mark.asyncio
async def test_invalid_hmac_signature():
    """
    Simulate a security incident: unauthorized request with bad HMAC.
    """
    payload = {"action": "opened", "number": 123, "repository": {"full_name": "test/repo"}}
    payload_bytes = json.dumps(payload).encode('utf-8')
    
    headers = {
        "x-hub-signature-256": "sha256=invalid_signature_string",
        "x-github-event": "pull_request"
    }

    response = client.post("/webhooks/github", content=payload_bytes, headers=headers)
    
    assert response.status_code == 401
    assert "Invalid signature" in response.json()["detail"]

@pytest.mark.asyncio
@patch("backend.routers.webhooks.github_service")
@patch("backend.routers.webhooks.brd_manager")
async def test_github_api_timeout_incident(mock_brd_manager, mock_github_service):
    """
    Simulate third-party API downtime incident (GitHub API timeout).
    """
    mock_brd_manager.load_brd = AsyncMock(return_value="Mock BRD")
    
    # Simulate a timeout exception from httpx
    mock_github_service.get_pr_details = AsyncMock(side_effect=httpx.TimeoutException("GitHub API timed out"))
    
    payload = {
        "action": "opened",
        "number": 123,
        "repository": {"full_name": "test/repo"},
        "pull_request": {"title": "Test PR", "number": 123, "base": {"ref": "main"}}
    }
    payload_bytes = json.dumps(payload).encode('utf-8')
    signature = generate_github_signature(payload_bytes, settings.GITHUB_WEBHOOK_SECRET)
    
    headers = {
        "x-hub-signature-256": signature,
        "x-github-event": "pull_request"
    }

    # Since the route doesn't catch all exceptions explicitly, FastAPI will raise 500 Internal Server Error
    # but we can verify it doesn't crash the server and returns a 500 response.
    # We might need to ensure our app actually raises an HTTPException(503) or lets the 500 propagate.
    # In FastAPI TestClient, an unhandled exception will raise a 500 in the test client if we let it.
    response = client.post("/webhooks/github", content=payload_bytes, headers=headers)
    assert response.status_code == 504
    assert "Timeout" in response.json()["detail"]

@pytest.mark.asyncio
@patch("backend.routers.webhooks.github_service")
@patch("backend.routers.webhooks.brd_manager")
@patch("backend.routers.webhooks.ai_engine")
@patch("backend.routers.webhooks.insert")
async def test_ai_hallucination_shield_incident(mock_insert, mock_ai_engine, mock_brd_manager, mock_github_service):
    """
    Simulate AI hallucinating non-existent files and ensuring the system drops the confidence score.
    We test this by ensuring the ai_engine returns a low confidence score, which is inserted into DB.
    """
    mock_brd_manager.load_brd = AsyncMock(return_value="Mock BRD")
    mock_github_service.get_pr_details = AsyncMock(return_value={"title": "Test PR", "number": 123})
    mock_github_service.get_pr_diff = AsyncMock(return_value="--- a/file.py\n+++ b/file.py\n+print('hello')")
    
    from backend.models.schemas import PRSummary, WorkflowImpact, Severity
    mock_ai_summary = PRSummary(
        pr_number=123,
        repo="test/repo",
        title="Test PR",
        summary="Test summary",
        changes=[],
        workflow_impact=WorkflowImpact(
            has_impact=False,
            severity=Severity.NONE,
            impact_description="",
            affected_workflows=[]
        ),
        confidence_score=0.3, # Low confidence due to hallucination penalty
        analyzed_at="2026-06-17T00:00:00Z"
    )
    mock_ai_engine.analyze_pr = AsyncMock(return_value=mock_ai_summary)
    mock_insert = AsyncMock()

    payload = {
        "action": "opened",
        "number": 123,
        "repository": {"full_name": "test/repo"},
        "pull_request": {"title": "Test PR", "number": 123, "base": {"ref": "main"}}
    }
    payload_bytes = json.dumps(payload).encode('utf-8')
    signature = generate_github_signature(payload_bytes, settings.GITHUB_WEBHOOK_SECRET)
    
    headers = {
        "x-hub-signature-256": signature,
        "x-github-event": "pull_request"
    }

    response = client.post("/webhooks/github", content=payload_bytes, headers=headers)
    
    assert response.status_code == 200
    assert response.json()["data"]["confidence_score"] == 0.3
