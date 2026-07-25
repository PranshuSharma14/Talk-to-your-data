"""
database.py — Database connection, schema extraction, and query execution.

This is the foundation of the entire system. Three key responsibilities:
1. Connect to SQLite in READ-ONLY mode (our strongest safety guarantee)
2. Extract the full schema + sample rows (so the LLM knows the database structure)
3. Execute validated SQL queries and return results

Security note:
    The connection uses `file:chinook.db?mode=ro` (URI-based read-only mode).
    This means SQLite itself refuses ANY write operation at the engine level.
    Even if our SQL validator somehow misses a DELETE/DROP query,
    SQLite will throw: "attempt to write a readonly database"
    This is Layer 5 (the final guarantee) in our defense-in-depth strategy.
"""

import sqlite3
import os
from app.config import DATABASE_PATH


class Database:
    """Handles all database interactions with read-only safety."""

    def __init__(self, db_path: str = None):
        """
        Initialize with the path to the SQLite database file.

        Args:
            db_path: Path to the .db file. Defaults to DATABASE_PATH from config.
        """
        self.db_path = db_path or DATABASE_PATH

        # Verify the database file exists before trying to connect
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(
                f"Database file not found: {self.db_path}\n"
                f"Please place the Chinook database as '{self.db_path}' in the project root."
            )

    def _get_connection(self) -> sqlite3.Connection:
        """
        Create a new READ-ONLY connection to the database.

        Uses SQLite URI mode with ?mode=ro to enforce read-only at the engine level.
        This is our strongest safety guarantee — even if all validation layers fail,
        SQLite itself will refuse to execute any write operation.

        Returns:
            sqlite3.Connection in read-only mode
        """
        # Convert to absolute path for URI format
        abs_path = os.path.abspath(self.db_path)

        # URI format: file:/path/to/db?mode=ro
        # mode=ro = read-only (SQLite enforced, cannot be bypassed by SQL tricks)
        uri = f"file:{abs_path}?mode=ro"

        conn = sqlite3.connect(uri, uri=True)

        # Return rows as tuples (default behavior, keeping it explicit)
        conn.row_factory = None

        return conn

    def get_schema(self) -> str:
        """
        Extract the full database schema with sample rows.

        This is what we send to the LLM so it knows:
        1. Exact table and column names (prevents hallucinated column names)
        2. Foreign key relationships (so it knows how to JOIN)
        3. Actual data values via sample rows (so it uses 'USA' not 'United States')

        Returns:
            str: Full schema text with CREATE TABLE statements + 3 sample rows per table
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Get all CREATE TABLE statements from sqlite_master
        # sqlite_master is SQLite's internal metadata table
        cursor.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = cursor.fetchall()

        schema_parts = []

        for table_name, create_sql in tables:
            # Add the CREATE TABLE statement
            schema_parts.append(create_sql + ";")

            # Add 3 sample rows so the LLM can see actual data formats
            # Why 3? Enough to show variety, not so many that we waste tokens
            try:
                cursor.execute(f"SELECT * FROM [{table_name}] LIMIT 3")
                sample_rows = cursor.fetchall()

                if sample_rows:
                    # Get column names from cursor description
                    col_names = [desc[0] for desc in cursor.description]
                    schema_parts.append(
                        f"\n-- Sample rows from {table_name} "
                        f"(columns: {', '.join(col_names)}):"
                    )
                    for row in sample_rows:
                        schema_parts.append(f"-- {row}")
            except sqlite3.Error:
                # If we can't read a table, skip samples (shouldn't happen with Chinook)
                pass

            schema_parts.append("")  # blank line between tables

        conn.close()

        return "\n".join(schema_parts)

    def execute_query(self, sql: str) -> dict:
        """
        Execute a validated SQL query and return results.

        IMPORTANT: This method should ONLY be called AFTER the SQL has passed
        through the validation pipeline (Phase 2). The read-only connection
        is the last line of defense, not the first.

        Args:
            sql: The SQL query to execute (should already be validated)

        Returns:
            dict with:
                - 'columns': list of column names
                - 'rows': list of row tuples
                - 'row_count': number of rows returned

        Raises:
            sqlite3.Error: If the query fails (syntax error, invalid column, etc.)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(sql)
            rows = cursor.fetchall()

            # Get column names from cursor.description
            columns = (
                [desc[0] for desc in cursor.description] if cursor.description else []
            )

            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
            }
        finally:
            # Always close the connection, even if query fails
            conn.close()

    def get_table_names(self) -> list[str]:
        """
        Get a list of all table names in the database.
        Useful for quick checks and validation.

        Returns:
            list of table name strings
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]

        conn.close()
        return tables
