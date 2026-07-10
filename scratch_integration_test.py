import asyncio
import httpx
import subprocess
import time
import json
import sqlite3
import os

async def main():
    db_path = r"c:\Users\punya\Desktop\capsule\capsule.db"
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM profiles LIMIT 1")
    profile = cur.fetchone()
    if not profile:
        print("No profiles in DB.")
        return
        
    print(f"Using profile {profile[1]} (ID {profile[0]})")
    
    repo = "PTejasKr/OS-Tracker"
    cur.execute("SELECT id FROM repository_mappings WHERE source_repo = ?", (repo,))
    if not cur.fetchone():
        cur.execute("INSERT INTO repository_mappings (source_repo, profile_id) VALUES (?, ?)", (repo, profile[0]))
        conn.commit()
    conn.close()

    print("Starting backend server...")
    proc = subprocess.Popen(
        ["python", "-m", "uvicorn", "backend.main:app", "--port", "8089"],
        cwd=r"c:\Users\punya\Desktop\capsule",
        env={**os.environ, "PYTHONPATH": r"c:\Users\punya\Desktop\capsule"}
    )
    
    time.sleep(4) # Wait for server to start
    
    print("Sending webhook payload...")
    payload = {
        "action": "closed",
        "pull_request": {
            "number": 999,
            "title": "Mock E2E PR",
            "body": "Testing Capsule's E2E PR analysis.",
            "merged": True,
            "head": {"ref": "mock-feature"},
            "base": {"ref": "main"}
        },
        "repository": {
            "full_name": repo
        }
    }
    
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                "http://localhost:8089/api/webhook/github",
                json=payload,
                headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=bypass"}
            )
            print(f"Response status: {res.status_code}")
            print(f"Response body: {res.text}")
            
            print("\nSending via Jenkins webhook to force synchronous execution...")
            res2 = await client.post(
                "http://localhost:8089/api/jenkins",
                json={"repo": repo, "pr_number": 999},
                headers={"Authorization": "Bearer TEST_KEY"} # Needs API key
            )
            print(f"Jenkins Response status: {res2.status_code}")
            print(f"Jenkins Response body: {res2.text}")
            
        except Exception as e:
            print(f"Error: {e}")
            
    print("Stopping backend server...")
    proc.terminate()
    proc.wait()

if __name__ == "__main__":
    asyncio.run(main())
