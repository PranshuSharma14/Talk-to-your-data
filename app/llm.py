"""
llm.py -- Gemini API wrapper.

Handles all communication with Google's Gemini API.
Keeps LLM configuration in one place so it's easy to swap models,
adjust temperature, or switch providers later.

Why Gemini?
    - Free tier: 15 requests/minute, 1500 requests/day
    - Gemini Flash is fast and good enough for SQL generation
    - The assignment doesn't require a specific LLM
"""

from google import genai
from app.config import GEMINI_API_KEY


# Configure the client once at module level
client = genai.Client(api_key=GEMINI_API_KEY)

# Model to use — change this if you want a different model
MODEL_NAME = "gemini-3.5-flash"


def call_llm(prompt: str, temperature: float = 0.0) -> str:
    """
    Send a prompt to Gemini and return the text response.

    Args:
        prompt: The full prompt string (system instructions + user question + schema)
        temperature: Controls randomness.
            0.0 = deterministic (best for SQL generation — same question = same SQL)
            0.3 = slightly creative (good for natural language answers)

    Returns:
        str: The LLM's text response, stripped of whitespace

    Raises:
        Exception: If the API call fails (rate limit, invalid key, etc.)
    """
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config={
            "temperature": temperature,
        },
    )

    return response.text.strip()
