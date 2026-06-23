"""
Capsule Celery Tasks
--------------------
Async task definitions for PR analysis and changelog generation.
These run inside the Celery worker process — entirely separate from
the FastAPI web process — keeping webhooks non-blocking.

Key design decisions:
- Each task uses asyncio.run() to bridge sync Celery → async Python services.
- Retry on transient failures (network, rate-limit) with exponential back-off.
- All auth tokens come from settings (never from task arguments) to prevent
  accidental serialization of credentials into the Redis queue.
"""
import asyncio
import json
import logging
from typing import Optional

from celery.utils.log import get_task_logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from backend.worker import celery_app
from backend.config import settings

logger = get_task_logger("capsule.tasks")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Bridge Celery's synchronous task context to async service calls."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _core_pr_analysis(repo: str, pr_number: int) -> dict:
    """
    Executes the full PR analysis pipeline:
    1. Resolve profile (model, BRD, changelog_repo)
    2. Fetch PR details + raw diff from GitHub
    3. Run Map-Reduce AI analysis
    4. Persist results to database
    Returns the PRSummary as a dict.
    """
    import httpx
    from backend.services.github_service import GitHubService
    from backend.services.ai_engine import AIEngine
    from backend.services.brd_manager import BRDManager
    from backend.database import insert, fetch_one
    from backend.middleware.security import sanitize_text

    github_service = GitHubService()
    ai_engine = AIEngine()
    brd_manager = BRDManager()

    # --- resolve profile ---
    row = await fetch_one("""
        SELECT p.* FROM profiles p
        JOIN repository_mappings rm ON p.id = rm.profile_id
        WHERE rm.source_repo = ?
    """, (repo,))

    if row:
        profile = {
            "changelog_repo": row["changelog_repo"],
            "ai_model": row["ai_model"],
            "brd_content": row["brd_content"],
        }
    else:
        profile = {
            "changelog_repo": settings.CHANGELOG_REPO,
            "ai_model": settings.NVIDIA_NIM_MODEL,
            "brd_content": None,
        }

    brd = profile["brd_content"] or await brd_manager.load_brd()
    if not brd:
        raise ValueError("BRD missing. Upload a BRD before triggering analysis.")

    # --- fetch from GitHub ---
    pr_details = await github_service.get_pr_details(repo, pr_number)
    pr_diff    = await github_service.get_pr_diff(repo, pr_number)

    sanitized_diff  = sanitize_text(pr_diff)
    sanitized_title = sanitize_text(pr_details["title"])

    # --- AI analysis (Map-Reduce inside AIEngine) ---
    summary = await ai_engine.analyze_pr(
        pr_number=pr_number,
        repo=repo,
        pr_title=sanitized_title,
        diff=sanitized_diff,
        brd_content=brd,
        model=profile["ai_model"],
    )

    # --- persist ---
    await insert("pr_analyses", {
        "pr_number":            pr_number,
        "repo":                 repo,
        "title":                summary.title,
        "summary":              summary.summary,
        "branch":               pr_details.get("head_ref", "") or summary.branch,
        "approved":             False,
        "changes_json":         json.dumps([c.model_dump() for c in summary.changes]),
        "workflow_impact_json": json.dumps(summary.workflow_impact.model_dump()),
        "confidence_score":     summary.confidence_score,
    })

    return summary.model_dump()


async def _core_changelog(repo: str, pr_number: int) -> dict:
    """Generates and pushes the versioned changelog after a PR merge."""
    import json
    from backend.services.github_service import GitHubService
    from backend.services.changelog_service import ChangelogService
    from backend.database import fetch_one
    from backend.models.schemas import (
        PRSummary, WorkflowImpact, ChangeItem, Severity, ChangeType
    )

    github_service = GitHubService()
    changelog_service = ChangelogService(github_service)

    sql = "SELECT * FROM pr_analyses WHERE pr_number = ? AND repo = ?"
    row = await fetch_one(sql, (pr_number, repo))
    if not row:
        raise ValueError(f"No analysis found for PR #{pr_number} in {repo}")

    changes = [
        ChangeItem(
            file=c["file"],
            line_range=c["line_range"],
            change_type=ChangeType(c["change_type"]),
            description=c["description"],
            confidence=c["confidence"],
        )
        for c in json.loads(row["changes_json"])
    ]
    wf = json.loads(row["workflow_impact_json"])
    workflow_impact = WorkflowImpact(
        has_impact=wf["has_impact"],
        severity=Severity(wf["severity"]),
        impact_description=wf["impact_description"],
        affected_workflows=wf["affected_workflows"],
        before_state=wf.get("before_state", ""),
        after_state=wf.get("after_state", ""),
    )
    summary_obj = PRSummary(
        pr_number=pr_number,
        repo=repo,
        title=row["title"],
        summary=row["summary"],
        changes=changes,
        workflow_impact=workflow_impact,
        confidence_score=row["confidence_score"],
    )

    # resolve changelog repo for this profile
    profile_row = await fetch_one("""
        SELECT p.* FROM profiles p
        JOIN repository_mappings rm ON p.id = rm.profile_id
        WHERE rm.source_repo = ?
    """, (repo,))
    changelog_repo = (profile_row["changelog_repo"] if profile_row
                      else settings.CHANGELOG_REPO)

    files_metadata = await github_service.get_pr_files(repo, pr_number)
    entry = await changelog_service.generate_changelog(summary_obj, files_metadata)
    result = await changelog_service.push_changelog(entry, changelog_repo)
    return {"version": entry.version, "push_result": result}


# ---------------------------------------------------------------------------
# Celery task definitions
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    name="capsule.tasks.analyze_pr",
    max_retries=3,
    default_retry_delay=20,
    acks_late=True,
)
def analyze_pr_task(self, repo: str, pr_number: int):
    """
    Async task: fetch PR, run Map-Reduce LLM analysis, store results.
    Called via analyze_pr_task.delay(repo, pr_number).
    """
    logger.info(f"[Task {self.request.id}] Starting analysis — {repo} PR #{pr_number}")
    try:
        result = _run_async(_core_pr_analysis(repo, pr_number))
        logger.info(f"[Task {self.request.id}] Analysis complete — confidence={result.get('confidence_score')}")
        return {"status": "success", "pr_number": pr_number, "data": result}
    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Analysis failed: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=int(20 * (2 ** self.request.retries)))


@celery_app.task(
    bind=True,
    name="capsule.tasks.generate_changelog",
    max_retries=3,
    default_retry_delay=15,
    acks_late=True,
)
def generate_changelog_task(self, repo: str, pr_number: int):
    """
    Async task: generate and push changelog to the target repo after PR merge.
    Called via generate_changelog_task.delay(repo, pr_number).
    """
    logger.info(f"[Task {self.request.id}] Generating changelog — {repo} PR #{pr_number}")
    try:
        result = _run_async(_core_changelog(repo, pr_number))
        logger.info(f"[Task {self.request.id}] Changelog pushed — version={result.get('version')}")
        return {"status": "success", "pr_number": pr_number, **result}
    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Changelog failed: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=int(15 * (2 ** self.request.retries)))
