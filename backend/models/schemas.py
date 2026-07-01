from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from datetime import datetime

class ChangeType(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"

class Severity(str, Enum):
    NONE = "none"
    MINOR = "minor"
    MAJOR = "major"

class ChangeItem(BaseModel):
    file: str = Field(..., description="The path of the file that was changed")
    line_range: str = Field(..., description="The range of lines changed, e.g., '12-25' or '45'")
    change_type: ChangeType = Field(..., description="The type of change (added, modified, deleted)")
    description: str = Field(..., description="Brief, clear description of the specific code changes")
    confidence: float = Field(..., description="Confidence score (0.0 to 1.0) of this change description")

class WorkflowImpact(BaseModel):
    has_impact: bool = Field(..., description="Whether the changes alter any business workflow defined in the BRD")
    severity: Severity = Field(..., description="Severity of workflow change (none, minor, major)")
    impact_description: Optional[str] = Field("", description="Detailed explanation of the workflow impact")
    affected_workflows: List[str] = Field(default_factory=list, description="List of workflows from the BRD that are impacted")
    before_state: Optional[str] = Field("", description="Workflow state before the change")
    after_state: Optional[str] = Field("", description="Workflow state after the change")

class PRSummary(BaseModel):
    pr_number: int = Field(..., description="The GitHub pull request number")
    repo: str = Field(..., description="The repository name in owner/repo format")
    branch: Optional[str] = Field(None, description="The branch name the PR targets")
    title: str = Field(..., description="The title of the pull request")
    summary: str = Field(..., description="High-level, human-readable summary of the changes")
    changes: List[ChangeItem] = Field(..., description="List of specific technical changes")
    workflow_impact: WorkflowImpact = Field(..., description="Analysis of changes against the BRD workflows")
    confidence_score: float = Field(..., description="Overall confidence score of the analysis")
    analyzed_at: Optional[str] = Field(None, description="ISO timestamp of when the analysis was performed")

class ChangelogEntry(BaseModel):
    version: str = Field(..., description="Semantic version string, e.g., 'v1.0.1'")
    date: str = Field(..., description="ISO date of the entry, e.g., '2026-06-17'")
    technical_changes: List[str] = Field(..., description="Technical summary lines detailing file and line changes")
    workflow_changes: List[str] = Field(..., description="Workflow change lines explaining flow differences")
    lines_added: int = Field(0, description="Total number of lines added")
    lines_deleted: int = Field(0, description="Total number of lines deleted")
    pr_number: Optional[int] = Field(None, description="The PR number associated with this changelog entry")

class WebhookPayload(BaseModel):
    action: str
    number: int
    pull_request: dict
    repository: dict

class JenkinsWebhookPayload(BaseModel):
    pr_number: int
    repo: Optional[str] = None

    
class ProfileCreate(BaseModel):
    name: str = Field(..., description="Unique name for the profile")
    changelog_repo: str = Field(..., description="GitHub repository (owner/repo) to push changelogs to")
    ai_model: str = Field("meta/llama-3.1-70b-instruct", description="NVIDIA NIM model name")
    brd_content: Optional[str] = Field(None, description="Optional BRD content specific to this profile")
    github_token: Optional[str] = Field(None, description="GitHub token for 1-click deployment")

class ProfileResponse(ProfileCreate):
    id: int

class RepositoryMappingCreate(BaseModel):
    source_repo: str = Field(..., description="The repository triggering the webhook (owner/repo)")
    profile_id: int = Field(..., description="The ID of the profile to use")

class WebhookDeployRequest(BaseModel):
    source_repo: str = Field(..., description="The repository to deploy to (owner/repo)")
    profile_id: int = Field(..., description="The ID of the profile to use")
    webhook_url: str = Field(..., description="The publicly accessible webhook URL")

class BRDUploadResponse(BaseModel):
    status: str
    version: str
    hash: str
    uploaded_at: str

class BRDHistoryItem(BaseModel):
    id: int
    version: str
    uploaded_at: str
    hash: str

class RepoSetupRequest(BaseModel):
    repo: str = Field(..., description="The repository in owner/repo format")
    callback_url: str = Field(..., description="The public base URL of the Capsule server")
