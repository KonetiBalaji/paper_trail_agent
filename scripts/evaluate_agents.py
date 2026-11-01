"""Generate the agent scorecard; no provider/model calls. Nonzero on gate failure."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.agent_evals import evaluate,validate_report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',default='work/agent-evals-results.json')
    args=parser.parse_args();result=evaluate();validate_report(result)
    output=Path(args.report);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'tool_contract':result['tools']['contract_correctness'],
                      'retrieval_precision':result['tools']['retrieval_precision'],'critic':result['critic']['catch_rate'],
                      'false_alarms':result['critic']['false_alarm_rate'],'live_status':result['live']['status']}))
    raise SystemExit(0 if result['passed'] else 1)
