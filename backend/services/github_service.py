import base64
import logging
import asyncio
import httpx
from typing import List, Dict, Any, Optional, Union
from backend.config import settings

logger = logging.getLogger("capsule.github_service")

class GitHubService:
    def __init__(self, token: Optional[str] = None):
        self.token = (token or settings.GITHUB_TOKEN or "").strip()
        self.headers = {
            "Accept": "application/vnd.github.v3+json"
        }
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"
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
            "html_url": data.get("html_url", ""),
            "merged_at": data.get("merged_at", "")
        }

    async def get_pr_diff(self, repo: str, pr_number: int) -> str:
        """
        Fetches the unified diff of the PR using headers for raw diff.
        """
        logger.info(f"Fetching raw diff for PR #{pr_number} on: {repo}")
        url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}"
        
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

    async def ensure_branch_exists(self, repo: str, branch: str = "changelog"):
        """
        Ensures that the specified branch exists in the target repository.
        If it doesn't exist, creates it from the default branch (e.g. main).
        """
        logger.info(f"Ensuring branch '{branch}' exists in repository '{repo}'...")
        url_get_ref = f"{self.base_url}/repos/{repo}/git/ref/heads/{branch}"
        
        response = await self._request_with_backoff("GET", url_get_ref)
        if response.status_code == 200:
            logger.info(f"Branch '{branch}' already exists in '{repo}'")
            return
            
        repo_url = f"{self.base_url}/repos/{repo}"
        res_repo = await self._request_with_backoff("GET", repo_url)
        default_branch = "main"
        if res_repo.status_code == 200:
            default_branch = res_repo.json().get("default_branch", "main")
            
        default_ref_url = f"{self.base_url}/repos/{repo}/git/ref/heads/{default_branch}"
        res_default = await self._request_with_backoff("GET", default_ref_url)
        if res_default.status_code != 200:
            logger.error(f"Failed to fetch default branch '{default_branch}' reference: {res_default.status_code}")
            return
            
        sha = res_default.json().get("object", {}).get("sha")
        if not sha:
            logger.error("Could not find commit SHA for default branch")
            return
            
        create_ref_url = f"{self.base_url}/repos/{repo}/git/refs"
        payload = {
            "ref": f"refs/heads/{branch}",
            "sha": sha
        }
        res_create = await self._request_with_backoff("POST", create_ref_url, json=payload)
        if res_create.status_code == 201:
            logger.info(f"Successfully created branch '{branch}' in '{repo}' from '{default_branch}'")
        elif res_create.status_code == 422:
            logger.info(f"Branch '{branch}' already exists (422 response)")
        else:
            logger.error(f"Failed to create branch '{branch}': {res_create.status_code} {res_create.text}")

    async def push_changelog(
        self,
        path: str,
        content: Union[str, bytes],
        commit_message: str,
        target_repo: str = None,
        branch: str = "changelog"
    ) -> Dict[str, Any]:
        """
        Pushes content (text or bytes) to the target repository at path on the specified branch.
        """
        repo = target_repo or settings.CHANGELOG_REPO
        logger.info(f"Pushing content to repository {repo} on branch {branch} at path {path}")
        
        await self.ensure_branch_exists(repo, branch)
        
        url = f"{self.base_url}/repos/{repo}/contents/{path}"
        url_get = f"{url}?ref={branch}"
        
        sha = None
        response = await self._request_with_backoff("GET", url_get)
        if response.status_code == 200:
            sha = response.json().get("sha")
            logger.info(f"Existing file found with SHA: {sha} on branch {branch}. Performing update.")
        elif response.status_code == 404:
            logger.info(f"File {path} does not exist yet on branch {branch}. Creating a new one.")
        else:
            logger.error(f"Error checking file existence on branch {branch}: Status: {response.status_code} {response.reason_phrase}")
            response.raise_for_status()

        if isinstance(content, bytes):
            encoded_content = base64.b64encode(content).decode("utf-8")
        else:
            encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            
        payload = {
            "message": commit_message,
            "content": encoded_content,
            "branch": branch
        }
        if sha:
            payload["sha"] = sha

        response = await self._request_with_backoff("PUT", url, json=payload)
        if response.status_code not in (200, 201):
            logger.error(f"Failed to push content: Status: {response.status_code} {response.reason_phrase}")
            response.raise_for_status()

        data = response.json()
        return {
            "sha": data.get("commit", {}).get("sha", ""),
            "html_url": data.get("content", {}).get("html_url", "")
        }

    async def commit_repair_patch(self, repo: str, branch: str, patch_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Commits multiple file changes back to a specific branch as an auto-repair.
        patch_data format:
        {
          "files": [
            {
              "path": "backend/api.py",
              "new_content": "import json\n..."
            }
          ],
          "message": "Auto-repair PR based on AI analysis"
        }
        """
        results = []
        message = patch_data.get("message", "Auto-repair by AI")
        files = patch_data.get("files", [])
        
        for file in files:
            path = file.get("path")
            content = file.get("new_content")
            if not path or content is None:
                continue
                
            logger.info(f"Applying repair to {path} on branch {branch}")
            try:
                res = await self.push_changelog(
                    path=path,
                    content=content,
                    commit_message=message,
                    target_repo=repo,
                    branch=branch
                )
                results.append(res)
            except Exception as e:
                logger.error(f"Failed to push repair to {path}: {e}")
                
        return {"status": "success", "files_updated": len(results), "results": results}

    async def create_repository_webhook(self, repo: str, callback_url: str) -> Dict[str, Any]:
        """
        Creates a GitHub webhook for pull_request events on the target repository.
        """
        url = f"{self.base_url}/repos/{repo}/hooks"
        payload = {
            "name": "web",
            "active": True,
            "events": ["pull_request"],
            "config": {
                "url": f"{callback_url.rstrip('/')}/webhooks/github",
                "content_type": "json",
                "secret": settings.GITHUB_WEBHOOK_SECRET or ""
            }
        }
        response = await self._request_with_backoff("POST", url, json=payload)
        if response.status_code == 201:
            logger.info(f"Successfully created pull_request webhook on repository {repo}")
            return {"status": "success", "details": response.json()}
        elif response.status_code == 422:
            logger.info(f"Webhook already exists on repository {repo}")
            return {"status": "already_exists", "details": "Webhook already configured"}
        else:
            logger.error(f"Failed to create webhook on {repo}: {response.status_code} {response.text}")
            response.raise_for_status()

    async def get_file_content(self, repo: str, path: str, branch: str = "main") -> Optional[str]:
        """Fetches the decoded content of a file from a specific branch."""
        url = f"{self.base_url}/repos/{repo}/contents/{path}?ref={branch}"
        response = await self._request_with_backoff("GET", url)
        if response.status_code == 200:
            data = response.json()
            content_b64 = data.get("content", "")
            if content_b64:
                return base64.b64decode(content_b64).decode('utf-8')
            return ""
        elif response.status_code == 404:
            return None
        else:
            response.raise_for_status()
            
    async def create_pull_request(self, repo: str, title: str, head: str, base: str, body: str) -> Dict[str, Any]:
        """Creates a pull request."""
        logger.info(f"Creating PR on {repo} from {head} to {base}")
        url = f"{self.base_url}/repos/{repo}/pulls"
        payload = {
            "title": title,
            "head": head,
            "base": base,
            "body": body
        }
        response = await self._request_with_backoff("POST", url, json=payload)
        if response.status_code == 201:
            return response.json()
        elif response.status_code == 422: # Might already exist
            logger.info(f"PR might already exist from {head} to {base} on {repo}. {response.text}")
            return {"status": "already_exists", "details": response.json()}
        else:
            logger.error(f"Failed to create PR: {response.status_code} {response.text}")
            response.raise_for_status()
