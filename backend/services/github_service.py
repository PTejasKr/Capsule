import base64
import logging
import asyncio
import httpx
from typing import List, Dict, Any, Optional
from backend.config import settings

logger = logging.getLogger("capsule.github_service")

class GitHubService:
    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.GITHUB_TOKEN
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.base_url = "https://api.github.com"

    async def _request_with_backoff(self, method: str, url: str, **kwargs) -> httpx.Response:
        """
        Executes HTTP request with exponential backoff on 403 Rate Limit or 5xx server errors.
        """
        headers = self.headers.copy()
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))

        max_retries = 5
        backoff_factor = 2.0
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(max_retries):
                try:
                    response = await client.request(method, url, headers=headers, **kwargs)
                    
                    # Check for rate limit or server error
                    if response.status_code == 403 and "X-RateLimit-Remaining" in response.headers:
                        remaining = int(response.headers.get("X-RateLimit-Remaining", 0))
                        if remaining == 0:
                            reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
                            import time
                            sleep_time = max(reset_time - time.time(), 5.0)
                            logger.warning(f"GitHub rate limit hit. Sleeping for {sleep_time:.1f} seconds (attempt {attempt + 1})")
                            await asyncio.sleep(sleep_time)
                            continue
                            
                    if response.status_code >= 500:
                        sleep_time = backoff_factor ** attempt
                        logger.warning(f"GitHub server error {response.status_code}. Retrying in {sleep_time:.1f} seconds")
                        await asyncio.sleep(sleep_time)
                        continue
                        
                    return response
                except httpx.RequestError as e:
                    sleep_time = backoff_factor ** attempt
                    logger.warning(f"Network error calling GitHub: {e}. Retrying in {sleep_time:.1f} seconds")
                    await asyncio.sleep(sleep_time)
                    if attempt == max_retries - 1:
                        raise e
            
            # If we fall through the loop, try one last time
            return await client.request(method, url, headers=headers, **kwargs)

    async def get_pr_details(self, repo: str, pr_number: int) -> Dict[str, Any]:
        """
        Fetches PR details (title, body, base/head ref, etc.)
        """
        logger.info(f"Fetching PR #{pr_number} details for repository: {repo}")
        url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}"
        response = await self._request_with_backoff("GET", url)
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch PR details: Status: {response.status_code} {response.reason_phrase}")
            response.raise_for_status()
            
        data = response.json()
        return {
            "pr_number": pr_number,
            "repo": repo,
            "title": data.get("title", ""),
            "body": data.get("body", "") or "",
            "state": data.get("state", ""),
            "merged": data.get("merged", False),
            "base_ref": data.get("base", {}).get("ref", ""),
            "head_ref": data.get("head", {}).get("ref", ""),
            "user": data.get("user", {}).get("login", ""),
            "html_url": data.get("html_url", "")
        }

    async def get_pr_diff(self, repo: str, pr_number: int) -> str:
        """
        Fetches the unified diff of the PR using headers for raw diff.
        """
        logger.info(f"Fetching raw diff for PR #{pr_number} on: {repo}")
        url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}"
        
        # Use custom headers to request raw unified diff
        headers = {"Accept": "application/vnd.github.v3.diff"}
        response = await self._request_with_backoff("GET", url, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch PR diff: Status: {response.status_code} {response.reason_phrase}")
            response.raise_for_status()
            
        return response.text

    async def get_pr_files(self, repo: str, pr_number: int) -> List[Dict[str, Any]]:
        """
        Fetches the list of files changed in the PR.
        """
        logger.info(f"Fetching file list for PR #{pr_number} on: {repo}")
        url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}/files"
        response = await self._request_with_backoff("GET", url)
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch PR files: Status: {response.status_code} {response.reason_phrase}")
            response.raise_for_status()
            
        files = response.json()
        return [
            {
                "filename": f.get("filename", ""),
                "status": f.get("status", ""),
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "patch": f.get("patch", "")
            }
            for f in files
        ]

    async def get_pr_commits(self, repo: str, pr_number: int) -> List[Dict[str, Any]]:
        """
        Fetches all commits inside the PR.
        """
        logger.info(f"Fetching commit list for PR #{pr_number} on: {repo}")
        url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}/commits"
        response = await self._request_with_backoff("GET", url)
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch PR commits: Status: {response.status_code} {response.reason_phrase}")
            response.raise_for_status()
            
        commits = response.json()
        return [
            {
                "sha": c.get("sha", ""),
                "message": c.get("commit", {}).get("message", ""),
                "author": c.get("commit", {}).get("author", {}).get("name", "")
            }
            for c in commits
        ]

    async def push_changelog(self, path: str, content: str, commit_message: str, target_repo: str = None) -> Dict[str, Any]:
        """
        Pushes changelog.txt content to the configured separate changelog repository.
        Uses GET to get the existing file SHA if it exists, then updates or creates it.
        """
        repo = target_repo or settings.CHANGELOG_REPO
        logger.info(f"Pushing changelog to repository {repo} at path {path}")
        url = f"{self.base_url}/repos/{repo}/contents/{path}"
        
        # Check if file already exists to get its SHA
        sha = None
        response = await self._request_with_backoff("GET", url)
        if response.status_code == 200:
            sha = response.json().get("sha")
            logger.info(f"Existing file found with SHA: {sha}. Performing update.")
        elif response.status_code == 404:
            logger.info("Changelog file does not exist yet. Creating a new one.")
        else:
            logger.error(f"Error checking changelog existence: Status: {response.status_code} {response.reason_phrase}")
            response.raise_for_status()

        # Prepare payload
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        payload = {
            "message": commit_message,
            "content": encoded_content
        }
        if sha:
            payload["sha"] = sha

        # Push file content
        response = await self._request_with_backoff("PUT", url, json=payload)
        if response.status_code not in (200, 201):
            logger.error(f"Failed to push changelog: Status: {response.status_code} {response.reason_phrase}")
            response.raise_for_status()

        data = response.json()
        return {
            "sha": data.get("commit", {}).get("sha", ""),
            "html_url": data.get("content", {}).get("html_url", "")
        }
