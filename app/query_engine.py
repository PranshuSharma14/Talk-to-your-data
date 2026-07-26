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
    8. Return everything (answer + SQL + rows + assumptions + latency)

Why two LLM calls instead of one?
    One call: Question → LLM → "Rock made $850" (hallucinated number)
    Two calls: Question → LLM → SQL → Validate → Execute → Real data → LLM → "Rock, $826.65"
    The gap between calls is where validation + real data happens.

Phase 7: Added latency tracking for observability.
"""

import re
import time
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

CRITICAL RULES (follow these EXACTLY):

1. **ONLY SELECT queries**: Generate ONLY a single SELECT query. Never generate INSERT, UPDATE, DELETE, DROP, or any other statement.

2. **Use ONLY existing columns**: Use ONLY tables and columns that exist in the schema above. Do NOT invent columns.

3. **UNANSWERABLE detection**: If the question CANNOT be answered with available data, respond with EXACTLY:
   UNANSWERABLE: [clear reason why the data doesn't exist]
   
   Common unanswerable questions include:
   - Profit, cost, margins, expenses (we only have prices/totals, not costs)
   - Ratings, reviews, quality scores (not in schema)
   - Streaming counts, plays, downloads (not tracked)
   - Time-based data not in schema (e.g., "last month" when no date range exists)
   - Future predictions or forecasts
   - External data not in database

4. **AMBIGUITY handling**: If the question is AMBIGUOUS (multiple valid interpretations), you MUST:
   a) Generate the query using your most reasonable interpretation
   b) Add a SQL comment at the TOP explaining your assumption:
      -- ASSUMPTION: Interpreting "best" as "highest total spending" (could also mean most orders or most recent)
   
   Common ambiguous terms:
   - "best" → could mean highest revenue, most orders, most recent, highest rated
   - "popular" → could mean most sold, highest revenue, most artists
   - "top" → clarify the metric (revenue, quantity, duration)
   - "active" → define what makes someone active
   - "recent" → specify the time window

5. **Be specific in assumptions**: When stating assumptions, be explicit about:
   - What metric you chose (e.g., "total spending in dollars")
   - What you excluded or included (e.g., "all purchases, not just recent")
   - Any sorting or filtering decisions

6. **Technical requirements**:
   - Always use table aliases for readability in JOINs
   - Use appropriate aggregation (COUNT, SUM, AVG, MAX, MIN)
   - Return ONLY the SQL query (or UNANSWERABLE response)
   - No explanations, no markdown code blocks, no extra text

USER QUESTION: {question}

SQL:"""

ANSWER_GENERATION_PROMPT = """You are a helpful data analyst. Based on the question, SQL query, and actual database results below,
provide a clear, natural language answer.

QUESTION: {question}
SQL QUERY: {sql}
RESULTS: {rows}
{assumption_text}

CRITICAL RULES:

1. **Use ONLY actual data**: ONLY use the data provided in RESULTS. Do NOT make up, estimate, or infer any numbers not present.

2. **Empty results**: If the results are empty, say "No matching data was found in the database."

3. **Acknowledge assumptions FIRST**: If there was an ASSUMPTION made (shown above), you MUST:
   - State it clearly at the very beginning of your answer
   - Use language like: "Assuming X means Y, ..." or "Interpreting X as Y, ..."
   - Make it obvious you made an assumption
   - End with: "If you meant something else, please specify."

4. **Be concise but complete**:
   - Include specific numbers and names from the results
   - Format large numbers with commas (e.g., 1,234.56)
   - Use appropriate units (e.g., dollars, tracks, customers)

5. **Honesty over guessing**:
   - If results seem incomplete or unusual, state that
   - Don't extrapolate beyond what the data shows
   - Stick to what can be proven from the RESULTS

6. **Formatting**:
   - Do NOT include the SQL query in your answer (it's shown separately)
   - Use clear, conversational language
   - For single numbers, state them directly
   - For lists, present them naturally

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

    def process_question(self, question: str, preview_mode: bool = False) -> dict:
        """
        Process a natural language question through the full pipeline.

        Args:
            question: The user's natural language question
            preview_mode: If True, only generate and validate SQL without execution (Phase 7)

        Returns:
            dict with: answer, sql, rows, row_count, assumptions, error, latency_ms
        """
        start_time = time.time()
        latency_breakdown = {}
        
        try:
            # Step 1: Get the schema
            schema_start = time.time()
            schema = self._get_schema()
            latency_breakdown['schema_load_ms'] = int((time.time() - schema_start) * 1000)

            # Step 2: LLM Call #1 — Generate SQL from question + schema
            llm1_start = time.time()
            sql_prompt = SQL_GENERATION_PROMPT.format(
                schema=schema, question=question
            )
            llm_response = call_llm(sql_prompt, temperature=0.0)
            latency_breakdown['llm_sql_generation_ms'] = int((time.time() - llm1_start) * 1000)

            # Step 3: Check if UNANSWERABLE
            if self._is_unanswerable(llm_response):
                reason = self._extract_unanswerable_reason(llm_response)
                total_ms = int((time.time() - start_time) * 1000)
                return {
                    "answer": f"This question cannot be answered with the available data. {reason}",
                    "sql": None,
                    "rows": None,
                    "row_count": None,
                    "assumptions": None,
                    "error": None,
                    "latency_ms": total_ms,
                    "latency_breakdown": latency_breakdown,
                    "preview_only": preview_mode,
                }

            # Step 4: Extract SQL and any assumptions
            sql = self._clean_sql(llm_response)
            assumptions = self._extract_assumptions(llm_response)

            # Step 5: Validate the SQL (4-layer safety pipeline)
            validation_start = time.time()
            validation = validate_sql(sql)
            latency_breakdown['sql_validation_ms'] = int((time.time() - validation_start) * 1000)
            
            if not validation["valid"]:
                total_ms = int((time.time() - start_time) * 1000)
                return {
                    "answer": f"The generated query was blocked by safety validation: {validation['error']}",
                    "sql": sql,
                    "rows": None,
                    "row_count": None,
                    "assumptions": assumptions,
                    "error": validation["error"],
                    "latency_ms": total_ms,
                    "latency_breakdown": latency_breakdown,
                    "preview_only": preview_mode,
                }

            # Use the (possibly modified) SQL from validator (may have LIMIT added)
            safe_sql = validation["sql"]

            # Phase 7: Preview mode - return SQL without execution
            if preview_mode:
                total_ms = int((time.time() - start_time) * 1000)
                preview_answer = f"Preview: Here's the SQL that would be executed to answer your question."
                if assumptions:
                    preview_answer = f"Preview (assuming {assumptions}): Here's the SQL that would be executed."
                
                return {
                    "answer": preview_answer,
                    "sql": safe_sql,
                    "rows": None,
                    "row_count": None,
                    "assumptions": assumptions,
                    "error": None,
                    "latency_ms": total_ms,
                    "latency_breakdown": latency_breakdown,
                    "preview_only": True,
                }

            # Step 6: Execute on read-only database
            db_start = time.time()
            try:
                result = self.db.execute_query(safe_sql)
                latency_breakdown['database_execution_ms'] = int((time.time() - db_start) * 1000)
            except Exception as e:
                latency_breakdown['database_execution_ms'] = int((time.time() - db_start) * 1000)
                total_ms = int((time.time() - start_time) * 1000)
                return {
                    "answer": f"The SQL query failed to execute: {str(e)}",
                    "sql": safe_sql,
                    "rows": None,
                    "row_count": None,
                    "assumptions": assumptions,
                    "error": str(e),
                    "latency_ms": total_ms,
                    "latency_breakdown": latency_breakdown,
                    "preview_only": preview_mode,
                }

            # Step 7: LLM Call #2 — Generate English answer from real data
            llm2_start = time.time()
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
            latency_breakdown['llm_answer_generation_ms'] = int((time.time() - llm2_start) * 1000)

            # Step 8: Return everything
            total_ms = int((time.time() - start_time) * 1000)
            return {
                "answer": answer,
                "sql": safe_sql,
                "rows": result["rows"],
                "row_count": result["row_count"],
                "assumptions": assumptions,
                "error": None,
                "latency_ms": total_ms,
                "latency_breakdown": latency_breakdown,
                "preview_only": preview_mode,
            }

        except Exception as e:
            total_ms = int((time.time() - start_time) * 1000)
            return {
                "answer": f"An unexpected error occurred: {str(e)}",
                "sql": None,
                "rows": None,
                "row_count": None,
                "assumptions": None,
                "error": str(e),
                "latency_ms": total_ms,
                "latency_breakdown": latency_breakdown if 'latency_breakdown' in locals() else {},
                "preview_only": preview_mode,
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
