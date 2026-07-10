import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.database import init_db, execute_query

async def main():
    await init_db()
    
    await execute_query("DELETE FROM pr_analyses WHERE repo = 'mock-owner/mock-repo'")
    print("Mock PRs deleted.")

if __name__ == "__main__":
    asyncio.run(main())
