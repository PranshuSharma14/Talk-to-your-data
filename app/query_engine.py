"""
query_engine.py -- The core pipeline that orchestrates everything.

This is THE BRAIN of the entire system. It connects:
    - Database layer (Phase 1) for schema and query execution
    - SQL Validator (Phase 2) for safety checks
    - LLM (this phase) for SQL generation and answer generation

The pipeline:
    1. Load database schema + sample rows
    2. LLM Call #1: question + schema → SQL (or UNANSWERABLE)
    3. Check if LLM said UNANSWERABLE → return decline
    4. Extract any ASSUMPTION comments (ambiguity handling)
    5. Validate the SQL through 4-layer safety pipeline
    6. Execute on read-only database
    7. LLM Call #2: question + SQL + actual rows → English answer
    8. Return everything (answer + SQL + rows + assumptions)

Why two LLM calls instead of one?
    One call: Question → LLM → "Rock made $850" (hallucinated number)
    Two calls: Question → LLM → SQL → Validate → Execute → Real data → LLM → "Rock, $826.65"
    The gap between calls is where validation + real data happens.
"""

import re
from app.database import Database
from app.sql_validator import validate_sql
from app.llm import call_llm


# ─────────────────────────────────────────────
# PROMPT TEMPLATES
# ─────────────────────────────────────────────

SQL_GENERATION_PROMPT = """You are a SQL expert. Given a user's question and the database schema below,
generate a SQLite-compatible SELECT query to answer the question.

DATABASE SCHEMA:
{schema}

RULES (follow these EXACTLY):
1. Generate ONLY a single SELECT query. Never generate INSERT, UPDATE, DELETE, DROP, or any other statement.
2. Use ONLY tables and columns that exist in the schema above. Do NOT invent columns.
3. If the question CANNOT be answered with the available data (e.g., asks about profit, cost, ratings, or data that doesn't exist in any table), respond with EXACTLY:
   UNANSWERABLE: [brief reason why the data doesn't exist]
4. If the question is AMBIGUOUS (e.g., "best customer" could mean highest spending or most orders), generate the query using your best interpretation BUT add a SQL comment explaining your assumption:
   -- ASSUMPTION: [what you assumed and why or ask user to clearly describe]
5. Always use table aliases for readability in JOINs.
6. Use appropriate aggregation (COUNT, SUM, AVG) when the question implies it.
7. Return ONLY the SQL query (or UNANSWERABLE response). No explanations, no markdown, no code blocks.

USER QUESTION: {question}

SQL:"""

ANSWER_GENERATION_PROMPT = """You are a helpful data analyst. Based on the question, SQL query, and actual database results below,
provide a clear, natural language answer.

QUESTION: {question}
SQL QUERY: {sql}
RESULTS: {rows}
{assumption_text}

RULES:
1. ONLY use the data provided in RESULTS. Do NOT make up or estimate any numbers.
2. If the results are empty, say "No matching data was found."
3. Be concise but complete. Include specific numbers and names from the results.
4. If there was an ASSUMPTION made, clearly state it at the beginning of your answer.
5. Format large numbers with commas for readability (e.g., 1,234.56).
6. Do NOT include the SQL query in your answer — it's shown separately.

ANSWER:"""


class QueryEngine:
    """Orchestrates the full question-answering pipeline."""

    def __init__(self):
        """Initialize with a Database instance."""
        self.db = Database()
        # Cache the schema since it doesn't change
        self._schema = None

    def _get_schema(self) -> str:
        """Get database schema (cached after first call)."""
        if self._schema is None:
            self._schema = self.db.get_schema()
        return self._schema

    def process_question(self, question: str) -> dict:
        """
        Process a natural language question through the full pipeline.

        Args:
            question: The user's natural language question

        Returns:
            dict with: answer, sql, rows, row_count, assumptions, error
        """
        try:
            # Step 1: Get the schema
            schema = self._get_schema()

            # Step 2: LLM Call #1 — Generate SQL from question + schema
            sql_prompt = SQL_GENERATION_PROMPT.format(
                schema=schema, question=question
            )
            llm_response = call_llm(sql_prompt, temperature=0.0)

            # Step 3: Check if UNANSWERABLE
            if self._is_unanswerable(llm_response):
                reason = self._extract_unanswerable_reason(llm_response)
                return {
                    "answer": f"This question cannot be answered with the available data. {reason}",
                    "sql": None,
                    "rows": None,
                    "row_count": None,
                    "assumptions": None,
                    "error": None,
                }

            # Step 4: Extract SQL and any assumptions
            sql = self._clean_sql(llm_response)
            assumptions = self._extract_assumptions(llm_response)

            # Step 5: Validate the SQL (4-layer safety pipeline)
            validation = validate_sql(sql)
            if not validation["valid"]:
                return {
                    "answer": f"The generated query was blocked by safety validation: {validation['error']}",
                    "sql": sql,
                    "rows": None,
                    "row_count": None,
                    "assumptions": assumptions,
                    "error": validation["error"],
                }

            # Use the (possibly modified) SQL from validator (may have LIMIT added)
            safe_sql = validation["sql"]

            # Step 6: Execute on read-only database
            try:
                result = self.db.execute_query(safe_sql)
            except Exception as e:
                return {
                    "answer": f"The SQL query failed to execute: {str(e)}",
                    "sql": safe_sql,
                    "rows": None,
                    "row_count": None,
                    "assumptions": assumptions,
                    "error": str(e),
                }

            # Step 7: LLM Call #2 — Generate English answer from real data
            assumption_text = (
                f"ASSUMPTION MADE: {assumptions}" if assumptions else ""
            )
            answer_prompt = ANSWER_GENERATION_PROMPT.format(
                question=question,
                sql=safe_sql,
                rows=result["rows"],
                assumption_text=assumption_text,
            )
            answer = call_llm(answer_prompt, temperature=0.3)

            # Step 8: Return everything
            return {
                "answer": answer,
                "sql": safe_sql,
                "rows": result["rows"],
                "row_count": result["row_count"],
                "assumptions": assumptions,
                "error": None,
            }

        except Exception as e:
            return {
                "answer": f"An unexpected error occurred: {str(e)}",
                "sql": None,
                "rows": None,
                "row_count": None,
                "assumptions": None,
                "error": str(e),
            }

    # ─────────────────────────────────────────────
    # HELPER METHODS
    # ─────────────────────────────────────────────

    def _is_unanswerable(self, response: str) -> bool:
        """Check if the LLM said the question is unanswerable."""
        return response.strip().upper().startswith("UNANSWERABLE")

    def _extract_unanswerable_reason(self, response: str) -> str:
        """Extract the reason from 'UNANSWERABLE: reason'."""
        if ":" in response:
            return response.split(":", 1)[1].strip()
        return "The required data does not exist in the database."

    def _clean_sql(self, response: str) -> str:
        """
        Clean the LLM response to extract just the SQL query.

        The LLM might wrap it in markdown code blocks or add extra text.
        This handles all those cases.
        """
        sql = response.strip()

        # Remove markdown code blocks if present: ```sql ... ```
        if sql.startswith("```"):
            # Remove opening ``` (with optional language tag)
            sql = re.sub(r"^```\w*\n?", "", sql)
            # Remove closing ```
            sql = re.sub(r"\n?```$", "", sql)
            sql = sql.strip()

        return sql

    def _extract_assumptions(self, response: str) -> str | None:
        """
        Extract ASSUMPTION comments from the SQL.

        The LLM adds comments like: -- ASSUMPTION: best = highest spending
        We extract these to show the user what was assumed.
        """
        assumptions = []
        for line in response.split("\n"):
            line = line.strip()
            if "-- ASSUMPTION:" in line.upper() or "-- ASSUMPTION:" in line:
                # Extract everything after "-- ASSUMPTION:"
                match = re.search(r"--\s*ASSUMPTION:\s*(.*)", line, re.IGNORECASE)
                if match:
                    assumptions.append(match.group(1).strip())

        return "; ".join(assumptions) if assumptions else None
