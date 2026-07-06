import os
import sys
# Resolve package paths for Vercel/serverless environments
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.config import settings
from backend.database import init_db
from backend.services.brd_manager import BRDManager
from backend.routers import webhooks, api, profiles

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("capsule.main")

# Disable interactive API docs in production for security
_IS_PRODUCTION = os.environ.get("ENV", "production").lower() == "production"
_docs_url = None if _IS_PRODUCTION else "/docs"
_redoc_url = None if _IS_PRODUCTION else "/redoc"
_openapi_url = None if _IS_PRODUCTION else "/openapi.json"

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up Capsule API Service...")
    
    # 1. Initialize SQLite Database Tables
    await init_db()
    
    # 2. Pre-load/Initialize active BRD into memory for the default profile
    brd_manager = BRDManager()
    await brd_manager.load_brd(profile_id=1)
    
    logger.info("Capsule API Service successfully started and ready to handle requests.")
    yield

# Initialize FastAPI App
app = FastAPI(
    title="Capsule — PR Analyzer API",
    description="Backend service for AI-powered PR analysis, workflow impact detection, and changelog generation.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

# CORS — allow Chrome extension origins and the Vercel frontend.
# Wildcard (*) with allow_credentials=True is rejected by browsers anyway
# and violates OWASP A05; we restrict to known origins instead.
ALLOWED_ORIGINS = [
    "https://capsule-opal-nine.vercel.app",
    "chrome-extension://",  # Chrome extension origins are validated by API key
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Chrome extensions need wildcard; security is enforced by X-API-Key
    allow_credentials=False,      # Credentials=False with wildcard is safe and valid
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["X-API-Key", "Content-Type", "Authorization", "x-hub-signature-256"],
)

# Include Routers
app.include_router(webhooks.router)
app.include_router(api.router)
app.include_router(profiles.router)

@app.get("/")
def read_root():
    return {
        "project": "Capsule",
        "status": "operational",
    }
