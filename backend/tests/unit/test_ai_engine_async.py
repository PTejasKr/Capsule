import pytest
import asyncio
from unittest.mock import AsyncMock, patch
import json

from backend.services.ai_engine import AIEngine
from backend.models.schemas import PRSummary

@pytest.fixture
def dummy_diff():
    return """diff --git a/file1.py b/file1.py\n--- a/file1.py\n+++ b/file1.py\n@@ -1,3 +1,3 @@\n-print('old')\n+print('new')\n"""

@pytest.fixture
def dummy_brd():
    return "Business Requirement Document content."

@pytest.fixture
def mock_llm_response():
    return {
        "summary": "Changes detected",
        "changes": [
            {
                "file": "file1.py",
                "line_range": "1-3",
                "change_type": "modified",
                "description": "Updated print statement",
                "confidence": 0.95
            }
        ],
        "workflow_impact": {
            "has_impact": False,
            "severity": "none",
            "impact_description": "",
            "affected_workflows": [],
            "before_state": "",
            "after_state": ""
        },
        "confidence_score": 0.95
    }

@pytest.mark.asyncio
async def test_analyze_pr_success(dummy_diff, dummy_brd, mock_llm_response):
    engine = AIEngine()
    with patch.object(engine, "client") as mock_client:
        async_response = AsyncMock()
        async_response.choices = [type('Choice', (), {"message": type('Message', (), {"content": json.dumps(mock_llm_response)})})]
        mock_client.chat.completions.create = AsyncMock(return_value=async_response)
        result: PRSummary = await engine.analyze_pr(
            pr_number=1,
            repo="test/repo",
            pr_title="Test PR",
            diff=dummy_diff,
            brd_content=dummy_brd
        )
        assert isinstance(result, PRSummary)
        assert result.pr_number == 1
        assert len(result.changes) == 1
        assert result.changes[0].file == "file1.py"
        assert result.changes[0].description == "Updated print statement"
        assert result.confidence_score == pytest.approx(0.95)
