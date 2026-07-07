import asyncio
import json
import httpx
from backend.database import fetch_one

async def run_test():
    repo = "PTejasKr/OS-Tracker"
    
    # Check if we have a profile mapping
    profile = await fetch_one("SELECT * FROM profiles LIMIT 1")
    if not profile:
        print("No profile found. Please create one.")
        return
        
    print(f"Using profile: {profile['name']} for mock test.")
    
    payload = {
        "action": "closed",
        "pull_request": {
            "number": 999,
            "title": "Mock PR for End-to-End Test",
            "body": "This is a mock PR to test the end-to-end functionality of Capsule.",
            "merged": True,
            "head": {"ref": "feature/mock-test"},
            "base": {"ref": "main"}
        },
        "repository": {
            "full_name": repo
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": "sha256=MOCK_SIGNATURE" # Webhook signature verify might need to be bypassed for mock
    }
    
    # We will invoke the webhooks service function directly to bypass signature verification
    from backend.routers.webhooks import process_pull_request_event
    print("Triggering PR processing...")
    try:
        await process_pull_request_event(payload)
        print("Processing complete!")
        
        # Verify in DB
        res = await fetch_one("SELECT * FROM pr_analyses WHERE repo = ? AND pr_number = ?", (repo, 999))
        if res:
            print("SUCCESS: PR Analysis found in database!")
            print(f"Summary: {res['summary'][:100]}...")
        else:
            print("FAILURE: PR Analysis not found in database.")
    except Exception as e:
        print(f"Error during processing: {e}")

if __name__ == "__main__":
    asyncio.run(run_test())
