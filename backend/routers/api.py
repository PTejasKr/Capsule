import json
import logging
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from typing import Optional, List
from backend.middleware.security import verify_api_key
from backend.services.github_service import GitHubService
from backend.services.ai_engine import AIEngine
from backend.services.brd_manager import BRDManager
from backend.services.changelog_service import ChangelogService
from backend.database import fetch_one, insert
from backend.models.schemas import PRSummary, WorkflowImpact, ChangelogEntry, BRDUploadResponse, BRDHistoryItem, ChangeItem, Severity, ChangeType

logger = logging.getLogger("capsule.api")
router = APIRouter(prefix="/api", tags=["api"])

# Initialize services
github_service = GitHubService()
ai_engine = AIEngine()
brd_manager = BRDManager()
changelog_service = ChangelogService(github_service)

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
async def get_pr_summary(pr_number: int, repo: str):
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
async def get_pr_workflow_impact(pr_number: int, repo: str):
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
async def get_changelog_preview(pr_number: int, repo: str):
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
    push_res = await changelog_service.push_changelog(entry)
    
    return {
        "status": "success",
        "message": f"Changelog pushed for version {entry.version}",
        "version": entry.version,
        "push_result": push_res
    }

@router.post("/pr/{pr_number}/approve", dependencies=[Depends(verify_api_key)])
async def approve_pr(pr_number: int, repo: str):
    """
    Approves a feature branch analysis, making it visible to the extension.
    """
    from backend.database import execute_query
    sql = "UPDATE pr_analyses SET approved = ? WHERE pr_number = ? AND repo = ?"
    updated = await execute_query(sql, (True, pr_number, repo))
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PR #{pr_number} in {repo} not found to approve."
        )
    return {"status": "success", "message": f"PR #{pr_number} in {repo} approved."}

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


@router.post("/brd/upload", dependencies=[Depends(verify_api_key)], response_model=BRDUploadResponse)
async def upload_brd_file(
    file: Optional[UploadFile] = File(None),
    text_content: Optional[str] = Form(None),
    version: Optional[str] = Form(None)
):
    """
    Uploads a new Business Requirement Document (BRD) version.
    Supports either file upload or plain text form content.
    """
    if file:
        content_bytes = await file.read()
        content = content_bytes.decode("utf-8")
    elif text_content:
        content = text_content
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either file or text_content must be provided"
        )

    res = await brd_manager.upload_brd(content, version)
    current_meta = await brd_manager.get_current_brd()
    
    return BRDUploadResponse(
        status=res["status"],
        version=res["version"],
        hash=res["hash"],
        uploaded_at=current_meta.get("uploaded_at", "Just Uploaded")
    )

@router.get("/brd/current", dependencies=[Depends(verify_api_key)])
async def get_current_brd():
    """
    Returns active BRD document details.
    """
    meta = await brd_manager.get_current_brd()
    if not meta:
        return {"content": "", "version": "v0.0.0", "hash": "", "uploaded_at": None}
    return meta

@router.get("/brd/history", dependencies=[Depends(verify_api_key)], response_model=List[BRDHistoryItem])
async def get_brd_history():
    """
    Returns history of all uploaded BRD versions.
    """
    return await brd_manager.get_brd_history()
