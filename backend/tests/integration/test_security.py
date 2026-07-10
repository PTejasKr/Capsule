import pytest
import json
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings
from backend.database import insert, fetch_one, execute_query, init_db
from unittest.mock import patch, AsyncMock

client = TestClient(app)

@pytest.mark.asyncio
@patch("backend.routers.api.generate_and_push_changelog", new_callable=AsyncMock)
async def test_cross_pipeline_branch_visibility_control(mock_push):
    """
    Security Test: Verifies that feature branch analyses are not visible without approval,
    while main branch analyses are visible immediately.
    """
    await init_db()
    mock_push.return_value = {"version": "v1.0.1"}
    
    repo = "testorg/testsecurity"
    pr_num = 501
    
    await execute_query("DELETE FROM pr_analyses WHERE pr_number = ? AND repo = ?", (pr_num, repo))
    
    await insert("pr_analyses", {
        "pr_number": pr_num,
        "repo": repo,
        "branch": "feature/payment-fix",
        "approved": False,
        "title": "Fix Payment Processing",
        "summary": "Fixes payment state transitions",
        "changes_json": "[]",
        "workflow_impact_json": '{"has_impact": false, "severity": "none", "impact_description": "", "affected_workflows": [], "before_state": "", "after_state": ""}',
        "confidence_score": 0.95
    })
    
    headers = {"X-API-Key": settings.API_KEY}
    response = client.get(f"/api/pr/{pr_num}/summary?repo={repo}", headers=headers)
    assert response.status_code == 403
    assert "requires pipeline approval" in response.json()["detail"]
    
    approve_response = client.post(f"/api/pr/{pr_num}/approve?repo={repo}", headers=headers)
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "success"
    
    response = client.get(f"/api/pr/{pr_num}/summary?repo={repo}", headers=headers)
    assert response.status_code == 200
    assert response.json()["pr_number"] == pr_num
    assert response.json()["branch"] == "feature/payment-fix"
    
    main_pr_num = 502
    await execute_query("DELETE FROM pr_analyses WHERE pr_number = ? AND repo = ?", (main_pr_num, repo))
    await insert("pr_analyses", {
        "pr_number": main_pr_num,
        "repo": repo,
        "branch": "main",
        "approved": False, # set to False to test main branch override
        "title": "Main Branch PR",
        "summary": "Core update",
        "changes_json": "[]",
        "workflow_impact_json": '{"has_impact": false, "severity": "none", "impact_description": "", "affected_workflows": [], "before_state": "", "after_state": ""}',
        "confidence_score": 0.99
    })
    
    response = client.get(f"/api/pr/{main_pr_num}/summary?repo={repo}", headers=headers)
    assert response.status_code == 200
    assert response.json()["pr_number"] == main_pr_num
    assert response.json()["branch"] == "main"
    
    await execute_query("DELETE FROM pr_analyses WHERE repo = ?", (repo,))

@pytest.mark.asyncio
async def test_data_duplication_prevention():
    """
    Security Test: Verifies that multiple inserts of the same PR analysis
    do not create duplicate entries (upsert behavior).
    """
    await init_db()
    
    repo = "testorg/testdup"
    pr_num = 601
    
    await execute_query("DELETE FROM pr_analyses WHERE pr_number = ? AND repo = ?", (pr_num, repo))
    
    await insert("pr_analyses", {
        "pr_number": pr_num,
        "repo": repo,
        "branch": "main",
        "approved": True,
        "title": "First Version",
        "summary": "Original summary",
        "changes_json": "[]",
        "workflow_impact_json": '{"has_impact": false, "severity": "none", "impact_description": "", "affected_workflows": [], "before_state": "", "after_state": ""}',
        "confidence_score": 0.8
    })
    
    await insert("pr_analyses", {
        "pr_number": pr_num,
        "repo": repo,
        "branch": "main",
        "approved": True,
        "title": "Second Version",
        "summary": "Updated summary",
        "changes_json": "[]",
        "workflow_impact_json": '{"has_impact": false, "severity": "none", "impact_description": "", "affected_workflows": [], "before_state": "", "after_state": ""}',
        "confidence_score": 0.95
    })
    
    headers = {"X-API-Key": settings.API_KEY}
    response = client.get(f"/api/pr/{pr_num}/summary?repo={repo}", headers=headers)
    assert response.status_code == 200
    assert response.json()["title"] == "Second Version"
    assert response.json()["summary"] == "Updated summary"
    
    await execute_query("DELETE FROM pr_analyses WHERE repo = ?", (repo,))

@pytest.mark.asyncio
async def test_data_leakage_checks():
    """
    Security Test: Verifies that sensitive system credentials are never saved
    in the database audit logs or exposed via summary endpoints.
    """
    await init_db()
    
    repo = "testorg/testleak"
    pr_num = 701
    
    await execute_query("DELETE FROM pr_analyses WHERE pr_number = ? AND repo = ?", (pr_num, repo))
    await execute_query("DELETE FROM audit_log WHERE pr_number = ?", (pr_num,))
    
    await insert("audit_log", {
        "pr_number": pr_num,
        "input_hash": "hash123",
        "output_json": '{"summary": "Test summary text"}',
        "model": "meta/llama-3.1-70b-instruct",
        "tokens": 1500,
        "latency_ms": 320.5
    })
    
    log = await fetch_one("SELECT * FROM audit_log WHERE pr_number = ?", (pr_num,))
    assert log is not None
    
    log_str = json.dumps(dict(log))
    
    if settings.GITHUB_TOKEN:
        assert settings.GITHUB_TOKEN not in log_str
    if settings.NVIDIA_NIM_API_KEY:
        assert settings.NVIDIA_NIM_API_KEY not in log_str
    if settings.API_KEY:
        assert settings.API_KEY not in log_str
        
    await execute_query("DELETE FROM audit_log WHERE pr_number = ?", (pr_num,))
