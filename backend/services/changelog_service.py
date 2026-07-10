import json
import logging
import time
import base64
from typing import List, Dict, Any, Optional
from datetime import datetime
from backend.config import settings
from backend.models.schemas import PRSummary, ChangelogEntry, Severity
from backend.services.github_service import GitHubService
from backend.database import fetch_one, insert

logger = logging.getLogger("capsule.changelog_service")

class ChangelogService:
    def __init__(self, github_service: Optional[GitHubService] = None):
        self.github_service = github_service or GitHubService()

    async def get_latest_version(self) -> str:
        """
        Retrieves the latest recorded version from the database.
        Defaults to 'v0.0.0' if no records exist.
        """
        try:
            sql = "SELECT version FROM changelog_entries ORDER BY id DESC LIMIT 1"
            row = await fetch_one(sql)
            if row:
                return row["version"]
        except Exception as e:
            logger.error(f"Error fetching latest version: {e}")
        return "v0.0.0"

    def _increment_version(self, current: str, severity: Severity) -> str:
        """
        Increments version (vMAJOR.MINOR.PATCH) based on workflow change severity.
        - major -> Increment MAJOR, reset MINOR and PATCH
        - minor -> Increment MINOR, reset PATCH
        - none -> Increment PATCH
        """
        cleaned = current.lstrip("v")
        try:
            parts = [int(x) for x in cleaned.split(".")]
        except Exception:
            parts = [0, 0, 0]

        if len(parts) < 3:
            parts = parts + [0] * (3 - len(parts))

        if severity == Severity.MAJOR:
            parts[0] += 1
            parts[1] = 0
            parts[2] = 0
        elif severity == Severity.MINOR:
            parts[1] += 1
            parts[2] = 0
        else:
            parts[2] += 1

        return f"v{parts[0]}.{parts[1]}.{parts[2]}"

    def _format_changelog_entry_text(self, entry: ChangelogEntry) -> str:
        """
        Formats a single changelog entry into standard markdown/text format.
        """
        text = f"## [{entry.version}] - {entry.date}\n"
        
        if entry.brd_comparison:
            text += "### BRD Comparison\n"
            text += f"{entry.brd_comparison}\n\n"
        
        
        text += "### Technical Changes\n"
        if entry.technical_changes:
            for change in entry.technical_changes:
                text += f"- {change}\n"
        else:
            text += "- No technical changes listed.\n"
            
        text += "### Workflow Changes\n"
        if entry.workflow_changes:
            for change in entry.workflow_changes:
                text += f"- {change}\n"
        else:
            text += "- No workflow changes detected.\n"
            
        text += f"### Lines Changed: +{entry.lines_added} / -{entry.lines_deleted}\n\n"
        return text

    async def generate_changelog(self, pr_summary: PRSummary, files_metadata: List[Dict[str, Any]]) -> ChangelogEntry:
        """
        Generates a versioned ChangelogEntry based on the AI analysis and file diffs.
        """
        logger.info(f"Generating changelog for PR #{pr_summary.pr_number}")
        
        additions = sum(f.get("additions", 0) for f in files_metadata)
        deletions = sum(f.get("deletions", 0) for f in files_metadata)

        latest_ver = await self.get_latest_version()
        severity = pr_summary.workflow_impact.severity
        new_version = self._increment_version(latest_ver, severity)
        
        tech_changes = []
        for c in pr_summary.changes:
            tech_changes.append(f"[{c.file}:L{c.line_range}] {c.description}")
            
        workflow_changes = []
        if pr_summary.workflow_impact.has_impact:
            workflow_changes.append(
                f"{pr_summary.workflow_impact.impact_description} "
                f"(Workflows: {', '.join(pr_summary.workflow_impact.affected_workflows)})"
            )
            if pr_summary.workflow_impact.before_state or pr_summary.workflow_impact.after_state:
                workflow_changes.append(
                    f"State Transition Change: "
                    f"[{pr_summary.workflow_impact.before_state}] -> [{pr_summary.workflow_impact.after_state}]"
                )

        return ChangelogEntry(
            version=new_version,
            date=datetime.now().strftime("%Y-%m-%d"),
            technical_changes=tech_changes,
            workflow_changes=workflow_changes,
            lines_added=additions,
            lines_deleted=deletions,
            pr_number=pr_summary.pr_number,
            brd_comparison=pr_summary.brd_comparison
        )

    async def push_changelog(self, entry: ChangelogEntry, target_repo: str = None) -> Dict[str, Any]:
        """
        Reads the existing changelog.txt from the changelog branch (if it exists),
        prepends the new entry, and pushes the updated file back to the changelog branch of target_repo.
        Also generates a workflow diagram using Workers AI and pushes the diagram and markdown summary.
        """
        target_repo = target_repo or settings.CHANGELOG_REPO
        logger.info(f"Prepending entry for version {entry.version} and pushing to repository {target_repo} on branch changelog")
        
        path = "changelog.txt"
        commit_message = f"chore(release): release version {entry.version} (PR #{entry.pr_number})"
        
        existing_content = ""
        try:
            url = f"https://api.github.com/repos/{target_repo}/contents/{path}?ref=changelog"
            headers = {"Authorization": f"token {settings.GITHUB_TOKEN}"}
            
            import httpx
            async with httpx.AsyncClient() as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    file_data = res.json()
                    raw_b64 = file_data.get("content", "")
                    existing_content = base64.b64decode(raw_b64.replace("\n", "")).decode("utf-8")
        except Exception as e:
            logger.warning(f"Could not read existing changelog.txt from branch changelog: {e}")

        new_entry_text = self._format_changelog_entry_text(entry)
        
        updated_content = new_entry_text + existing_content
        
        result = await self.github_service.push_changelog(
            path,
            updated_content,
            commit_message,
            target_repo,
            branch="changelog"
        )

        wf_desc = "Software development process flow chart"
        if entry.pr_number:
            try:
                analysis_row = await fetch_one("SELECT * FROM pr_analyses WHERE pr_number = ? LIMIT 1", (entry.pr_number,))
                if analysis_row:
                    wf_impact = json.loads(analysis_row["workflow_impact_json"])
                    if wf_impact.get("has_impact") and wf_impact.get("impact_description"):
                        wf_desc = wf_impact.get("impact_description")
            except Exception as e:
                logger.warning(f"Could not fetch workflow description from DB: {e}")

        image_bytes = None
        if settings.CLOUDFLARE_WORKER_URL:
            try:
                worker_image_url = f"{settings.CLOUDFLARE_WORKER_URL}/api/regenerate-workflow-image"
                async with httpx.AsyncClient() as client:
                    img_res = await client.post(
                        worker_image_url,
                        json={"workflow_text": wf_desc},
                        timeout=40.0
                    )
                    if img_res.status_code == 200:
                        image_bytes = img_res.content
                        logger.info(f"Generated workflow diagram from Cloudflare Worker for PR #{entry.pr_number}")
            except Exception as ex:
                logger.error(f"Failed to generate workflow diagram from Cloudflare Worker: {ex}")

        if image_bytes:
            try:
                image_path = f"diagrams/pr_{entry.pr_number}.png"
                image_commit = f"image(changelog): upload workflow diagram for PR #{entry.pr_number}"
                await self.github_service.push_changelog(
                    image_path,
                    image_bytes,
                    image_commit,
                    target_repo,
                    branch="changelog"
                )
            except Exception as e:
                logger.error(f"Failed to push workflow diagram to changelog branch: {e}")

        try:
            summary_md = f"# PR #{entry.pr_number} Summary\n\n"
            summary_md += f"- **Version**: {entry.version}\n"
            summary_md += f"- **Date**: {entry.date}\n"
            summary_md += f"- **Lines Changed**: +{entry.lines_added} / -{entry.lines_deleted}\n\n"
            summary_md += "## Technical Changes\n"
            for tc in entry.technical_changes:
                summary_md += f"- {tc}\n"
            summary_md += "\n## Workflow Changes\n"
            if entry.workflow_changes:
                for wc in entry.workflow_changes:
                    summary_md += f"- {wc}\n"
            else:
                summary_md += "- No workflow changes detected.\n"
            if image_bytes:
                summary_md += f"\n## Workflow Diagram\n![Workflow Diagram](../diagrams/pr_{entry.pr_number}.png)\n"
            if entry.brd_comparison:
                summary_md += f"\n## BRD Comparison\n{entry.brd_comparison}\n"

            summary_path = f"summaries/pr_{entry.pr_number}.md"
            summary_commit = f"docs(changelog): upload summary markdown for PR #{entry.pr_number}"
            await self.github_service.push_changelog(
                summary_path,
                summary_md,
                summary_commit,
                target_repo,
                branch="changelog"
            )
        except Exception as e:
            logger.error(f"Failed to push summary markdown to changelog branch: {e}")

        db_data = {
            "version": entry.version,
            "date": entry.date,
            "technical_changes_json": json.dumps(entry.technical_changes),
            "workflow_changes_json": json.dumps(entry.workflow_changes),
            "lines_added": entry.lines_added,
            "lines_deleted": entry.lines_deleted,
            "pr_number": entry.pr_number,
        }
        await insert("changelog_entries", db_data)
        
        try:
            pr_title = f"chore(release): Update Changelog for v{entry.version}"
            pr_body = f"This PR was auto-generated to append the latest AI summaries and BRD comparisons for version {entry.version}."
            pr_res = await self.github_service.create_pull_request(
                target_repo,
                title=pr_title,
                head="changelog",
                base="main",
                body=pr_body
            )
            logger.info(f"Opened PR from changelog to main: {pr_res.get('html_url')}")
        except Exception as e:
            logger.error(f"Failed to create PR from changelog to main: {e}")

        return {"status": "success", "file": path, "commit": result.get("sha")}
