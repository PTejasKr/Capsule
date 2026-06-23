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

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up Capsule API Service...")
    
    # 1. Initialize SQLite Database Tables
    await init_db()
    
    # 2. Pre-load/Initialize active BRD into memory
    brd_manager = BRDManager()
    await brd_manager.load_brd()
    
    logger.info("Capsule API Service successfully started and ready to handle requests.")
    yield

# Initialize FastAPI App
app = FastAPI(
    title="Capsule — PR Analyzer API",
    description="Backend service for AI-powered PR analysis, workflow impact detection, and changelog generation.",
    version="1.0.0",
    lifespan=lifespan
)

# Set up CORS middleware
# Chrome extensions make requests from unique origins (chrome-extension://<id>).
# We allow all origins to ensure compatibility, secured strictly via API Key / webhook signatures.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(webhooks.router)
app.include_router(api.router)
app.include_router(profiles.router)

@app.get("/")
def read_root():
    return {
        "project": "Capsule",
        "description": "AI-Powered PR Analysis & Release System Backend",
        "docs_url": "/docs"
    }
