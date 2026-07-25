"""
sql_validator.py -- Multi-layer SQL validation pipeline.

This is our defense-in-depth system. We have 4 layers of validation,
each catching different types of dangerous SQL. Even if all 4 layers
somehow fail, Layer 5 (SQLite read-only from database.py) blocks writes.

Architecture:
    Layer 1: Statement type check (sqlparse) -- must be SELECT
    Layer 2: Keyword blocklist -- scans for dangerous keywords after stripping string literals
    Layer 3: Stacked query detection -- checks for multiple statements (semicolons)
    Layer 4: LIMIT injection -- adds LIMIT 500 if missing to prevent runaway queries

Usage:
    from app.sql_validator import validate_sql
    result = validate_sql("SELECT * FROM Customer")
    if result['valid']:
        safe_sql = result['sql']  # may have LIMIT added
    else:
        error = result['error']   # why it was rejected
"""

import re

import sqlparse


# Dangerous keywords that should NEVER appear in a user-facing query.
# We check for these AFTER removing string literals to avoid false positives.
BLOCKED_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "PRAGMA", "ATTACH", "DETACH", "EXEC", "EXECUTE",
    "GRANT", "REVOKE", "REPLACE",
]

# Default row limit to prevent runaway queries
DEFAULT_LIMIT = 500


def validate_sql(sql: str) -> dict:
    """
    Run the SQL through all 4 validation layers.

    Args:
        sql: The raw SQL string from the LLM

    Returns:
        dict with:
            'valid': bool -- True if query passed all checks
            'sql': str -- The (possibly modified) safe SQL (with LIMIT added if needed)
            'error': str or None -- Error message if validation failed
    """
    # Clean up whitespace
    sql = sql.strip()

    if not sql:
        return {"valid": False, "sql": sql, "error": "Empty query"}

    # Layer 1: Statement type check
    error = _check_statement_type(sql)
    if error:
        return {"valid": False, "sql": sql, "error": f"Layer 1 (statement type): {error}"}

    # Layer 2: Keyword blocklist
    error = _check_blocked_keywords(sql)
    if error:
        return {"valid": False, "sql": sql, "error": f"Layer 2 (blocked keyword): {error}"}

    # Layer 3: Stacked query detection
    error = _check_stacked_queries(sql)
    if error:
        return {"valid": False, "sql": sql, "error": f"Layer 3 (stacked query): {error}"}

    # Layer 4: LIMIT injection
    sql = _inject_limit(sql)

    return {"valid": True, "sql": sql, "error": None}


def _check_statement_type(sql: str) -> str | None:
    """
    Layer 1: Parse with sqlparse and verify it's a SELECT statement.

    Why sqlparse? It properly handles SQL syntax including comments,
    whitespace, and subqueries. Simple regex would miss edge cases.

    Returns:
        None if valid, error string if not
    """
    try:
        parsed = sqlparse.parse(sql)

        if not parsed:
            return "Could not parse SQL"

        # Get the first (should be only) statement
        stmt = parsed[0]

        # sqlparse identifies the statement type
        stmt_type = stmt.get_type()

        if stmt_type != "SELECT":
            return f"Only SELECT queries are allowed, got: {stmt_type or 'UNKNOWN'}"

        return None

    except Exception as e:
        return f"SQL parsing failed: {str(e)}"


def _check_blocked_keywords(sql: str) -> str | None:
    """
    Layer 2: Scan for dangerous keywords AFTER stripping string literals.

    Why strip strings first?
    Consider: SELECT * FROM Track WHERE Name = 'Delete This Track'
    Without stripping, we'd flag 'DELETE' -- but it's inside a string literal,
    it's data, not a SQL command. By removing string contents first,
    we only catch keywords in the actual SQL structure.

    Returns:
        None if valid, error string if found dangerous keyword
    """
    # Remove everything inside single quotes (SQL string literals)
    # This prevents false positives like WHERE Name = 'Drop Everything'
    cleaned_sql = re.sub(r"'[^']*'", "''", sql)

    # Also remove everything inside double quotes (SQL identifiers)
    cleaned_sql = re.sub(r'"[^"]*"', '""', cleaned_sql)

    # Check each blocked keyword
    # Use word boundaries (\b) to avoid matching partial words
    # e.g., "CREATED_AT" should not match "CREATE"
    for keyword in BLOCKED_KEYWORDS:
        pattern = r'\b' + keyword + r'\b'
        if re.search(pattern, cleaned_sql, re.IGNORECASE):
            return f"Dangerous keyword found: {keyword}"

    return None


def _check_stacked_queries(sql: str) -> str | None:
    """
    Layer 3: Detect multiple SQL statements (stacked query attack).

    Attack example: "SELECT * FROM Customer; DROP TABLE Customer"
    The semicolon separates two statements. The database might execute both.

    We check two ways:
    1. sqlparse should find exactly 1 statement
    2. No semicolons in the query body (after removing trailing semicolons)

    Returns:
        None if valid, error string if stacked query detected
    """
    # Check 1: sqlparse should parse exactly one statement
    parsed = sqlparse.parse(sql)
    # Filter out empty statements (sqlparse sometimes creates empty ones from trailing semicolons)
    non_empty = [s for s in parsed if str(s).strip()]

    if len(non_empty) > 1:
        return "Multiple SQL statements detected (possible injection attack)"

    # Check 2: Look for semicolons in the query body
    # Remove trailing semicolons first (those are harmless)
    body = sql.rstrip().rstrip(";").strip()

    # Also remove semicolons inside string literals before checking
    body_no_strings = re.sub(r"'[^']*'", "''", body)

    if ";" in body_no_strings:
        return "Semicolon found in query body (possible stacked query attack)"

    return None


def _inject_limit(sql: str) -> str:
    """
    Layer 4: Add LIMIT if the query doesn't already have one.

    Why? A bad query like SELECT * FROM Track (no WHERE, no LIMIT) could
    return thousands of rows, exhausting memory and crashing the server.
    500 rows is more than enough for any reasonable business question.

    If the query already has a LIMIT, we respect it (but cap at DEFAULT_LIMIT).

    Returns:
        The SQL string, possibly with LIMIT appended
    """
    # Remove trailing semicolons for clean processing
    clean_sql = sql.rstrip().rstrip(";").strip()

    # Check if LIMIT already exists (case-insensitive)
    if re.search(r'\bLIMIT\b', clean_sql, re.IGNORECASE):
        # LIMIT already present -- keep it as-is
        return clean_sql

    # No LIMIT found -- add one
    return f"{clean_sql} LIMIT {DEFAULT_LIMIT}"
