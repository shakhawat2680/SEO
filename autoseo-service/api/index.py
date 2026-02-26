"""
Vercel serverless entry point
"""
import sys
import os
from pathlib import Path

# Add parent directory to path so imports work
sys.path.append(str(Path(__file__).parent.parent))

# Import the FastAPI app
from app import app

# Import mangum for ASGI wrapper
try:
    from mangum import Mangum
    # Create handler for Vercel
    handler = Mangum(app)
except ImportError:
    # Fallback for local development
    def handler(event, context):
        return {
            "statusCode": 500,
            "body": "Mangum not installed"
        }
