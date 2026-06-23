import os
import hashlib
import logging
import re
from typing import List, Dict, Any, Optional
from backend.config import settings
from backend.database import fetch_one, fetch_all, insert

logger = logging.getLogger("capsule.brd_manager")

class BRDManager:
    def __init__(self):
        self.file_path = settings.BRD_FILE_PATH
        self._cached_brd: Optional[Dict[str, Any]] = None

    async def load_brd(self) -> str:
        """
        Loads the latest active BRD content.
        Tries loading from database, then falls back to local file.
        Caches the result in memory.
        """
        # 1. Try to read from cache first
        if self._cached_brd:
            return self._cached_brd["content"]

        # 2. Try to fetch the latest version from database
        try:
            sql = "SELECT content, version, hash, uploaded_at FROM brd_versions ORDER BY id DESC LIMIT 1"
            row = await fetch_one(sql)
            if row:
                self._cached_brd = {
                    "content": row["content"],
                    "version": row["version"],
                    "hash": row["hash"],
                    "uploaded_at": row["uploaded_at"]
                }
                logger.info(f"Loaded BRD version {row['version']} from database")
                return row["content"]
        except Exception as e:
            logger.error(f"Error fetching BRD from database: {e}")

        # 3. Fallback to local file path
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Create a version hash
                content_hash = hashlib.sha256(content.encode()).hexdigest()
                version = "v1.0.0"
                
                # Cache it
                self._cached_brd = {
                    "content": content,
                    "version": version,
                    "hash": content_hash,
                    "uploaded_at": "Local File"
                }
                
                # Save to database so we have it persistent
                await self.upload_brd(content, version)
                logger.info(f"Loaded BRD from local file {self.file_path} and saved to database")
                return content
            except Exception as e:
                logger.error(f"Error reading local BRD file: {e}")
        else:
            logger.warning(f"BRD file not found at: {self.file_path}")

        return ""

    async def upload_brd(self, content: str, version: Optional[str] = None) -> Dict[str, Any]:
        """
        Saves a new BRD content into the database, computing hash and version.
        Updates cache.
        """
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        
        # Check if version exists already
        existing = await fetch_one("SELECT version FROM brd_versions WHERE hash = ?", (content_hash,))
        if existing:
            logger.info(f"BRD content already exists as version: {existing['version']}")
            # Update cache
            self._cached_brd = {
                "content": content,
                "version": existing["version"],
                "hash": content_hash,
                "uploaded_at": "Already Uploaded"
            }
            return {"status": "skipped", "version": existing["version"], "hash": content_hash}

        # Auto-increment version if not provided
        if not version:
            latest = await fetch_one("SELECT version FROM brd_versions ORDER BY id DESC LIMIT 1")
            if latest:
                try:
                    # e.g., v1.2.3 -> parse and increment minor
                    ver_str = latest["version"].lstrip("v")
                    parts = [int(p) for p in ver_str.split(".")]
                    parts[1] += 1  # Increment minor version
                    parts[2] = 0   # Reset patch
                    version = f"v{parts[0]}.{parts[1]}.{parts[2]}"
                except Exception:
                    version = "v1.1.0"
            else:
                version = "v1.0.0"

        # Insert to database
        db_data = {
            "content": content,
            "version": version,
            "hash": content_hash
        }
        await insert("brd_versions", db_data)
        
        # Invalidate/update cache
        self._cached_brd = {
            "content": content,
            "version": version,
            "hash": content_hash,
            "uploaded_at": "Just Uploaded"
        }
        
        # If path to settings.BRD_FILE_PATH doesn't exist or is different, write it to file as well
        try:
            dir_name = os.path.dirname(self.file_path)
            if dir_name and not os.path.exists(dir_name):
                os.makedirs(dir_name, exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            logger.error(f"Could not write uploaded BRD to disk path {self.file_path}: {e}")

        logger.info(f"Successfully uploaded and activated BRD version: {version}")
        return {"status": "success", "version": version, "hash": content_hash}

    async def get_current_brd(self) -> Optional[Dict[str, Any]]:
        """
        Returns metadata about the active BRD.
        """
        await self.load_brd()  # Ensure cache is populated
        return self._cached_brd

    async def get_brd_history(self) -> List[Dict[str, Any]]:
        """
        Returns list of all uploaded BRD versions.
        """
        sql = "SELECT id, version, hash, uploaded_at FROM brd_versions ORDER BY id DESC"
        return await fetch_all(sql)

    def extract_workflow_sections(self, brd_content: str) -> str:
        """
        Parses BRD markdown and extracts sections related to workflows/processes.
        Looks for headers containing terms: workflow, flow, process, sequence, pipeline, steps.
        """
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
                # Count headers
                level = len(line) - len(line.lstrip("#"))
                if workflow_header_pattern.match(line):
                    capturing = True
                    current_header_level = level
                    sections.append(line)
                elif capturing and level <= current_header_level:
                    # Found another header at same or higher level, stop capturing unless it also matches
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
        """
        Creates a condensed version of workflows to maximize token space.
        """
        workflow_text = self.extract_workflow_sections(brd_content)
        # Clean up double line breaks, remove large image links or HTML tags
        clean_text = re.sub(r"!\[.*?\]\(.*?\)", "", workflow_text)  # Remove images
        clean_text = re.sub(r"<.*?>", "", clean_text)  # Remove HTML tags
        clean_text = re.sub(r"\n\s*\n+", "\n\n", clean_text)  # Collapse empty lines
        return clean_text.strip()
