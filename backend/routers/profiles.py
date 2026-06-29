import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
import httpx
from backend.middleware.security import verify_api_key
from backend.models.schemas import (
    ProfileCreate, ProfileResponse, RepositoryMappingCreate, 
    WebhookDeployRequest, BRDUploadResponse, BRDHistoryItem
)
from backend.database import insert, fetch_one, fetch_all, execute_query
from backend.services.brd_manager import BRDManager

logger = logging.getLogger("capsule.profiles")
router = APIRouter(prefix="/profiles", tags=["profiles"], dependencies=[Depends(verify_api_key)])
brd_manager = BRDManager()

@router.post("/", response_model=ProfileResponse)
async def create_profile(profile: ProfileCreate):
    """
    Creates a new profile. Requires API key.
    """
    try:
        data = profile.model_dump()
        profile_id = await insert("profiles", data)
        return ProfileResponse(id=profile_id, **data)
    except Exception as e:
        logger.error(f"Error creating profile: {e}")
        raise HTTPException(status_code=400, detail="Profile creation failed (possibly duplicate name)")

@router.get("/", response_model=list[ProfileResponse])
async def list_profiles():
    """
    Lists all profiles.
    """
    rows = await fetch_all("SELECT * FROM profiles")
    return [ProfileResponse(**row) for row in rows]

@router.post("/mappings")
async def map_repository(mapping: RepositoryMappingCreate):
    """
    Maps a repository to a specific profile.
    """
    profile = await fetch_one("SELECT * FROM profiles WHERE id = ?", (mapping.profile_id,))
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    try:
        await insert("repository_mappings", mapping.model_dump())
        return {"status": "success", "message": f"Mapped {mapping.source_repo} to profile {mapping.profile_id}"}
    except Exception as e:
        logger.error(f"Error mapping repository: {e}")
        raise HTTPException(status_code=400, detail="Mapping failed")

@router.get("/mappings/{owner}/{repo}")
async def get_repository_mapping(owner: str, repo: str):
    """
    Gets the profile mapped to a specific repository.
    """
    full_repo = f"{owner}/{repo}"
    row = await fetch_one("""
        SELECT p.* FROM profiles p
        JOIN repository_mappings rm ON p.id = rm.profile_id
        WHERE rm.source_repo = ?
    """, (full_repo,))
    
    if not row:
        raise HTTPException(status_code=404, detail="No profile mapping found for this repository")
        
    return ProfileResponse(**row)

@router.post("/mappings/deploy-webhook")
async def deploy_webhook(request: WebhookDeployRequest):
    """
    Deploys a GitHub webhook to the source_repo using the profile's GitHub token.
    """
    profile = await fetch_one("SELECT * FROM profiles WHERE id = ?", (request.profile_id,))
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    token = profile.get("github_token")
    if not token:
        raise HTTPException(status_code=400, detail="Profile has no github_token configured")
        
    # Map repository in DB as well
    try:
        await insert("repository_mappings", {"source_repo": request.source_repo, "profile_id": request.profile_id})
    except Exception as e:
        logger.warning(f"Repo already mapped or mapping failed: {e}")

    # Register webhook on GitHub
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    payload = {
        "name": "web",
        "active": True,
        "events": ["pull_request", "pull_request_review"],
        "config": {
            "url": request.webhook_url,
            "content_type": "json",
            "insecure_ssl": "0"
        }
    }
    
    url = f"https://api.github.com/repos/{request.source_repo}/hooks"
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code in [200, 201]:
            return {"status": "success", "message": "Webhook deployed successfully"}
        elif resp.status_code == 422:
            return {"status": "skipped", "message": "Webhook might already exist"}
        else:
            logger.error(f"GitHub API Error: {resp.text}")
            raise HTTPException(status_code=400, detail=f"Failed to deploy webhook: {resp.text}")

# --- BRD Endpoints scoped by profile_id ---

@router.post("/{profile_id}/brd/upload", response_model=BRDUploadResponse)
async def upload_brd_file(
    profile_id: int,
    file: Optional[UploadFile] = File(None),
    text_content: Optional[str] = Form(None),
    version: Optional[str] = Form(None)
):
    """
    Uploads a new BRD version for a specific profile.
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

    res = await brd_manager.upload_brd(profile_id, content, version)
    current_meta = await brd_manager.get_current_brd(profile_id)
    
    return BRDUploadResponse(
        status=res["status"],
        version=res["version"],
        hash=res["hash"],
        uploaded_at=current_meta.get("uploaded_at", "Just Uploaded") if current_meta else "Just Uploaded"
    )

@router.get("/{profile_id}/brd/current")
async def get_current_brd(profile_id: int):
    """
    Returns active BRD document details for a profile.
    """
    meta = await brd_manager.get_current_brd(profile_id)
    if not meta:
        return {"content": "", "version": "v0.0.0", "hash": "", "uploaded_at": None}
    return meta

@router.get("/{profile_id}/brd/history", response_model=List[BRDHistoryItem])
async def get_brd_history(profile_id: int):
    """
    Returns history of all uploaded BRD versions for a profile.
    """
    return await brd_manager.get_brd_history(profile_id)
