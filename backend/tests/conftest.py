import sys
import os

# Set testing flag before importing any app modules
os.environ["TESTING"] = "true"

# Ensure the backend package root is on PYTHONPATH when running tests from backend/tests
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

