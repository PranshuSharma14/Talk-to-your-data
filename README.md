# Talk to Your Data — A Conversational Analytics Service

**Turn natural language questions into SQL queries and trustworthy answers.**

Ask questions like "Which genre made the most revenue?" and get back accurate answers grounded in real database results — with full transparency showing the SQL query and raw data used to generate each answer.

---

## 🎯 What This Project Does

This is a conversational analytics system that:

1. **Accepts natural language questions** about a relational database
2. **Generates SQL queries** using Google's Gemini LLM
3. **Validates queries** through a 4-layer security pipeline (defense-in-depth)
4. **Executes on a read-only database** (Chinook music store dataset)
5. **Returns grounded answers** with full evidence (SQL + raw results)
6. **Handles ambiguity** by stating assumptions explicitly
7. **Declines unanswerable questions** honestly instead of hallucinating

**Key Features**:
- ✅ Two-call LLM architecture (SQL generation → execution → answer generation)
- ✅ Defense-in-depth security (5 validation layers)
- ✅ Ambiguous question handling with explicit assumptions
- ✅ Unanswerable question detection (declines when data doesn't exist)
- ✅ Query preview mode (see SQL before execution)
- ✅ Latency tracking with breakdown (schema, LLM, validation, DB)
- ✅ Automatic chart generation for numeric results
- ✅ Evaluation harness with 15 benchmark questions

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Question                            │
│              "Which genre made the most revenue?"                │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │   Query Engine        │
                    │  (query_engine.py)    │
                    └───────────┬───────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
┌───────▼────────┐   ┌──────────▼─────────┐   ┌───────▼────────┐
│  LLM Call #1   │   │   SQL Validator    │   │   Database     │
│   (llm.py)     │   │ (sql_validator.py) │   │ (database.py)  │
│                │   │                    │   │                │
│ Question +     │   │ • Statement type   │   │ • Read-only    │
│ Schema →       │   │ • Keyword block    │   │ • SQLite       │
│ SQL Query      │   │ • Stacked query    │   │ • Chinook DB   │
└────────┬───────┘   │ • LIMIT injection  │   └────────┬───────┘
         │           └──────────┬─────────┘            │
         │                      │                      │
         │                      │                      │
         └──────────────────────┼──────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │   Execute SQL         │
                    │   Get Real Rows       │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   LLM Call #2         │
                    │   (llm.py)            │
                    │                       │
                    │ Question + SQL +      │
                    │ Real Data →           │
                    │ Natural Language      │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   Return Response     │
                    │ • Answer              │
                    │ • SQL Query           │
                    │ • Raw Rows            │
                    │ • Assumptions         │
                    │ • Latency Breakdown   │
                    └───────────────────────┘
```

### Key Design Decisions

**1. Two-Call LLM Architecture**
- **Call #1**: Question + Schema → SQL (temperature=0.0 for determinism)
- **Call #2**: Question + SQL + Real Data → Answer (temperature=0.3 for natural language)
- The gap between calls is where **validation** and **real data** happen
- Prevents hallucination: LLM cannot invent numbers not in the database

**2. Defense-in-Depth Security**
- **Layer 1**: Statement type check using sqlparse AST
- **Layer 2**: Keyword blocklist (after stripping string literals)
- **Layer 3**: Stacked query detection (semicolon checking)
- **Layer 4**: LIMIT injection (cap at 500 rows)
- **Layer 5**: Read-only database connection (SQLite `PRAGMA query_only`)

**3. Explicit Ambiguity Handling**
- LLM trained to add SQL comments: `-- ASSUMPTION: "best" = highest spending`
- Assumptions extracted and surfaced in the answer
- User knows exactly what metric was used

**4. Unanswerable Question Detection**
- LLM returns sentinel value: `UNANSWERABLE: no profit/cost data`
- System declines honestly instead of generating meaningless SQL
- Examples: profit margins, streaming counts, future predictions

---

## 📁 Project Structure

```
talk-to-your-data/
├── app/
│   ├── __init__.py
│   ├── config.py              # Environment variables (API key, DB path)
│   ├── database.py            # SQLite connection, schema loading, read-only execution
│   ├── llm.py                 # Gemini API wrapper with retry logic
│   ├── models.py              # Pydantic models for request/response
│   ├── query_engine.py        # CORE: Orchestrates the full pipeline
│   ├── sql_validator.py       # 4-layer SQL validation (defense-in-depth)
│   ├── main.py                # FastAPI application with /ask endpoint
│   └── static/
│       └── index.html         # Chat UI with Chart.js integration
├── eval/
│   ├── benchmark.py           # Evaluation harness (runs 15 test questions)
│   ├── questions.json         # 15 benchmark questions with expected answers
│   └── results/
│       └── eval_results.txt   # Committed evaluation results (8/15 = 53%)
├── tests/
│   └── test_sql_validator.py # Unit tests for SQL validation layers
├── chinook.db                 # SQLite database (music store: 11 tables)
├── requirements.txt           # Python dependencies
├── .env                       # Your API key (git-ignored)
├── .env.example               # Template for .env
├── .gitignore
├── README.md                  # This file
└── WRITEUP.md                 # Written component (AI usage, decisions, critique)
```

---

## 🚀 Setup Instructions (Clone to Running)

### Prerequisites

- **Python 3.10+** (3.8+ should work, but 3.10+ is tested)
- **pip** (Python package manager)
- **Git** (to clone the repository)
- **Google Gemini API Key** (free tier: 15 requests/min, 1500/day)

### Step 1: Clone the Repository

```bash
git clone <your-repo-url>
cd talk-to-your-data
```

### Step 2: Create Virtual Environment

**On Windows (cmd)**:
```cmd
python -m venv venv
venv\Scripts\activate
```

**On Windows (PowerShell)**:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**On macOS/Linux**:
```bash
python3 -m venv venv
source venv/bin/activate
```

You should see `(venv)` in your terminal prompt.

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

**Dependencies installed**:
- `fastapi` — Web framework for the API
- `uvicorn` — ASGI server to run FastAPI
- `google-generativeai` — Google Gemini API SDK
- `sqlparse` — SQL parser for validation
- `python-dotenv` — Load environment variables from .env
- `pydantic` — Data validation for API models
- `pytest` — Testing framework

### Step 4: Set Up Your API Key

1. **Get a Gemini API key**:
   - Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
   - Click "Create API Key"
   - Copy the key

2. **Create `.env` file**:
   ```bash
   copy .env.example .env     # Windows (cmd)
   cp .env.example .env       # macOS/Linux
   ```

3. **Edit `.env` and add your key**:
   ```
   GEMINI_API_KEY=your_actual_api_key_here
   ```

### Step 5: Verify Database Exists

The Chinook SQLite database should already be in the project:

```bash
dir chinook.db    # Windows (cmd)
ls chinook.db     # macOS/Linux
```

If missing, download from: https://github.com/lerocha/chinook-database

### Step 6: Run the Application

```bash
uvicorn app.main:app --reload --port 8000
```

**Expected output**:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx] using WatchFiles
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### Step 7: Open the Chat UI

Open your browser and navigate to:
```
http://localhost:8000
```

You should see the chat interface. Try asking:
- "How many customers are there?"
- "Which genre made the most revenue?"
- "Who is our best customer?" (tests ambiguity handling)
- "What is the profit margin on each album?" (tests unanswerable detection)

---

## 🧪 Running Tests

### Run All Tests

```bash
pytest
```

### Run SQL Validator Tests

```bash
pytest tests/test_sql_validator.py -v
```

**What's tested**:
- Valid SELECT queries pass all layers
- INSERT/UPDATE/DELETE blocked (Layer 1)
- DROP/ALTER blocked (Layer 2)
- Stacked queries blocked (Layer 3)
- LIMIT injection adds row cap (Layer 4)
- String literals don't cause false positives

---

## 📊 Running the Evaluation Harness

The evaluation harness runs 15 benchmark questions and reports accuracy.

```bash
python -m eval.benchmark
```

**What it tests**:
- ✅ Simple lookups (Q1: "How many customers?")
- ✅ Sorting + limits (Q2: "5 longest tracks")
- ✅ Group + aggregate (Q3: "Revenue by country")
- ✅ Joins + aggregates (Q4: "Genre with most tracks")
- ✅ Ambiguous questions (Q9: "Who is our best customer?")
- ✅ Unanswerable questions (Q10: "Profit margin?", Q11: "Streaming counts?")

**Expected output**:
```
Testing 15 questions...
Q1: How many customers are there?...               ✅ PASS
Q2: List the 5 longest tracks by duration...       ✅ PASS
Q3: What is the total revenue by country?...       ✅ PASS
...
Q10: What is the profit margin on each album?...   ✅ PASS (correctly declined)
Q11: How many tracks were streamed last month?...  ✅ PASS (correctly declined)
...

================================================================================
EVALUATION RESULTS
================================================================================
Overall: 8/15 passed (53.3%)
```

**Note**: Results may vary due to:
- API rate limits (free tier: 15 requests/min)
- Model non-determinism for answer generation (temperature=0.3)
- API quota exhaustion if run multiple times quickly

**Current committed result**: 8/15 (53.3%) — see `eval/results/eval_results.txt`

Questions that passed correctly include:
- All simple queries (Q1, Q4, Q7, Q12)
- Both unanswerable questions (Q10, Q11) — correctly declined
- Ambiguous question (Q9) — stated assumption

---

## 🎨 Using the Chat UI

### Features

1. **Ask Questions**: Type natural language questions in the input box
2. **Preview SQL**: Click "Preview SQL" to see the query without executing it
3. **View Results**: See the answer, SQL query, and raw data rows
4. **Automatic Charts**: Numeric results with 2 columns automatically render as bar charts
5. **Latency Display**: See timing breakdown (schema, LLM, validation, DB)
6. **Assumption Display**: Ambiguous questions show the assumption made
7. **Error Handling**: Clear error messages for invalid queries or API issues

### Example Questions to Try

**Simple Questions**:
- "How many customers are there?"
- "List all genres"
- "What is the total number of tracks?"

**Complex Questions**:
- "Which genre made the most revenue?"
- "Who are the top 5 customers by spending?"
- "What is the average invoice total?"

**Ambiguous Questions** (tests assumption handling):
- "Who is our best customer?"
- "What is the most popular genre?"
- "Which employee is the best?"

**Unanswerable Questions** (tests decline behavior):
- "What is the profit margin on each album?"
- "How many tracks were streamed last month?"
- "What is the customer satisfaction rating?"

---

## 🔧 Configuration

### Environment Variables

Edit `.env` to configure:

```bash
# Required: Your Google Gemini API key
GEMINI_API_KEY=your_api_key_here

# Optional: Database path (defaults to chinook.db)
# DATABASE_PATH=path/to/your/database.db
```

### Model Configuration

Edit `app/llm.py` to change the model:

```python
MODEL_NAME = "gemini-1.5-flash"  # Fast, good for SQL generation
# MODEL_NAME = "gemini-1.5-pro"  # More powerful, slower, higher cost
```

### Validation Configuration

Edit `app/sql_validator.py` to adjust limits:

```python
DEFAULT_LIMIT = 500  # Maximum rows returned per query
```

Add/remove blocked keywords:

```python
BLOCKED_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    # Add more keywords here
]
```

---

## 🛠️ Troubleshooting

### Issue: "404 NOT_FOUND: model not found"

**Symptoms**: All questions fail with 404 errors about Gemini model names.

**Possible causes**:
1. **API key issue**: Invalid or expired API key
2. **Model name mismatch**: Model not available in your region/tier
3. **SDK version**: Incompatibility between SDK and API version

**Solutions**:
1. Verify your API key at https://aistudio.google.com/app/apikey
2. Try different model names in `app/llm.py`:
   ```python
   MODEL_NAME = "gemini-1.5-flash"
   # or
   MODEL_NAME = "gemini-pro"
   ```
3. Check SDK version: `pip show google-generativeai`
4. Reinstall: `pip install --upgrade google-generativeai`

### Issue: "RATE_LIMIT_EXCEEDED: 429 quota exceeded"

**Symptoms**: First few questions work, then all fail with 429 errors.

**Cause**: Free tier limits (15 requests/min, 1500/day). Each question = 2 LLM calls.

**Solutions**:
1. **Wait**: Quota resets after 1 minute (for RPM limit) or 24 hours (for daily limit)
2. **Upgrade**: Get a paid API tier from Google

---

## 📚 Further Reading

- **WRITEUP.md** — Detailed explanation of AI usage, key decisions, design questions, and code critique

---


## 📝 License

This is a take-home assignment project. All code is original or clearly attributed.

---

## 🙋 Questions?

If you're evaluating this project and have questions:

1. Check **WRITEUP.md** for detailed explanations of key decisions
2. Check **eval/results/eval_results.txt** for committed evaluation results
3. Run the evaluation harness: `python -m eval.benchmark`
4. Check the inline code comments — every file has detailed docstrings

**Author**: [Pranshu Sharma]  
**Date**: July 2026  
**Assignment**: Conversational Analytics Service
