import sys
import os
import asyncio

# Force standard asyncio event loop policy on Vercel to bypass uvloop bugs
# (uvloop create_connection throws OSError Errno 99 on SSL PostgreSQL in AWS Lambda/Vercel)
try:
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
except Exception:
    pass

# Ensure the root directory (which contains the backend package) is in the path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Import the FastAPI app instance from backend.main
from backend.main import app
