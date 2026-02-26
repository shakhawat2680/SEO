from fastapi import FastAPI
from mangum import Mangum
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

# Import your app
from app import app

# Create handler for Vercel
handler = Mangum(app)

# This is for Vercel
def handler(event, context):
    return Mangum(app)(event, context)
