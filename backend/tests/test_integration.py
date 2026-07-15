import asyncio
import json
import hmac
import hashlib
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
import pytest

from backend.main import app
from backend.config import settings
from backend.models.schemas import ChangelogEntry

def generate_github_signature(payload_body: bytes, secret: str) -> str:
    hmac_obj = hmac.new(
        secret.encode('utf-8'),
        payload_body,
        hashlib.sha256
    )
    return f"sha256={hmac_obj.hexdigest()}"

@pytest.mark.asyncio
@patch("backend.routers.webhooks.run_pr_analysis")
async def test_github_webhook_open(mock_run_pr_analysis):
    mock_run_pr_analysis.return_value = {"id": 1, "confidence_score": 0.9}
    
    payload = {
        "action": "opened",
        "number": 123,
        "repository": {"full_name": "testorg/testrepo"},
        "pull_request": {"merged": False},
    }
    payload_bytes = json.dumps(payload).encode('utf-8')
    signature = generate_github_signature(payload_bytes, settings.GITHUB_WEBHOOK_SECRET)
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/github",
            content=payload_bytes,
            headers={
                "X-Github-Event": "pull_request",
                "x-hub-signature-256": signature
            },
        )
        
    assert response.status_code == 200
    json_resp = response.json()
    assert json_resp["status"] == "analyzed"
    assert json_resp["pr_number"] == 123
    assert json_resp["data"]["id"] == 1


@pytest.mark.asyncio
@patch("backend.routers.webhooks.fetch_one")
@patch("backend.routers.webhooks.github_service")
@patch("backend.routers.webhooks.changelog_service")
async def test_github_webhook_close_merged(mock_changelog_service, mock_github_service, mock_fetch_one):
    mock_fetch_one.return_value = {
        "pr_number": 124,
        "repo": "testorg/testrepo",
        "title": "Test PR",
        "summary": "Summary",
        "changes_json": "[]",
        "workflow_impact_json": '{"has_impact": false, "severity": "none", "impact_description": "", "affected_workflows": [], "before_state": "", "after_state": ""}',
        "confidence_score": 0.9
    }
    mock_github_service.get_pr_files = AsyncMock(return_value=[{"additions": 10, "deletions": 5}])
    mock_entry = ChangelogEntry(
        version="v1.0.1",
        date="2026-06-17",
        technical_changes=[],
        workflow_changes=[],
        lines_added=10,
        lines_deleted=5,
        pr_number=124
    )
    mock_changelog_service.generate_changelog = AsyncMock(return_value=mock_entry)
    mock_changelog_service.push_changelog = AsyncMock(return_value={"commit": "sha123"})
    
    payload = {
        "action": "closed",
        "number": 124,
        "repository": {"full_name": "testorg/testrepo"},
        "pull_request": {"merged": True},
    }
    payload_bytes = json.dumps(payload).encode('utf-8')
    signature = generate_github_signature(payload_bytes, settings.GITHUB_WEBHOOK_SECRET)
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/github",
            content=payload_bytes,
            headers={
                "X-Github-Event": "pull_request",
                "x-hub-signature-256": signature
            },
        )
        
    assert response.status_code == 200
    json_resp = response.json()
    assert json_resp["status"] == "changelog_pushed"
    assert json_resp["version"] == "v1.0.1"
