"""Run the extended PDF benchmark and fail on any regression or false clean."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.benchmark import evaluate_suite

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',type=Path)
    args=parser.parse_args();result=evaluate_suite()
    for row in result['cases']:print(('PASS' if row['passed'] else 'FAIL'),row['case'],row['status'],'; '.join(row['errors']))
    print(json.dumps(result['summary'],indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    raise SystemExit(1 if result['summary']['failed'] or result['summary']['false_clean_count'] else 0)
