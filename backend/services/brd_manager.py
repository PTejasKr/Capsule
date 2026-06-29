import os
import hashlib
import logging
import re
from typing import List, Dict, Any, Optional
from backend.config import settings
from backend.database import fetch_one, fetch_all, insert

logger = logging.getLogger("capsule.brd_manager")

DEFAULT_BRD_CONTENT = """# Sample BRD
## PRD
This is the default Product Requirements Document.
## Architecture
Backend: Python/FastAPI. Frontend: HTML/JS. Database: SQLite/PostgreSQL.
## Web Flow
User logs in -> views dashboard -> manages items.
"""

class BRDManager:
    def __init__(self):
        self.file_path = settings.BRD_FILE_PATH
        self.brd_folder = os.path.dirname(self.file_path) if os.path.dirname(self.file_path) else "brd"
        self._cached_brds: Dict[int, Dict[str, Any]] = {}

    def _ensure_default_brd_exists(self):
        if not os.path.exists(self.brd_folder):
            os.makedirs(self.brd_folder, exist_ok=True)
        
        sample_path = os.path.join(self.brd_folder, "sample_brd.md")
        files = os.listdir(self.brd_folder)
        if not files or (len(files) == 1 and files[0] == "sample_brd.md" and not os.path.exists(sample_path)):
            if not os.path.exists(sample_path):
                with open(sample_path, "w", encoding="utf-8") as f:
                    f.write(DEFAULT_BRD_CONTENT)
                logger.info(f"Created default BRD at {sample_path}")

    async def load_brd(self, profile_id: int) -> str:
        """
        Loads the latest active BRD content for a profile.
        Tries loading from database, then falls back to local file if it's the first profile or global fallback.
        Caches the result in memory per profile.
        """
        self._ensure_default_brd_exists()

        if profile_id in self._cached_brds:
            return self._cached_brds[profile_id]["content"]

        try:
            sql = "SELECT content, version, hash, uploaded_at FROM brd_versions WHERE profile_id = ? ORDER BY id DESC LIMIT 1"
            row = await fetch_one(sql, (profile_id,))
            if row:
                self._cached_brds[profile_id] = {
                    "content": row["content"],
                    "version": row["version"],
                    "hash": row["hash"],
                    "uploaded_at": row["uploaded_at"]
                }
                logger.info(f"Loaded BRD version {row['version']} from database for profile {profile_id}")
                return row["content"]
        except Exception as e:
            logger.error(f"Error fetching BRD from database for profile {profile_id}: {e}")

        # Fallback to sample_brd.md if DB has nothing
        sample_path = os.path.join(self.brd_folder, "sample_brd.md")
        if os.path.exists(sample_path):
            try:
                with open(sample_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                content_hash = hashlib.sha256(content.encode()).hexdigest()
                version = "v1.0.0"
                
                self._cached_brds[profile_id] = {
                    "content": content,
                    "version": version,
                    "hash": content_hash,
                    "uploaded_at": "Local File"
                }
                
                await self.upload_brd(profile_id, content, version)
                logger.info(f"Loaded BRD from local file {sample_path} and saved to database for profile {profile_id}")
                return content
            except Exception as e:
                logger.error(f"Error reading local BRD file: {e}")

        return ""

    async def upload_brd(self, profile_id: int, content: str, version: Optional[str] = None) -> Dict[str, Any]:
        """
        Saves a new BRD content into the database, computing hash and version, scoped by profile.
        """
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        
        existing = await fetch_one("SELECT version FROM brd_versions WHERE hash = ? AND profile_id = ?", (content_hash, profile_id))
        if existing:
            logger.info(f"BRD content already exists for profile {profile_id} as version: {existing['version']}")
            self._cached_brds[profile_id] = {
                "content": content,
                "version": existing["version"],
                "hash": content_hash,
                "uploaded_at": "Already Uploaded"
            }
            return {"status": "skipped", "version": existing["version"], "hash": content_hash}

        if not version:
            latest = await fetch_one("SELECT version FROM brd_versions WHERE profile_id = ? ORDER BY id DESC LIMIT 1", (profile_id,))
            if latest:
                try:
                    ver_str = latest["version"].lstrip("v")
                    parts = [int(p) for p in ver_str.split(".")]
                    parts[1] += 1
                    parts[2] = 0
                    version = f"v{parts[0]}.{parts[1]}.{parts[2]}"
                except Exception:
                    version = "v1.1.0"
            else:
                version = "v1.0.0"

        db_data = {
            "content": content,
            "version": version,
            "hash": content_hash,
            "profile_id": profile_id
        }
        await insert("brd_versions", db_data)
        
        self._cached_brds[profile_id] = {
            "content": content,
            "version": version,
            "hash": content_hash,
            "uploaded_at": "Just Uploaded"
        }
        
        return {"status": "success", "version": version, "hash": content_hash}

    async def get_current_brd(self, profile_id: int) -> Optional[Dict[str, Any]]:
        await self.load_brd(profile_id)
        return self._cached_brds.get(profile_id)

    async def get_brd_history(self, profile_id: int) -> List[Dict[str, Any]]:
        sql = "SELECT id, version, hash, uploaded_at FROM brd_versions WHERE profile_id = ? ORDER BY id DESC"
        return await fetch_all(sql, (profile_id,))

    def extract_workflow_sections(self, brd_content: str) -> str:
        if not brd_content:
            return ""

        sections = []
        lines = brd_content.splitlines()
        
        workflow_header_pattern = re.compile(
            r"^#+\s+.*(?:workflow|flow|process|sequence|pipeline|steps|transition).*", 
            re.IGNORECASE
        )
        
        capturing = False
        current_header_level = 0
        
        for line in lines:
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                if workflow_header_pattern.match(line):
                    capturing = True
                    current_header_level = level
                    sections.append(line)
                elif capturing and level <= current_header_level:
                    if workflow_header_pattern.match(line):
                        current_header_level = level
                        sections.append(line)
                    else:
                        capturing = False
                elif capturing:
                    sections.append(line)
            elif capturing:
                sections.append(line)
                
        if not sections:
            logger.info("No specific workflow headers found in BRD. Returning full document for analysis.")
            return brd_content
            
        return "\n".join(sections)

    def generate_workflow_summary(self, brd_content: str) -> str:
        workflow_text = self.extract_workflow_sections(brd_content)
        clean_text = re.sub(r"!\[.*?\]\(.*?\)", "", workflow_text)
        clean_text = re.sub(r"<.*?>", "", clean_text)
        clean_text = re.sub(r"\n\s*\n+", "\n\n", clean_text)
        return clean_text.strip()
