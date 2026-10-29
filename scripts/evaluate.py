"""Run the same offline evaluator used by GET /api/evals."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.evals import evaluate_suite

def evaluate():
    result=evaluate_suite()
    for row in result['cases']:
        print(f"{'PASS' if row['passed'] else 'FAIL'} {row['case']}: {row['confirmed_count']} confirmed, {row['review_count']} review")
        for error in row['errors']:print('  '+error)
    print(f"{result['summary']['passed']} / {result['summary']['total']} cases passed")
    return result

if __name__=='__main__':
    raise SystemExit(1 if evaluate()['summary']['failed'] else 0)
