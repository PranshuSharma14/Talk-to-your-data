"""
test_sql_validator.py -- Unit tests for the SQL validation pipeline.

Tests all 4 validation layers + edge cases.
Run with: python -m pytest tests/test_sql_validator.py -v
"""

import pytest
from app.sql_validator import validate_sql


class TestLayer1StatementType:
    """Layer 1: Only SELECT statements should pass."""

    def test_simple_select(self):
        result = validate_sql("SELECT * FROM Customer")
        assert result["valid"] is True

    def test_select_with_where(self):
        result = validate_sql("SELECT FirstName FROM Customer WHERE Country = 'USA'")
        assert result["valid"] is True

    def test_select_count(self):
        result = validate_sql("SELECT COUNT(*) FROM Customer")
        assert result["valid"] is True

    def test_select_with_join(self):
        result = validate_sql(
            "SELECT c.FirstName, i.Total FROM Customer c "
            "JOIN Invoice i ON c.CustomerId = i.CustomerId"
        )
        assert result["valid"] is True

    def test_insert_blocked(self):
        result = validate_sql("INSERT INTO Customer (FirstName) VALUES ('Hacker')")
        assert result["valid"] is False
        assert "Layer 1" in result["error"]

    def test_update_blocked(self):
        result = validate_sql("UPDATE Customer SET FirstName = 'Hacked' WHERE CustomerId = 1")
        assert result["valid"] is False

    def test_delete_blocked(self):
        result = validate_sql("DELETE FROM Customer WHERE CustomerId = 1")
        assert result["valid"] is False

    def test_drop_blocked(self):
        result = validate_sql("DROP TABLE Customer")
        assert result["valid"] is False

    def test_alter_blocked(self):
        result = validate_sql("ALTER TABLE Customer ADD COLUMN Hacked TEXT")
        assert result["valid"] is False

    def test_create_blocked(self):
        result = validate_sql("CREATE TABLE Hacked (id INT)")
        assert result["valid"] is False

    def test_empty_query(self):
        result = validate_sql("")
        assert result["valid"] is False
        assert "Empty" in result["error"]

    def test_whitespace_only(self):
        result = validate_sql("   ")
        assert result["valid"] is False


class TestLayer2KeywordBlocklist:
    """Layer 2: Dangerous keywords should be caught even in tricky SQL."""

    def test_drop_in_subquery(self):
        """DROP hidden inside what looks like a SELECT."""
        result = validate_sql("SELECT * FROM Customer; DROP TABLE Customer")
        assert result["valid"] is False

    def test_pragma_blocked(self):
        """PRAGMA can change SQLite settings -- must be blocked."""
        result = validate_sql("PRAGMA table_info(Customer)")
        assert result["valid"] is False

    def test_attach_blocked(self):
        """ATTACH can connect external databases -- dangerous."""
        result = validate_sql("ATTACH DATABASE 'hack.db' AS hack")
        assert result["valid"] is False

    def test_delete_in_string_literal_passes(self):
        """'Delete' inside a string is data, not a command -- should NOT be blocked."""
        result = validate_sql("SELECT * FROM Track WHERE Name = 'Delete This Track'")
        assert result["valid"] is True, f"False positive! Error: {result['error']}"

    def test_drop_in_string_literal_passes(self):
        """'Drop' inside a string is data, not a command."""
        result = validate_sql("SELECT * FROM Track WHERE Name LIKE '%Drop%'")
        assert result["valid"] is True, f"False positive! Error: {result['error']}"

    def test_create_in_column_name_passes(self):
        """CREATED_AT should not trigger CREATE block (word boundary check)."""
        # Using a column alias that contains CREATE as a substring
        result = validate_sql("SELECT InvoiceDate AS created_at FROM Invoice LIMIT 5")
        assert result["valid"] is True, f"False positive! Error: {result['error']}"


class TestLayer3StackedQueries:
    """Layer 3: Multiple statements separated by semicolons should be caught."""

    def test_stacked_select_drop(self):
        """Stacked query should be blocked (may be caught by Layer 2 or Layer 3)."""
        result = validate_sql("SELECT 1; DROP TABLE Customer")
        assert result["valid"] is False

    def test_stacked_select_delete(self):
        result = validate_sql("SELECT * FROM Customer; DELETE FROM Customer")
        assert result["valid"] is False

    def test_stacked_select_insert(self):
        result = validate_sql("SELECT 1; INSERT INTO Customer VALUES (999, 'Hack')")
        assert result["valid"] is False

    def test_trailing_semicolon_ok(self):
        """A single trailing semicolon is harmless and common."""
        result = validate_sql("SELECT * FROM Customer;")
        assert result["valid"] is True

    def test_semicolon_in_string_ok(self):
        """Semicolons inside string literals are data, not statement separators."""
        result = validate_sql("SELECT * FROM Track WHERE Name = 'Rock; Roll'")
        assert result["valid"] is True, f"False positive! Error: {result['error']}"


class TestLayer4LimitInjection:
    """Layer 4: LIMIT should be added when missing, preserved when present."""

    def test_limit_added_when_missing(self):
        result = validate_sql("SELECT * FROM Customer")
        assert result["valid"] is True
        assert "LIMIT" in result["sql"].upper()
        assert "500" in result["sql"]

    def test_existing_limit_preserved(self):
        result = validate_sql("SELECT * FROM Customer LIMIT 10")
        assert result["valid"] is True
        assert "LIMIT 10" in result["sql"]
        # Should NOT add another LIMIT
        assert result["sql"].upper().count("LIMIT") == 1

    def test_limit_with_offset_preserved(self):
        result = validate_sql("SELECT * FROM Customer LIMIT 10 OFFSET 5")
        assert result["valid"] is True
        assert "LIMIT 10" in result["sql"]

    def test_limit_added_to_complex_query(self):
        sql = (
            "SELECT c.FirstName, SUM(i.Total) as Revenue "
            "FROM Customer c JOIN Invoice i ON c.CustomerId = i.CustomerId "
            "GROUP BY c.CustomerId ORDER BY Revenue DESC"
        )
        result = validate_sql(sql)
        assert result["valid"] is True
        assert "LIMIT 500" in result["sql"]


class TestEdgeCases:
    """Edge cases and real-world scenarios."""

    def test_multiline_query(self):
        sql = """
        SELECT
            c.FirstName,
            c.LastName,
            COUNT(i.InvoiceId) as OrderCount
        FROM Customer c
        JOIN Invoice i ON c.CustomerId = i.CustomerId
        GROUP BY c.CustomerId
        ORDER BY OrderCount DESC
        """
        result = validate_sql(sql)
        assert result["valid"] is True

    def test_subquery(self):
        sql = (
            "SELECT * FROM Customer WHERE CustomerId IN "
            "(SELECT CustomerId FROM Invoice WHERE Total > 10)"
        )
        result = validate_sql(sql)
        assert result["valid"] is True

    def test_case_insensitive_blocking(self):
        """Keywords should be caught regardless of case."""
        result = validate_sql("select * from Customer; drop table Customer")
        assert result["valid"] is False

    def test_with_sql_comments(self):
        """SQL comments from LLM (like -- ASSUMPTION) should be fine."""
        sql = "-- ASSUMPTION: best = highest spending\nSELECT * FROM Customer ORDER BY Total DESC"
        result = validate_sql(sql)
        assert result["valid"] is True

    def test_truncate_blocked(self):
        result = validate_sql("TRUNCATE TABLE Customer")
        assert result["valid"] is False
