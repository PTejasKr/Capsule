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
        
        # Calculate additions/deletions from file metadata
        additions = sum(f.get("additions", 0) for f in files_metadata)
        deletions = sum(f.get("deletions", 0) for f in files_metadata)

        # Retrieve latest version and increment it
        latest_ver = await self.get_latest_version()
        severity = pr_summary.workflow_impact.severity
        new_version = self._increment_version(latest_ver, severity)
        
        # Compile lists of changes
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
            pr_number=pr_summary.pr_number
        )

    async def push_changelog(self, entry: ChangelogEntry, target_repo: str = None) -> Dict[str, Any]:
        """
        Reads the existing changelog.txt from the repository (if it exists),
        prepends the new entry, and pushes the updated file back to the separate repo.
        """
        target_repo = target_repo or settings.CHANGELOG_REPO
        logger.info(f"Prepending entry for version {entry.version} and pushing to repository {target_repo}")
        
        path = "changelog.txt"
        commit_message = f"chore(release): release version {entry.version} (PR #{entry.pr_number})"
        
        # 1. Fetch current content of changelog.txt to prepend
        existing_content = ""
        try:
            url = f"https://api.github.com/repos/{target_repo}/contents/{path}"
            headers = {"Authorization": f"token {settings.GITHUB_TOKEN}"}
            
            # Simple async request using httpx to read current file contents
            import httpx
            async with httpx.AsyncClient() as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    file_data = res.json()
                    raw_b64 = file_data.get("content", "")
                    # GitHub contents are base64 encoded and might contain newlines
                    existing_content = base64_decode_str = base64.b64decode(raw_b64.replace("\n", "")).decode("utf-8")
        except Exception as e:
            logger.warning(f"Could not read existing changelog.txt (might be creating a new one): {e}")

        # 2. Format new entry
        new_entry_text = self._format_changelog_entry_text(entry)
        
        # Prepend to existing content
        updated_content = new_entry_text + existing_content
        
        # 3. Push back to GitHub
        result = await self.github_service.push_changelog(path, updated_content, commit_message, target_repo)
        
        # 4. Save to database
        db_data = {
            "version": entry.version,
            "date": entry.date,
            "technical_changes_json": json.dumps(entry.technical_changes),
            "workflow_changes_json": json.dumps(entry.workflow_changes),
            "lines_added": entry.lines_added,
            "lines_deleted": entry.lines_deleted,
            "pr_number": entry.pr_number,
            "pushed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        await insert("changelog_entries", db_data)
        
        return result
