import asyncio
import httpx
import time

async def trigger_pr(pr_number: int):
    repo = "PTejasKr/OS-Tracker"
    print(f"Triggering analysis for PR #{pr_number}...")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            res = await client.post(
                "http://localhost:8089/api/webhooks/jenkins",
                json={"repo": repo, "pr_number": pr_number},
                headers={"X-API-Key": "dev-bypass"}
            )
            print(f"PR #{pr_number} - Status: {res.status_code}")
            if res.status_code == 200:
                print(f"PR #{pr_number} - Success. Summary length: {len(res.text)}")
            else:
                print(f"PR #{pr_number} - Error: {res.text}")
        except Exception as e:
            print(f"PR #{pr_number} - Request failed: {e}")

async def main():
    time.sleep(2)
    
    prs = [6, 7, 8, 9, 10]
    for pr in prs:
        await trigger_pr(pr)

if __name__ == "__main__":
    asyncio.run(main())
