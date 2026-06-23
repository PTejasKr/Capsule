import logging
from fastapi import APIRouter, Depends, HTTPException, status
from backend.middleware.security import verify_api_key
from backend.models.schemas import ProfileCreate, ProfileResponse, RepositoryMappingCreate
from backend.database import insert, fetch_one, fetch_all, execute_query

logger = logging.getLogger("capsule.profiles")
router = APIRouter(prefix="/profiles", tags=["profiles"], dependencies=[Depends(verify_api_key)])

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
    # Verify profile exists
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
