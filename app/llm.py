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

import time
import google.generativeai as genai
from app.config import GEMINI_API_KEY


# Configure the API key
genai.configure(api_key=GEMINI_API_KEY)

# Model to use - using the stable google-generativeai package
MODEL_NAME = "gemini-3.5-flash"


def call_llm(prompt: str, temperature: float = 0.0, max_retries: int = 3) -> str:
    """
    Send a prompt to Gemini and return the text response.
    Includes retry logic with exponential backoff for rate limit errors.

    Args:
        prompt: The full prompt string (system instructions + user question + schema)
        temperature: Controls randomness.
            0.0 = deterministic (best for SQL generation — same question = same SQL)
            0.3 = slightly creative (good for natural language answers)
        max_retries: Maximum number of retry attempts for rate limit errors

    Returns:
        str: The LLM's text response, stripped of whitespace

    Raises:
        Exception: If the API call fails after all retries
    """
    model = genai.GenerativeModel(MODEL_NAME)
    
    for attempt in range(max_retries):
        try:
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=temperature,
                ),
            )
            return response.text.strip()
            
        except Exception as e:
            error_str = str(e)
            
            # Check if it's a rate limit error
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
                if attempt < max_retries - 1:
                    # Exponential backoff: 10s, 20s, 40s
                    wait_time = 10 * (2 ** attempt)
                    print(f"    ⚠️  Rate limit hit, waiting {wait_time}s before retry {attempt + 2}/{max_retries}...")
                    time.sleep(wait_time)
                    continue
                else:
                    # Max retries reached
                    print(f"    ❌ Rate limit exceeded after {max_retries} retries")
                    raise Exception(f"RATE_LIMIT_EXCEEDED: {error_str}")
            else:
                # Not a rate limit error, raise immediately
                print(f"    ❌ API Error: {error_str[:200]}")
                raise
    
    # Should never reach here, but just in case
    raise Exception("Unexpected error in call_llm after retries")
