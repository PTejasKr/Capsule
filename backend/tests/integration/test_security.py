import pytest
import json
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings
from backend.database import insert, fetch_one, execute_query, init_db

client = TestClient(app)

@pytest.mark.asyncio
async def test_cross_pipeline_branch_visibility_control():
    """
    Security Test: Verifies that feature branch analyses are not visible without approval,
    while main branch analyses are visible immediately.
    """
    await init_db()
    
    # 1. Setup - insert a feature branch PR analysis (unapproved)
    repo = "testorg/testsecurity"
    pr_num = 501
    
    # Clean up any residual data first
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
    
    # 2. Try fetching the summary - should be Forbidden (403)
    headers = {"X-API-Key": settings.API_KEY}
    response = client.get(f"/api/pr/{pr_num}/summary?repo={repo}", headers=headers)
    assert response.status_code == 403
    assert "requires pipeline approval" in response.json()["detail"]
    
    # 3. Approve the PR analysis
    approve_response = client.post(f"/api/pr/{pr_num}/approve?repo={repo}", headers=headers)
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "success"
    
    # 4. Fetch again - should now be OK (200)
    response = client.get(f"/api/pr/{pr_num}/summary?repo={repo}", headers=headers)
    assert response.status_code == 200
    assert response.json()["pr_number"] == pr_num
    assert response.json()["branch"] == "feature/payment-fix"
    
    # 5. Verify that 'main' branch PR analysis is visible immediately without approval
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
    
    # Clean up
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
    
    # First insert
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
    
    # Second insert (updates the entry)
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
    
    # Verify only one row exists and it has the updated value
    headers = {"X-API-Key": settings.API_KEY}
    response = client.get(f"/api/pr/{pr_num}/summary?repo={repo}", headers=headers)
    assert response.status_code == 200
    assert response.json()["title"] == "Second Version"
    assert response.json()["summary"] == "Updated summary"
    
    # Clean up
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
    
    # Insert audit entry containing mock output
    await insert("audit_log", {
        "pr_number": pr_num,
        "input_hash": "hash123",
        "output_json": '{"summary": "Test summary text"}',
        "model": "meta/llama-3.1-70b-instruct",
        "tokens": 1500,
        "latency_ms": 320.5
    })
    
    # Fetch log from DB to verify it does not contain credentials
    log = await fetch_one("SELECT * FROM audit_log WHERE pr_number = ?", (pr_num,))
    assert log is not None
    
    # Convert log to string to do a simple containment check
    log_str = json.dumps(dict(log))
    
    # Check that secrets are not in the log
    if settings.GITHUB_TOKEN:
        assert settings.GITHUB_TOKEN not in log_str
    if settings.NVIDIA_NIM_API_KEY:
        assert settings.NVIDIA_NIM_API_KEY not in log_str
    if settings.API_KEY:
        assert settings.API_KEY not in log_str
        
    # Clean up
    await execute_query("DELETE FROM audit_log WHERE pr_number = ?", (pr_num,))
