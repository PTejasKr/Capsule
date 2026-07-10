import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.database import init_db, execute_query
from backend.services.changelog_service import ChangelogService
from backend.services.github_service import GitHubService
from backend.routers.api import get_pr_summary, _reconstruct_summary_from_row

async def main():
    await init_db()
    
    github_service = GitHubService()
    changelog_service = ChangelogService(github_service)
    
    try:
        from backend.database import fetch_one
        pr_row = await fetch_one("SELECT * FROM pr_analyses LIMIT 1")
        if not pr_row:
            print("No PR analysis found in DB.")
            return
        
        pr_number = pr_row["pr_number"]
        repo = pr_row["repo"]
            
        pr_summary = await _reconstruct_summary_from_row(pr_row)
        files_metadata = await github_service.get_pr_files(repo, pr_number)
        
        print(f"Generating changelog for PR {pr_number} in {repo}...")
        entry = await changelog_service.generate_changelog(pr_summary, files_metadata)
        
        print("Pushing changelog...")
        push_res = await changelog_service.push_changelog(entry, repo)
        print("Success:", push_res)
    except Exception as e:
        print("Error:", e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
