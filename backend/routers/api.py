import json
import logging
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from typing import Optional, List
from backend.middleware.security import verify_api_key, validate_repo_name
from backend.services.github_service import GitHubService
from backend.services.ai_engine import AIEngine
from backend.services.brd_manager import BRDManager
from backend.services.changelog_service import ChangelogService
from backend.database import fetch_one, insert
from backend.models.schemas import PRSummary, WorkflowImpact, ChangelogEntry, BRDUploadResponse, BRDHistoryItem, ChangeItem, Severity, ChangeType, RepoSetupRequest

logger = logging.getLogger("capsule.api")
router = APIRouter(tags=["api"])

# Initialize services
github_service = GitHubService()
ai_engine = AIEngine()
brd_manager = BRDManager()
changelog_service = ChangelogService(github_service)

def validate_repo(repo: str) -> str:
    if not validate_repo_name(repo):
        raise HTTPException(status_code=400, detail="Invalid repository format")
    return repo

async def _reconstruct_summary_from_row(row: dict) -> PRSummary:
    """Helper to reconstruct PRSummary schema from DB row."""
    changes_list = json.loads(row["changes_json"])
    changes = [
        ChangeItem(
            file=c["file"],
            line_range=c["line_range"],
            change_type=ChangeType(c["change_type"]),
            description=c["description"],
            confidence=c["confidence"]
        ) for c in changes_list
    ]
    
    wf_dict = json.loads(row["workflow_impact_json"])
    workflow_impact = WorkflowImpact(
        has_impact=wf_dict["has_impact"],
        severity=Severity(wf_dict["severity"]),
        impact_description=wf_dict["impact_description"],
        affected_workflows=wf_dict["affected_workflows"],
        before_state=wf_dict["before_state"],
        after_state=wf_dict["after_state"]
    )
    
    return PRSummary(
        pr_number=row["pr_number"],
        repo=row["repo"],
        branch=row.get("branch"),
        title=row["title"],
        summary=row["summary"],
        changes=changes,
        workflow_impact=workflow_impact,
        confidence_score=row["confidence_score"]
    )

@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "capsule-api"}

@router.get("/pr/{pr_number}/summary", dependencies=[Depends(verify_api_key)], response_model=PRSummary)
async def get_pr_summary(pr_number: int, repo: str = Depends(validate_repo)):
    """
    Fetches the saved PR analysis summary from database.
    """
    sql = "SELECT * FROM pr_analyses WHERE pr_number = ? AND repo = ?"
    row = await fetch_one(sql, (pr_number, repo))
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Summary not found for PR #{pr_number}. Make sure it has been analyzed."
        )
    
    # Check pipeline visibility / approval gate
    is_approved = bool(row.get("approved"))
    branch = row.get("branch")
    if not is_approved and branch != "main":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this PR analysis requires pipeline approval."
        )
        
    return await _reconstruct_summary_from_row(row)

@router.get("/pr/{pr_number}/workflow-impact", dependencies=[Depends(verify_api_key)], response_model=WorkflowImpact)
async def get_pr_workflow_impact(pr_number: int, repo: str = Depends(validate_repo)):
    """
    Fetches specifically the workflow impact analysis for a PR.
    """
    sql = "SELECT workflow_impact_json, approved, branch FROM pr_analyses WHERE pr_number = ? AND repo = ?"
    row = await fetch_one(sql, (pr_number, repo))
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PR #{pr_number} has not been analyzed yet."
        )
    
    is_approved = bool(row.get("approved"))
    branch = row.get("branch")
    if not is_approved and branch != "main":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this PR analysis requires pipeline approval."
        )
        
    wf_dict = json.loads(row["workflow_impact_json"])
    return WorkflowImpact(
        has_impact=wf_dict["has_impact"],
        severity=Severity(wf_dict["severity"]),
        impact_description=wf_dict["impact_description"],
        affected_workflows=wf_dict["affected_workflows"],
        before_state=wf_dict["before_state"],
        after_state=wf_dict["after_state"]
    )

@router.get("/pr/{pr_number}/changelog-preview", dependencies=[Depends(verify_api_key)], response_model=ChangelogEntry)
async def get_changelog_preview(pr_number: int, repo: str = Depends(validate_repo)):
    """
    Generates a preview of the changelog entry for this PR.
    """
    sql = "SELECT * FROM pr_analyses WHERE pr_number = ? AND repo = ?"
    row = await fetch_one(sql, (pr_number, repo))
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PR #{pr_number} must be analyzed before previewing changelog."
        )
        
    is_approved = bool(row.get("approved"))
    branch = row.get("branch")
    if not is_approved and branch != "main":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this PR analysis requires pipeline approval."
        )
    
    pr_summary = await _reconstruct_summary_from_row(row)
    files_metadata = await github_service.get_pr_files(repo, pr_number)
    
    entry = await changelog_service.generate_changelog(pr_summary, files_metadata)
    return entry

@router.post("/pr/{pr_number}/generate-changelog", dependencies=[Depends(verify_api_key)])
async def generate_and_push_changelog(pr_number: int, repo: Optional[str] = None):
    """
    Explicit trigger to generate and push the changelog to the release repo.
    Used by Jenkins post-merge hook.
    """
    repo = repo or settings.CHANGELOG_REPO
    sql = "SELECT * FROM pr_analyses WHERE pr_number = ? AND repo = ?"
    row = await fetch_one(sql, (pr_number, repo))
    
    if not row:
        # If not analyzed, analyze now
        try:
            from backend.routers.webhooks import run_pr_analysis
            await run_pr_analysis(repo, pr_number)
            row = await fetch_one(sql, (pr_number, repo))
        except Exception as e:
            logger.error(f"Failed to run PR analysis before changelog generation: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"PR #{pr_number} was not analyzed and auto-analysis failed: {str(e)}"
            )

    is_approved = bool(row.get("approved"))
    branch = row.get("branch")
    if not is_approved and branch != "main":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this PR analysis requires pipeline approval."
        )

    pr_summary = await _reconstruct_summary_from_row(row)
    files_metadata = await github_service.get_pr_files(repo, pr_number)
    
    entry = await changelog_service.generate_changelog(pr_summary, files_metadata)
    push_res = await changelog_service.push_changelog(entry, repo)
    
    return {
        "status": "success",
        "message": f"Changelog pushed for version {entry.version}",
        "version": entry.version,
        "push_result": push_res
    }

@router.post("/pr/{pr_number}/approve", dependencies=[Depends(verify_api_key)])
async def approve_pr(pr_number: int, repo: str = Depends(validate_repo)):
    """
    Approves a feature branch analysis, making it visible to the extension,
    and automatically generates and pushes the changelog.
    """
    from backend.database import execute_query
    
    # 1. Mark as approved in DB
    sql = "UPDATE pr_analyses SET approved = ? WHERE pr_number = ? AND repo = ?"
    updated = await execute_query(sql, (True, pr_number, repo))
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PR #{pr_number} in {repo} not found to approve."
        )
        
    # 2. Trigger changelog generation and push
    try:
        changelog_result = await generate_and_push_changelog(pr_number, repo)
        return {
            "status": "success", 
            "message": f"PR #{pr_number} in {repo} approved and changelog pushed.",
            "changelog": changelog_result
        }
    except Exception as e:
        logger.error(f"PR approved but failed to push changelog: {e}")
        return {
            "status": "partial_success",
            "message": f"PR #{pr_number} approved, but changelog generation failed: {str(e)}"
        }

from pydantic import BaseModel
class RepairSummaryRequest(BaseModel):
    edited_summary: str

@router.post("/pr/{pr_number}/repair", dependencies=[Depends(verify_api_key)])
async def repair_pr_summary(pr_number: int, request: RepairSummaryRequest, repo: str = Depends(validate_repo)):
    """
    Allows the Admin to repair or edit the generated summary before approval.
    """
    from backend.database import execute_query
    sql = "UPDATE pr_analyses SET summary = ?, approved = ? WHERE pr_number = ? AND repo = ?"
    updated = await execute_query(sql, (request.edited_summary, False, pr_number, repo))
    if not updated:
        raise HTTPException(status_code=404, detail="PR analysis not found.")
    return {"status": "success", "message": "Summary updated."}

@router.get("/pr/{pr_number}/compare", dependencies=[Depends(verify_api_key)])
async def compare_pr_summaries(pr_number: int, repo: str = Depends(validate_repo)):
    """
    Uses OpenRouter to compare the original AI summary with the currently edited summary.
    """
    sql = "SELECT original_summary, summary FROM pr_analyses WHERE pr_number = ? AND repo = ?"
    row = await fetch_one(sql, (pr_number, repo))
    if not row:
        raise HTTPException(status_code=404, detail="PR analysis not found.")
        
    original = row.get("original_summary")
    current = row.get("summary")
    
    if original == current or not original:
        return {"differences_detected": False, "message": "No edits made to the summary."}
        
    comparison = await ai_engine.compare_summaries(original, current)
    return comparison

@router.get("/pr/pending", dependencies=[Depends(verify_api_key)], response_model=List[PRSummary])
async def get_pending_prs():
    """
    Retrieves all unapproved PRs across all repositories.
    """
    from backend.database import fetch_all
    sql = "SELECT * FROM pr_analyses WHERE approved = ?"
    rows = await fetch_all(sql, (False,))
    
    summaries = []
    for r in rows:
        try:
            summary = await _reconstruct_summary_from_row(r)
            summaries.append(summary)
        except Exception as e:
            logger.error(f"Error reconstructing PR summary: {e}")
            continue
            
    return summaries

@router.post("/pr/{pr_number}/reject", dependencies=[Depends(verify_api_key)])
async def reject_pr(pr_number: int, repo: str = Depends(validate_repo)):
    """
    Rejects a PR by removing it from the database so it no longer appears in the pending queue.
    """
    from backend.database import execute_query
    sql = "DELETE FROM pr_analyses WHERE pr_number = ? AND repo = ?"
    deleted = await execute_query(sql, (pr_number, repo))
    if not deleted:
        raise HTTPException(status_code=404, detail="PR analysis not found.")
    return {"status": "success", "message": "PR rejected and removed from pending queue."}

@router.post("/pr/{pr_number}/auto-repair", dependencies=[Depends(verify_api_key)])
async def auto_repair_pr(pr_number: int, repo: str = Depends(validate_repo)):
    """
    Uses the Multi-LLM architecture to automatically generate and apply code fixes for a PR.
    """
    sql = "SELECT original_summary, summary, branch FROM pr_analyses WHERE pr_number = ? AND repo = ?"
    row = await fetch_one(sql, (pr_number, repo))
    if not row:
        raise HTTPException(status_code=404, detail="PR analysis not found.")
        
    branch = row.get("branch")
    if not branch or branch == "main":
        raise HTTPException(status_code=400, detail="Cannot auto-repair the main branch or unknown branch.")
        
    # 1. Fetch current files changed in the PR
    files_metadata = await github_service.get_pr_files(repo, pr_number)
    
    # 2. Use AI Engine to generate patch
    patch_result = await ai_engine.auto_repair_code(row.get("summary"), files_metadata)
    
    # 3. Apply patch via GitHub API
    commit_result = await github_service.commit_repair_patch(repo, branch, patch_result)
    
    return {
        "status": "success", 
        "message": f"Auto-repair completed and pushed to {branch}.",
        "details": commit_result
    }

@router.get("/changes/weekly", dependencies=[Depends(verify_api_key)], response_model=List[PRSummary])
async def get_weekly_changes():
    """
    Retrieves approved or main-branch PR summaries from the past 7 days.
    """
    from datetime import datetime, timedelta
    from backend.database import fetch_all
    
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    seven_days_ago_str = seven_days_ago.strftime("%Y-%m-%d %H:%M:%S")
    
    sql = "SELECT * FROM pr_analyses WHERE analyzed_at >= ? AND (approved = ? OR branch = ?)"
    rows = await fetch_all(sql, (seven_days_ago_str, True, "main"))
    
    summaries = []
    for r in rows:
        try:
            summary = await _reconstruct_summary_from_row(r)
            summaries.append(summary)
        except Exception as e:
            logger.error(f"Error reconstructing PR summary from database row: {e}")
            continue
            
    return summaries

@router.post("/setup-repository", dependencies=[Depends(verify_api_key)])
async def setup_repository(request: RepoSetupRequest):
    """
    Onboards a new repository to Capsule:
    1. Ensures the 'changelog' branch exists (creates it from default branch if missing).
    2. Configures a GitHub Webhook programmatically for pull_request events.
    """
    repo = request.repo
    callback_url = request.callback_url
    
    logger.info(f"Running automated Capsule infrastructure setup for repository: {repo}")
    
    # Step 1: Ensure changelog branch exists
    try:
        await github_service.ensure_branch_exists(repo, "changelog")
    except Exception as e:
        logger.error(f"Failed to ensure/create changelog branch: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to check/create changelog branch on GitHub: {str(e)}"
        )
        
    # Step 2: Configure Webhook programmatically
    try:
        hook_res = await github_service.create_repository_webhook(repo, callback_url)
    except Exception as e:
        logger.error(f"Failed to configure GitHub webhook: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create webhook on GitHub repository: {str(e)}"
        )
        
    return {
        "status": "success",
        "message": f"Successfully onboarded repository '{repo}' to Capsule.",
        "changelog_branch": "configured",
        "webhook": hook_res
    }

@router.post("/workflow/diagram", dependencies=[Depends(verify_api_key)])
async def generate_workflow_diagram(payload: dict):
    """
    Generates a workflow diagram image from text description.
    Uses the free AI models via the routing service to produce Mermaid.js code,
    then returns a QuickChart.io rendered image URL.
    """
    import urllib.parse
    workflow_text = payload.get("workflow_text", "")
    if not workflow_text:
        raise HTTPException(status_code=400, detail="workflow_text is required")

    try:
        mermaid_code = await ai_engine.generate_mermaid(workflow_text)
        encoded = urllib.parse.quote(mermaid_code)
        image_url = f"https://quickchart.io/chart?c=%7Btype:%27mermaid%27%7D&bkg=white&width=800&height=600&chart={encoded}"
        return {"image_url": image_url, "mermaid_code": mermaid_code}
    except Exception as e:
        logger.error(f"Failed to generate workflow diagram: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate workflow diagram: {str(e)}"
        )
