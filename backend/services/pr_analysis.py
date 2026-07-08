import json
import logging
from backend.services.ai_engine import AIEngine
from typing import Optional
from backend.models.schemas import PRSummary
from backend.database import insert

# Instantiate AI engine
ai_engine = AIEngine()

logger = logging.getLogger("capsule.pr_analysis")

from backend.services.github_service import GitHubService
from backend.services.brd_manager import BRDManager

# Default instances for production; can be overridden in unit tests.
github_service = GitHubService()
brd_manager = BRDManager()

async def run_pr_analysis(
    repo: str,
    pr_number: int,
    branch_name: Optional[str] = None,
    github_service=None,
    ai_engine=None,
    brd_manager=None,
) -> dict:
    """Fetch PR details, run AI analysis, persist the result.

    Args:
        repo: Repository identifier in "owner/repo" format.
        pr_number: Pull request number.
        branch_name: Optional branch name; if omitted it will be derived from the PR data.
        github_service: Optional custom GitHubService instance (for mocking in tests).
        ai_engine: Optional custom AIEngine instance (for mocking in tests).
        brd_manager: Optional custom BRDManager instance (for mocking in tests).

    Returns:
        The dictionary representation of the persisted PRSummary.
    """
    gh = github_service if github_service is not None else globals()["github_service"]
    ai = ai_engine if ai_engine is not None else globals()["ai_engine"]
    brd_mngr = brd_manager if brd_manager is not None else globals()["brd_manager"]

    # Fetch required PR information.
    pr_details = await gh.get_pr_details(repo, pr_number)
    title = pr_details.get("title", "")
    diff = await gh.get_pr_diff(repo, pr_number)
    
    # Derive branch name from PR if not supplied.
    if branch_name is None:
        branch_name = pr_details.get("head_ref", "")

    # Load the latest Business Requirements Document (BRD) content for default profile 1
    brd_content = await brd_mngr.load_brd(1)

    # Perform the analysis using the AI engine.
    summary: PRSummary = await ai.analyze_pr(
        pr_number=pr_number,
        repo=repo,
        pr_title=title,
        diff=diff,
        brd_content=brd_content,
        branch_name=branch_name,
    )

    # Persist the result in the database.
    try:
        # Construct summary dict aligned with database schema
        db_data = {
            "pr_number": pr_number,
            "repo": repo,
            "title": summary.title,
            "summary": summary.summary,
            "original_summary": summary.summary,
            "brd_comparison": summary.brd_comparison,
            "branch": branch_name or summary.branch,
            "approved": False,
            "changes_json": json.dumps([c.model_dump() for c in summary.changes]),
            "workflow_impact_json": json.dumps(summary.workflow_impact.model_dump()),
            "confidence_score": summary.confidence_score,
        }
        record_id = await insert("pr_analyses", db_data)
        logger.info(f"PR analysis persisted with id {record_id}")
    except Exception as e:
        logger.error(f"Failed to insert PR analysis result: {e}")
        raise

    # Return the stored representation (including the generated id).
    result = summary.model_dump()
    result["id"] = record_id
    return result

