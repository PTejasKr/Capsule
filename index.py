import sys
import os

# Ensure the root directory (which contains the backend package) is in the path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Import the FastAPI app instance from backend.main
from backend.main import app
