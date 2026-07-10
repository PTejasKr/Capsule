import pytest
import json
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings
from backend.tests.integration.test_webhooks import generate_github_signature

client = TestClient(app)

@pytest.mark.asyncio
async def test_jenkins_webhook_unauthorized():
    """
    Incident Test: Jenkins pipeline trigger with missing/invalid API key.
    Ensures that the pipeline cannot be triggered maliciously.
    """
    payload = {"pr_number": 123, "action": "opened"}
    
    response = client.post("/webhooks/jenkins", json=payload)
    assert response.status_code == 401
    assert "Could not validate credentials" in response.json()["detail"]
    
    headers = {"X-API-Key": "invalid_key"}
    response = client.post("/webhooks/jenkins", json=payload, headers=headers)
    assert response.status_code == 401
    assert "Could not validate credentials" in response.json()["detail"]

@pytest.mark.asyncio
@patch("backend.routers.webhooks.run_pr_analysis")
async def test_jenkins_webhook_authorized(mock_run_pr_analysis):
    """
    Pipeline Test: Authorized Jenkins trigger works correctly.
    """
    mock_run_pr_analysis.return_value = {"summary": "Mocked analysis"}
    
    payload = {"pr_number": 123, "action": "opened"}
    headers = {"X-API-Key": settings.API_KEY}
    
    response = client.post("/webhooks/jenkins", json=payload, headers=headers)
    
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_run_pr_analysis.assert_called_once_with(settings.CHANGELOG_REPO, 123)

@pytest.mark.asyncio
@patch("backend.routers.webhooks.fetch_one")
@patch("backend.routers.webhooks.run_pr_analysis")
async def test_approval_procedure_unmerged_pr_close(mock_run_pr_analysis, mock_fetch_one):
    """
    Approval Procedure Test: If a PR is closed but NOT merged (e.g., rejected/closed without approval),
    the changelog generation should not be triggered.
    """
    payload = {
        "action": "closed",
        "number": 123,
        "repository": {"full_name": "test/repo"},
        "pull_request": {
            "merged": False  # Crucial: Not merged
        }
    }
    payload_bytes = json.dumps(payload).encode('utf-8')
    signature = generate_github_signature(payload_bytes, settings.GITHUB_WEBHOOK_SECRET)
    
    headers = {
        "x-hub-signature-256": signature,
        "x-github-event": "pull_request"
    }

    response = client.post("/webhooks/github", content=payload_bytes, headers=headers)
    
    assert response.status_code == 200
    assert response.json()["status"] == "ignored_action"
    
    mock_fetch_one.assert_not_called()
