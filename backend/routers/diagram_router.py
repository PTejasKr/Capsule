from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict
import base64

from backend.services.diagram_service import DiagramService
from backend.services.github_service import GitHubService, get_github_service

router = APIRouter()

class DiagramRequest(BaseModel):
    name: str
    workflow: Dict
    commit: bool = False
    repo_url: Optional[str] = None

class DiagramResponse(BaseModel):
    url: str

@router.post("/api/workflow/diagram", response_model=DiagramResponse)
async def create_diagram(request: DiagramRequest, github: GitHubService = Depends(get_github_service)):
    png_bytes = DiagramService.generate_diagram(request.workflow)
    if request.commit:
        if not request.repo_url:
            raise HTTPException(status_code=400, detail="repo_url required when commit=True")
        b64 = base64.b64encode(png_bytes).decode()
        await github.commit_file(
            repo="PTejasKr/Capsule",
            branch="diagrams",
            path=f"diagrams/{request.name}.png",
            content=b64,
            message=f"Add workflow diagram {request.name}"
        )
        return DiagramResponse(url=f"{request.repo_url}/blob/diagrams/{request.name}.png")
    else:
        return DiagramResponse(url="data:image/png;base64," + base64.b64encode(png_bytes).decode())
