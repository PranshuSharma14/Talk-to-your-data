# Talk to Your Data — Written Component

## 7a. AI Usage Log

### Which AI Tools I Used

**Primary Tool: Antigravity IDE (Claude-based assistant - Claude Sonnet 4.5)**
- **Scaffolding**: Generated initial project structure, boilerplate code for FastAPI endpoints, database connections
- **Implementation**: Wrote core logic for query engine pipeline, LLM prompts, SQL validation layers
- **Testing**: Created evaluation harness, test cases for SQL validator
- **Debugging**: Helped diagnose API quota issues, model name resolution problems
- **Documentation**: Generated code comments, docstrings, this writeup

### Examples of Rejected/Fixed AI Output

**Example 1: Overly Complex Schema Loading**
- **What AI suggested**: AI initially proposed fetching full table data samples for every request
- **Why I rejected it**: This would be extremely slow and wasteful. Schema doesn't change, so it should be cached
- **What I did instead**: Added `_schema` caching in QueryEngine class (lines 132-138 in query_engine.py)

**Example 2: Weak SQL Validation**
- **What AI suggested**: Simple regex check like `if 'DROP' in sql.upper()`
- **Why I rejected it**: False positives (e.g., "SELECT * FROM Track WHERE Name = 'Drop Zone'") and could miss sophisticated attacks
- **What I did instead**: Implemented 4-layer defense-in-depth with sqlparse AST parsing, string literal stripping, and stacked query detection

### What I Can't Fully Explain

**The exact token limit behavior of Gemini 1.5 Flash**: The code includes schema + sample rows in the prompt, but I haven't tested the exact breaking point where context becomes too large. In production, I would add:
- Token counting before API calls
- Graceful degradation (remove sample rows if schema is huge)
- Monitoring to track when we approach limits

**Why Gemini model names keep returning 404 errors**: Despite trying multiple SDK versions (`google-genai` vs `google-generativeai`), proper API keys, and different model names (`gemini-1.5-flash`, `gemini-2.0-flash-exp`, `gemini-pro`), we consistently get 404 "model not found" errors. This appears to be an API region/compatibility issue I couldn't resolve within the assignment timeframe. The architecture is sound, but the model resolution mechanism needs deeper investigation.

---

## 7b. Key Decisions

### Decision 1: Two-Call LLM Architecture

**What I decided**: Use TWO separate LLM calls:
1. Question + Schema → SQL
2. Question + SQL + Real Data → Natural Language Answer

**Alternatives considered**:
- **One-call approach**: Question + Schema → Direct Answer
  - Faster (1 API call instead of 2)
  - Simpler code
- **Three-call approach**: Add LLM call for query validation
  - More robust validation
  - Could catch semantic errors

**Why I chose two calls**:
The gap between the two calls is where **validation and real data** happens. With one call, the LLM would generate answers from memory/hallucination and hence from two calls,  answer remain grounded that is it directly comes from real data from our database.


Three calls would add latency without meaningful benefit since SQL validation is better done with deterministic code (sqlparse) than probabilistic LLM judgment.


### Decision 2: Defense-in-Depth Security (4 Validation Layers + Read-Only DB)

**What I decided**: Implement 5 layers of security:
1. **Layer 1**: Statement type check (sqlparse AST)
2. **Layer 2**: Keyword blocklist (after stripping string literals)
3. **Layer 3**: Stacked query detection (semicolon checking)
4. **Layer 4**: LIMIT injection (cap at 500 rows)
5. **Layer 5**: Read-only database connection

**Alternatives considered**:
- **Trust the LLM**: Assume GPT-4/Gemini is "safe enough"
  - Minimal code, faster development
- **Single validation layer**: Just use sqlparse OR keyword blocking
  - Simpler, easier to understand

**Why I chose defense-in-depth**:
The assignment emphasizes: *"Safety"* Each layer catches different attack vectors:

```python
# Layer 1 catches: INSERT, UPDATE, CREATE TABLE
# Layer 2 catches: "SELECT * FROM Track; DROP TABLE Track"
# Layer 3 catches: Stacked queries with clever encoding
# Layer 4 catches: SELECT * FROM Track (returns 3,503 rows → memory exhaustion)
# Layer 5 catches: Everything else (SQLite PRAGMA protections)
```

Even if an attacker defeats 4 layers, the read-only connection (Last Ultimate Security Layer) blocks all writes. This is the security posture expected for production systems handling untrusted input.

### Decision 3: Schema + Sample Rows in Prompt

**What I decided**: Send the LLM:
- Full database schema (all tables, columns, foreign keys)
- Sample rows (3 rows from each table)

**Alternatives considered**:
- **Schema only, no samples**:
  - Smaller prompts, faster/cheaper
  - LLM must guess data types and formats

- **Embeddings + RAG** (retrieve relevant schema chunks):
  - Scales to massive schemas
  - Complex infrastructure (vector DB, embedding model)

**Why I chose schema + samples**:
Sample rows solve critical semantic ambiguities:

```sql
-- Without samples, LLM might generate:
SELECT * FROM Invoice WHERE Year = 2013  ❌ (no Year column)

-- With samples showing InvoiceDate = '2009-01-01 00:00:00':
SELECT * FROM Invoice WHERE strftime('%Y', InvoiceDate) = '2013'  ✅
```

The Chinook database is small enough (11 tables) that the full schema + samples fit comfortably in Gemini's context window. For larger schemas, I would use **RAG** 


---

## 7c. Design Questions

### Question 1: Top 2-3 Ways This System Can Produce Wrong But Confident Answers

**1. Hallucinated Numbers in Answer Generation (LLM Call #2)**

Even though SQL returns real data, the second LLM call could misread or "enhance" the numbers:

```python
# Real data returned: [{"total": 826.65}]
# LLM generates: "Rock generated approximately $850 in revenue"
```

**How to catch it**:
- Parse the LLM's answer and extract numbers
- Cross-check every number against the raw result rows
- Flag answer as suspicious if numbers don't match exactly
- Use temperature=0.0 for answer generation (more deterministic)

**2. Incorrect SQL Logic (Joins, Aggregations, Filtering)**

The LLM might generate syntactically valid SQL that answers the wrong question:

```sql
-- Question: "How many albums does Iron Maiden have?"
-- Correct: Count distinct albums
-- LLM might generate: Count all tracks (subtly wrong)

-- Returns 213 tracks, LLM says "Iron Maiden has 213 albums" ❌
-- Actual: 21 albums
```

**How to catch it**:
- **Benchmark suite with known answers** (already implemented)
- Unit test common query patterns (aggregations, joins)
- Show SQL to user BEFORE execution ("preview mode" — I already implemented it)


**3. Ambiguity Resolved Incorrectly**

The LLM picks an interpretation that's technically valid but not what the user meant:

```
User: "Who is our best customer?"
LLM assumption: "highest spending" → returns Helena Holý ($49.62)
User actually meant: "most recent order" → different answer
```

**How to catch it**:
- Cannot catch programmatically (only user knows their intent)
- Assumption should be clearly mentioned (Already Implemented)


### Question 2: If Dataset Were Too Large for Context Window

**What I'd change**: Implement **semantic search over schema + RAG** (Retrieval-Augmented Generation)

**Architecture**:
1. **Offline**: Generate embeddings for each table's schema + sample data
2. **Online**: 
   - Embed the user's question
   - Retrieve top-k most relevant tables 
   - Send ONLY those tables' schemas to LLM

**Example**:
```
Question: "What genre made the most revenue?"
Relevant tables: Genre, Track, InvoiceLine (skip Employee, Playlist, etc.)
Context size: 3 tables instead of 11 → 70% reduction
```

### Optional Bonus: Debugging Different Answers for Same Question

If a user asks the same question twice and gets different answers, debug in this order:

**Step 1: Compare the SQL queries**
```bash
# Logs should show:
# Attempt 1: SELECT Genre.Name, SUM(InvoiceLine.Total) ...
# Attempt 2: SELECT Genre.Name, COUNT(*) ...  ← different query
```

**If SQL is different**: Temperature should be 0.0 for SQL generation (deterministic). Check:
- Is temperature actually 0.0 in code?
- Are sample rows changing between requests (non-deterministic sampling)?
- Did the user rephrase the question slightly?

**If SQL is identical**: Continue to Step 2.

**Step 2: Check if answer wording differs (but numbers are same)**
```
Attempt 1: "Rock generated $826.65 in revenue"
Attempt 2: "The Rock genre made $826.65"
```

**If numbers match but wording differs**: This is expected. Temperature=0.3 for answer generation allows variation.

**If numbers differ**: Continue to Step 3.

**Step 3: Check if database data changed**
 But it's impossible for our system, since database is only Read-Only.



**Step 4: Add comprehensive logging**

Log every request so you can diff the two attempts and see exactly what changed.

**One Important Thing**

 Our system uses temperature=0.0 for SQL generation, so if the question is phrased identically, the SQL should be deterministic. This is the correct design for analytics systems.

---

## 7d. Code Critique

**The flawed snippet**:
```python
def answer_question(question: str) -> str:
    schema = get_full_schema()                       # entire schema as text
    sql = llm(f"Schema: {schema}\nWrite SQL for: {question}")
    rows = db.execute(sql)                            # run whatever the model returns
    return llm(f"Answer '{question}' using this data: {rows}")
```

### Flaws Identified

**1. No SQL Validation / Injection Vulnerability** (CRITICAL SECURITY FLAW)
- **Problem**: Executes whatever the LLM returns, no safety checks
- **Attack**: User asks "Show me all customers" → LLM returns `"SELECT * FROM Customer; DROP TABLE Customer"`
- **Fix**: Add validation layers (statement type check, keyword blocklist, stacked query detection)

**2. No Read-Only Database Connection** (CRITICAL SECURITY FLAW)
- **Problem**: `db.execute()` appears to allow any statement type
- **Attack**: Even if validation is added, bugs could let writes through
- **Fix**: Open database with `PRAGMA query_only = ON` or use read-only URI (`file:chinook.db?mode=ro`)

**3. No LIMIT / Runaway Query Protection** (AVAILABILITY RISK)
- **Problem**: Query like `SELECT * FROM Track` returns 3,503 rows → memory exhaustion, timeout
- **Fix**: Inject `LIMIT 500` if not present, add query timeout

**4. No Handling of Ambiguous Questions** (CORRECTNESS FLAW)
- **Problem**: User asks "Who is our best customer?" → LLM silently picks interpretation (spending? orders? recent?)
- **Fix**: Prompt LLM to state assumptions explicitly, surface them in the answer

**5. No Handling of Unanswerable Questions** (TRUST FLAW)
- **Problem**: User asks "What is the profit margin?" → LLM might generate SQL that returns empty results or hallucinate numbers
- **Impact**: System appears confident but answer is meaningless
- **Fix**: Prompt LLM to recognize unanswerable questions and return sentinel value like `UNANSWERABLE: no cost data`

**6. Single LLM Call = Hallucination Risk** (CORRECTNESS FLAW)
- **Problem**: LLM answers from prompt alone, no validation that answer matches real data
- **Impact**: LLM might say "Rock generated $850" when actual data shows $826.65
- **Fix**: Two-call architecture:
  1. Question → SQL
  2. SQL + Real Rows → Answer (grounded in actual data)


**7. No Prompt Engineering for SQL Generation** (CORRECTNESS FLAW)
- **Fix**: Detailed prompt with:
  - "Generate a SQLite-compatible SELECT query"
  - "Use ONLY tables/columns in the schema"
  - "Return ONLY the SQL, no markdown"
  - Include sample rows so LLM understands data types

**8. No Temperature Control** (CORRECTNESS FLAW)
- **Problem**: LLM uses default temperature (often 0.7-1.0) → non-deterministic SQL
- **Impact**: Same question asked twice yields different SQL queries
- **Fix**: 
  - Use temperature=0.0 for SQL generation (deterministic)
  - Use temperature=0.3 for answer generation (slight creativity acceptable)



