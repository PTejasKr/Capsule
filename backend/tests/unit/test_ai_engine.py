import asyncio
import json
import pytest
from pathlib import Path

# Import the AIEngine from the project
from backend.services.ai_engine import AIEngine

# ──────────────────────────────────────────────────────────────
# Mock objects for the OpenAI client
# ──────────────────────────────────────────────────────────────
class DummyMessage:
    def __init__(self, content: str):
        self.content = content


class DummyChoice:
    def __init__(self, content: str):
        self.message = DummyMessage(content)


class DummyResponse:
    def __init__(self, content: dict):
        self.choices = [DummyChoice(json.dumps(content))]
        self.usage = type("Usage", (), {"total_tokens": 1})()


class DummyChatCompletions:
    async def create(self, *, model, messages, temperature, response_format, max_tokens):
        # Return a very small, deterministic JSON payload that matches the schema
        # The payload is the same for every chunk – the test will later verify that
        # the reducer merges the two chunks correctly.
        return DummyResponse(
            {
                "summary": "Chunk summary",
                "changes": [
                    {
                        "file": "src/example.py",
                        "line_range": "1-10",
                        "change_type": "added",
                        "description": "Added example function",
                        "confidence": 0.98,
                    }
                ],
                "workflow_impact": {
                    "has_impact": True,
                    "severity": "minor",
                    "impact_description": "Minor workflow change",
                    "affected_workflows": ["Demo Workflow"],
                    "before_state": "A->B",
                    "after_state": "A->C->B",
                },
                "confidence_score": 0.99,
            }
        )


class DummyClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": DummyChatCompletions()})()


# ──────────────────────────────────────────────────────────────
# Helper fixtures
# ──────────────────────────────────────────────────────────────
@pytest.fixture
def engine():
    """Create an AIEngine with a mocked OpenAI client."""
    e = AIEngine()
    # Replace the real AsyncOpenAI client with our dummy client
    e.client = DummyClient()
    return e


# ──────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────
def test_chunk_diff_splits_correctly():
    """Verify that _chunk_diff respects the max_lines limit."""
    diff = "\n".join([f"+ line {i}" for i in range(1, 801)])  # 800 added lines
    ai = AIEngine()
    chunks = ai._chunk_diff(diff, max_lines=300)
    # 800 lines → should be split into 3 chunks (300, 300, 200)
    assert len(chunks) == 3
    assert all(len(c.splitlines()) <= 300 for c in chunks)
    # Ensure the content is preserved
    reconstructed = "".join(chunks)
    assert reconstructed == diff + "\n"


@pytest.mark.asyncio
async def test_analyze_pr_parallel_aggregates_results(engine):
    """Run analyze_pr on a tiny diff and ensure the map‑reduce flow works."""
    # Minimal diff with two files (the same content is fine for the mock)
    diff = """--- a/src/example.py
+++ b/src/example.py
@@ -1,2 +1,3 @@
+def foo():
+    pass
"""

    brd = "Business Requirement Document placeholder – not used by the dummy client."

    # Call the method – it will use asyncio.gather under the hood
    result = await engine.analyze_pr(
        pr_number=1,
        repo="demo/repo",
        pr_title="Test PR",
        diff=diff,
        brd_content=brd,
    )

    # The dummy client returns the same JSON for every chunk.
    # Because our diff is only one chunk, we expect exactly those values.
    assert result.pr_number == 1
    assert result.repo == "demo/repo"
    assert result.title == "Test PR"
    assert result.summary == "Chunk summary"
    # Changes should contain the single change from the dummy payload
    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.file == "src/example.py"
    assert change.change_type.name == "ADDED"
    assert change.confidence == pytest.approx(0.98)
    # Workflow impact should be copied from the dummy payload
    wi = result.workflow_impact
    assert wi.has_impact is True
    assert wi.severity.name == "MINOR"
    assert wi.affected_workflows == ["Demo Workflow"]
