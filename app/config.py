"""
config.py — Loads environment variables from .env file.

Why this file exists:
- Keeps the Gemini API key out of source code
- Single place to manage all configuration
- .env file is gitignored so secrets never get committed
"""

import os
from dotenv import load_dotenv

# Load variables from .env file into os.environ
load_dotenv()

# Gemini API key — used in llm.py (Phase 3)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Database path — relative to project root
DATABASE_PATH = os.getenv("DATABASE_PATH", "chinook.db")
