"""
models.py -- Pydantic models for request/response validation.

Why Pydantic?
    - FastAPI uses it natively for request body parsing
    - Automatic validation (if someone sends bad JSON, they get a clear error)
    - Auto-generates API docs with field descriptions
"""

from pydantic import BaseModel, Field


class QuestionRequest(BaseModel):
    """The incoming request body for POST /ask."""

    question: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="The natural language question to ask about the database",
        examples=["How many customers are there?"],
    )
    preview_mode: bool = Field(
        default=False,
        description="If true, only generate SQL without executing (Phase 7 feature)",
    )


class AnswerResponse(BaseModel):
    """The response body returned to the user."""

    answer: str = Field(
        description="Natural language answer to the question"
    )
    sql: str | None = Field(
        default=None,
        description="The SQL query that was generated and executed (None if unanswerable)",
    )
    rows: list | None = Field(
        default=None,
        description="Raw result rows from the database (None if unanswerable)",
    )
    row_count: int | None = Field(
        default=None,
        description="Number of rows returned",
    )
    assumptions: str | None = Field(
        default=None,
        description="Any assumptions made for ambiguous questions (None if unambiguous)",
    )
    error: str | None = Field(
        default=None,
        description="Error message if something went wrong (None if successful)",
    )
    latency_ms: int | None = Field(
        default=None,
        description="Total request latency in milliseconds (Phase 7 feature)",
    )
    latency_breakdown: dict | None = Field(
        default=None,
        description="Detailed latency breakdown by operation (Phase 7 feature)",
    )
    preview_only: bool = Field(
        default=False,
        description="True if this was a preview-only request (Phase 7 feature)",
    )
