"""
main.py -- FastAPI application with /ask endpoint and static file serving.

This is the entry point of the application. It:
1. Exposes POST /ask endpoint that accepts a question and returns the answer
2. Serves the chat UI from static/index.html
3. Configures CORS for cross-origin requests
4. Auto-generates Swagger docs at /docs

Run with: uvicorn app.main:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.models import QuestionRequest, AnswerResponse
from app.query_engine import QueryEngine

# Initialize FastAPI app
app = FastAPI(
    title="Talk to Your Data",
    description="A conversational analytics service that lets you ask questions about a database in plain English.",
    version="1.0.0",
)

# CORS — allow all origins for development (tighten in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the query engine (loads schema once)
engine = QueryEngine()

# Mount static files (CSS, JS, images)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def root():
    """Serve the chat UI."""
    return FileResponse("app/static/index.html")


@app.post("/ask", response_model=AnswerResponse)
async def ask_question(request: QuestionRequest):
    """
    Ask a question about the database in plain English.

    The system will:
    1. Generate SQL from your question using Gemini
    2. Validate the SQL for safety (4-layer defense)
    3. Execute it on the read-only database (unless preview_mode=True)
    4. Generate a natural language answer from the real data

    Phase 7: Supports preview_mode to only generate SQL without execution.

    Returns the answer, the SQL query, and the raw result rows.
    """
    try:
        result = engine.process_question(request.question, preview_mode=request.preview_mode)
        return AnswerResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "talk-to-your-data"}
