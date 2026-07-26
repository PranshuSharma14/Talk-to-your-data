"""
Enhanced evaluation harness with 5 scoring methods + SQL pattern validation.
Addresses known failure modes: wrong JOINs, aggregation ambiguity, value format mismatches.
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.query_engine import QueryEngine


class EnhancedBenchmark:
    """Enhanced evaluation harness with detailed failure mode tracking."""
    
    def __init__(self):
        self.engine = QueryEngine()
        self.questions = self._load_questions()
        self.results = []
        
    def _load_questions(self) -> List[Dict]:
        """Load benchmark questions from JSON file."""
        questions_file = Path(__file__).parent / "questions.json"
        with open(questions_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _extract_number(self, text: str) -> float:
        """Extract first number from text."""
        match = re.search(r'[-+]?\d*\.?\d+', text)
        return float(match.group()) if match else None
    
    def _validate_sql_pattern(self, sql: str, pattern: Dict) -> tuple[bool, str]:
        """
        Validate SQL against expected pattern.
        Returns (passed, reason).
        """
        if not sql or not pattern:
            return True, ""
        
        sql_upper = sql.upper()
        
        # Check required tables
        must_include = pattern.get("must_include", [])
        for table in must_include:
            if table.upper() not in sql_upper:
                return False, f"Missing table: {table}"
        
        # Check tables that shouldn't be there (over-joining)
        should_not = pattern.get("should_not", [])
        for table in should_not:
            if table.upper() in sql_upper:
                return False, f"Unnecessary table: {table}"
        
        # Check aggregation
        expected_agg = pattern.get("aggregation")
        if expected_agg:
            if expected_agg.upper() not in sql_upper:
                return False, f"Missing aggregation: {expected_agg}"
        
        return True, ""
    
    def _score_answer(self, question: Dict, response: Dict) -> tuple[bool, str]:
        """
        Score a response using 5 methods + SQL pattern validation.
        Returns (passed, reason).
        """
        expected = question["expected_answer"]
        answer_type = expected["type"]
        
        answer_text = response.get("answer", "").lower()
        sql = response.get("sql", "")
        
        # Method 1: Numeric comparison
        if answer_type == "numeric":
            actual = self._extract_number(answer_text)
            if actual is None:
                return False, "No number found in answer"
            
            expected_value = expected["value"]
            tolerance = expected.get("tolerance", 0)
            
            if abs(actual - expected_value) <= tolerance:
                # Check SQL pattern (bonus validation)
                if "expected_sql_pattern" in question:
                    pattern_ok, reason = self._validate_sql_pattern(
                        sql, question["expected_sql_pattern"]
                    )
                    if not pattern_ok:
                        return False, f"SQL pattern: {reason}"
                return True, f"Correct: {actual}"
            else:
                return False, f"Expected {expected_value}±{tolerance}, got {actual}"
        
        # Method 2: Categorical (entity name appears)
        elif answer_type == "categorical":
            expected_values = expected.get("expected_values", [])
            for value in expected_values:
                if value.lower() in answer_text:
                    return True, f"Found: {value}"
            return False, f"None of {expected_values} found in answer"
        
        # Method 3: List/Multi-item
        elif answer_type == "list":
            min_items = expected.get("min_items", 1)
            must_contain = expected.get("must_contain", [])
            
            found_count = sum(1 for item in must_contain if item.lower() in answer_text)
            
            if found_count >= min_items:
                return True, f"Found {found_count}/{len(must_contain)} expected items"
            else:
                return False, f"Only found {found_count}/{min_items} required items"
        
        # Method 4: Ambiguous (must state assumption)
        elif answer_type == "ambiguous":
            must_state = expected.get("must_state_assumption", False)
            
            if not must_state:
                return True, "Ambiguous question (no specific check)"
            
            # Check if answer explicitly states assumption
            assumption_keywords = ["assuming", "assume", "interpreting", "interpret", "defining", "define"]
            has_assumption = any(kw in answer_text for kw in assumption_keywords)
            
            # Also check assumptions field in response
            has_assumptions_field = bool(response.get("assumptions"))
            
            if has_assumption or has_assumptions_field:
                return True, "Assumption stated"
            else:
                return False, "Did not state assumption for ambiguous question"
        
        # Method 5: Unanswerable (must decline)
        elif answer_type == "unanswerable":
            # Check if system declined
            decline_keywords = ["cannot", "can't", "unable", "don't have", "no data", "not available"]
            declined = any(kw in answer_text for kw in decline_keywords)
            
            # Check if SQL is None/empty (system shouldn't generate SQL)
            no_sql = not sql or sql.strip() == ""
            
            if declined and no_sql:
                return True, "Correctly declined"
            elif not declined:
                return False, "Should have declined (unanswerable)"
            elif not no_sql:
                return False, "Generated SQL for unanswerable question"
        
        return False, f"Unknown answer type: {answer_type}"
    
    def run(self):
        """Run full evaluation harness."""
        print("=" * 80)
        print("ENHANCED EVALUATION HARNESS")
        print("=" * 80)
        print(f"Testing {len(self.questions)} questions...")
        print()
        
        passed = 0
        failed = 0
        failures_by_category = {}
        
        for q in self.questions:
            q_id = q["id"]
            question_text = q["question"]
            category = q["category"]
            
            print(f"{q_id}: {question_text[:60]}... ", end="", flush=True)
            
            try:
                # Run through pipeline
                response = self.engine.process_question(question_text)
                
                # Score the response
                passed_check, reason = self._score_answer(q, response)
                
                result = {
                    "question_id": q_id,
                    "question": question_text,
                    "category": category,
                    "response": response,
                    "passed": passed_check,
                    "reason": reason,
                    "failure_mode": q.get("failure_mode", "none")
                }
                
                self.results.append(result)
                
                if passed_check:
                    print(f"✅ PASS - {reason}")
                    passed += 1
                else:
                    print(f"❌ FAIL - {reason}")
                    failed += 1
                    
                    # Track failure by category
                    if category not in failures_by_category:
                        failures_by_category[category] = []
                    failures_by_category[category].append(q_id)
                
            except Exception as e:
                print(f"❌ ERROR - {str(e)}")
                result = {
                    "question_id": q_id,
                    "question": question_text,
                    "category": category,
                    "error": str(e),
                    "passed": False,
                    "reason": f"Exception: {str(e)}"
                }
                self.results.append(result)
                failed += 1
        
        # Print summary
        print()
        print("=" * 80)
        print("EVALUATION RESULTS")
        print("=" * 80)
        print(f"Overall: {passed}/{len(self.questions)} passed ({100*passed/len(self.questions):.1f}%)")
        print()
        
        # Show passed questions
        if passed > 0:
            print("PASSED Questions:")
            for r in self.results:
                if r.get("passed"):
                    print(f"✅ {r['question_id']:4s} {r['category']:20s} - {r['reason']}")
            print()
        
        # Show failed questions
        if failed > 0:
            print("FAILED Questions:")
            for r in self.results:
                if not r.get("passed"):
                    print(f"❌ {r['question_id']:4s} {r['category']:20s} - {r['reason']}")
            print()
        
        # Show category breakdown
        print("RESULTS BY CATEGORY:")
        categories = {}
        for r in self.results:
            cat = r["category"]
            if cat not in categories:
                categories[cat] = {"passed": 0, "total": 0}
            categories[cat]["total"] += 1
            if r.get("passed"):
                categories[cat]["passed"] += 1
        
        for cat, stats in sorted(categories.items()):
            pct = 100 * stats["passed"] / stats["total"] if stats["total"] > 0 else 0
            print(f"  {cat:20s}: {stats['passed']}/{stats['total']} ({pct:.0f}%)")
        
        print()
        print("=" * 80)
        
        # Save results
        self._save_results()
        
        return passed, failed
    
    def _save_results(self):
        """Save results to file."""
        results_dir = Path(__file__).parent / "results"
        results_dir.mkdir(exist_ok=True)
        
        # Human-readable summary
        summary_file = results_dir / "eval_results.txt"
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write("EVALUATION RESULTS\n")
            f.write("=" * 80 + "\n\n")
            
            passed = sum(1 for r in self.results if r.get("passed"))
            total = len(self.results)
            
            f.write(f"Overall: {passed}/{total} passed ({100*passed/total:.1f}%)\n\n")
            
            for r in self.results:
                status = "✅ PASS" if r.get("passed") else "❌ FAIL"
                f.write(f"{status} {r['question_id']}: {r['question']}\n")
                f.write(f"  Category: {r['category']}\n")
                f.write(f"  Result: {r['reason']}\n")
                if 'response' in r:
                    f.write(f"  Answer: {r['response'].get('answer', 'N/A')[:200]}\n")
                f.write("\n")
        
        print(f"Results saved to: {summary_file}")
        
        # Machine-readable JSON with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_file = results_dir / f"eval_{timestamp}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump({
                "timestamp": timestamp,
                "total": len(self.results),
                "passed": sum(1 for r in self.results if r.get("passed")),
                "results": self.results
            }, f, indent=2)
        
        print(f"JSON results saved to: {json_file}")


if __name__ == "__main__":
    benchmark = EnhancedBenchmark()
    passed, failed = benchmark.run()
    
    # Exit with non-zero code if any failures
    sys.exit(0 if failed == 0 else 1)
