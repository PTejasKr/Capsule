import pytest
import hmac
import hashlib
import json
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings

client = TestClient(app)

def generate_github_signature(payload_body: bytes, secret: str) -> str:
    hmac_obj = hmac.new(
        secret.encode('utf-8'),
        payload_body,
        hashlib.sha256
    )
    return f"sha256={hmac_obj.hexdigest()}"

@pytest.mark.asyncio
@patch("backend.routers.webhooks.github_service")
@patch("backend.routers.webhooks.ai_engine")
@patch("backend.routers.webhooks.brd_manager")
@patch("backend.routers.webhooks.insert")
async def test_github_webhook_pr_opened(mock_insert, mock_brd_manager, mock_ai_engine, mock_github_service):
    mock_brd_manager.load_brd = AsyncMock(return_value="Mock BRD Content")
    
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
        confidence_score=0.9,
        analyzed_at="2026-06-17T00:00:00Z"
    )
    mock_ai_engine.analyze_pr = AsyncMock(return_value=mock_ai_summary)
    mock_insert = AsyncMock()

    payload = {
        "action": "opened",
        "number": 123,
        "repository": {"full_name": "test/repo"},
        "pull_request": {
            "title": "Test PR",
            "number": 123,
            "base": {"ref": "main"}
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
    assert response.json()["status"] == "analyzed"
    assert response.json()["pr_number"] == 123
    
    mock_github_service.get_pr_diff.assert_called_once_with("test/repo", 123)
    mock_ai_engine.analyze_pr.assert_called_once()

@pytest.mark.asyncio
@patch("backend.routers.webhooks.changelog_service")
@patch("backend.routers.webhooks.fetch_one")
@patch("backend.routers.webhooks.github_service")
async def test_github_webhook_pr_merged(mock_github_service, mock_fetch_one, mock_changelog_service):
    mock_fetch_one.return_value = {
        "pr_number": 123,
        "repo": "test/repo",
        "title": "Test PR",
        "summary": "Summary",
        "changes_json": "[]",
        "workflow_impact_json": '{"has_impact": false, "severity": "none", "impact_description": "", "affected_workflows": [], "before_state": "", "after_state": ""}',
        "confidence_score": 0.9
    }
    
    mock_github_service.get_pr_files = AsyncMock(return_value=[{"additions": 10, "deletions": 5}])
    
    from backend.models.schemas import ChangelogEntry
    mock_entry = ChangelogEntry(
        version="v1.0.1",
        date="2026-06-17",
        technical_changes=[],
        workflow_changes=[],
        lines_added=10,
        lines_deleted=5,
        pr_number=123
    )
    mock_changelog_service.generate_changelog = AsyncMock(return_value=mock_entry)
    mock_changelog_service.push_changelog = AsyncMock(return_value={"commit": "sha123"})
    
    payload = {
        "action": "closed",
        "number": 123,
        "repository": {"full_name": "test/repo"},
        "pull_request": {
            "merged": True
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
    assert response.json()["status"] == "changelog_pushed"
    assert response.json()["version"] == "v1.0.1"
    
    mock_changelog_service.generate_changelog.assert_called_once()
    mock_changelog_service.push_changelog.assert_called_once_with(mock_entry)
