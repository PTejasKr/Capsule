import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
import httpx
from pydantic import BaseModel
from backend.config import settings
from backend.database import execute

logger = logging.getLogger("capsule.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

# Using GitHub OAuth URL
GITHUB_OAUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"

@router.get("/github/login")
async def github_login(request: Request, profile_id: int = 1):
    """
    Redirects the user to GitHub OAuth login.
    """
    client_id = getattr(settings, "GITHUB_CLIENT_ID", None)
    if not client_id:
        raise HTTPException(status_code=500, detail="GitHub Client ID not configured")
        
    host = getattr(settings, "HOST_URL", "http://localhost:8000")
    redirect_uri = f"{host}/api/auth/github/callback"
    url = f"{GITHUB_OAUTH_URL}?client_id={client_id}&redirect_uri={redirect_uri}&scope=repo,admin:repo_hook&state={profile_id}"
    return RedirectResponse(url)

@router.get("/github/callback")
async def github_callback(request: Request, code: str, state: str):
    """
    Handles the GitHub OAuth callback, exchanges code for token, and saves it to the profile.
    """
    client_id = getattr(settings, "GITHUB_CLIENT_ID", None)
    client_secret = getattr(settings, "GITHUB_CLIENT_SECRET", None)
    
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="GitHub OAuth credentials not configured")
        
    try:
        profile_id = int(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    # Exchange code for token
    headers = {"Accept": "application/json"}
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code
    }
    
    async with httpx.AsyncClient() as client:
        res = await client.post(GITHUB_TOKEN_URL, json=payload, headers=headers)
        if res.status_code != 200:
            logger.error(f"Failed to fetch GitHub token: {res.text}")
            raise HTTPException(status_code=500, detail="Failed to authenticate with GitHub")
            
        data = res.json()
        access_token = data.get("access_token")
        if not access_token:
            logger.error(f"GitHub token response missing access_token: {data}")
            raise HTTPException(status_code=500, detail="Invalid token response from GitHub")
            
    # Save token to the profile
    try:
        await execute("UPDATE profiles SET github_token = ? WHERE id = ?", (access_token, profile_id))
        logger.info(f"Successfully saved GitHub token for profile {profile_id}")
    except Exception as e:
        logger.error(f"Failed to update profile token: {e}")
        raise HTTPException(status_code=500, detail="Database error while saving token")
        
    # Redirect back to the extension or a success page
    return {"status": "success", "message": "Authentication successful. You can close this window."}

class ExtensionLoginPayload(BaseModel):
    code: str

@router.post("/extension/login")
async def extension_login(payload: ExtensionLoginPayload):
    """
    Exchanges the Chrome Extension's OAuth code for a token and verifies org membership.
    If valid, returns the master API key.
    """
    client_id = getattr(settings, "GITHUB_CLIENT_ID", None)
    client_secret = getattr(settings, "GITHUB_CLIENT_SECRET", None)
    target_org = getattr(settings, "COMPANY_GITHUB_ORG", "")

    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="GitHub OAuth credentials not configured")
    if not target_org:
        # If no org is configured, we can either reject or allow anyone.
        # Since this is enterprise software, we should reject if not configured securely.
        raise HTTPException(status_code=500, detail="COMPANY_GITHUB_ORG not configured")

    headers = {"Accept": "application/json"}
    auth_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": payload.code
    }
    
    async with httpx.AsyncClient() as client:
        # 1. Exchange code for token
        res = await client.post(GITHUB_TOKEN_URL, json=auth_payload, headers=headers)
        if res.status_code != 200:
            logger.error(f"Failed to fetch GitHub token for extension: {res.text}")
            raise HTTPException(status_code=401, detail="Invalid OAuth code")
            
        data = res.json()
        access_token = data.get("access_token")
        if not access_token:
            logger.error(f"GitHub token response missing access_token: {data}")
            raise HTTPException(status_code=401, detail="Invalid token response from GitHub")
            
        # 2. Check user's orgs (including private memberships if authorized)
        orgs_res = await client.get(
            "https://api.github.com/user/memberships/orgs",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github.v3+json"}
        )
        if orgs_res.status_code != 200:
            logger.error(f"Failed to fetch user org memberships: {orgs_res.text}")
            raise HTTPException(status_code=500, detail="Failed to verify organization membership")
            
        memberships = orgs_res.json()
        is_member = any(
            m.get("organization", {}).get("login", "").lower() == target_org.lower() 
            and m.get("state") == "active"
            for m in memberships
        )
        
        if not is_member:
            logger.warning(f"Unauthorized login attempt. User is not in {target_org}")
            raise HTTPException(status_code=403, detail=f"Unauthorized: You must be a member of the {target_org} organization.")
            
        # 3. Success! Return API key
        logger.info("Extension auto-login successful.")
        return {
            "status": "success",
            "api_key": settings.API_KEY
        }

@router.get("/extension/config")
async def extension_config():
    """
    Returns public configuration for the extension (e.g. GitHub Client ID).
    """
    client_id = getattr(settings, "GITHUB_CLIENT_ID", None)
    if not client_id:
        raise HTTPException(status_code=500, detail="GitHub Client ID not configured")
    
    return {
        "github_client_id": client_id
    }


