"""Live Muse Spark acceptance on varied fictional layouts; paid API calls."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app import main,meta
from app.benchmark import field_values,ROOT

DEFAULT_CASES=('loan_reverse_columns','loan_split_row','bank_cross_page','injection_note')

def run(output,mode,selected=DEFAULT_CASES):
    if not meta.configured():raise SystemExit('NOT RUN: configure the local Meta key; never paste it into chat.')
    project=ROOT.parents[1];cases={case['case']:case for case in json.loads((ROOT/'manifest.json').read_text())['cases']}
    evidence={'started_at':datetime.now(timezone.utc).isoformat(),'status':'running','model':os.getenv('META_MODEL','muse-spark-1.3'),
        'mode':mode,'data':'repository fictional PDFs only','max_tool_calls_per_case':8,'cases':[],
        'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=project,text=True).strip(),
        'working_tree_modified':bool(subprocess.check_output(['git','status','--porcelain'],cwd=project,text=True).strip()),
        'source_sha256_encoding':'UTF-8 with universal LF newlines',
        'source_sha256':{path.relative_to(project).as_posix():hashlib.sha256(path.read_text(encoding='utf-8').encode()).hexdigest() for path in sorted((project/'app').glob('*.py'))}}
    output.parent.mkdir(parents=True,exist_ok=True)
    def save():output.write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    save()
    with TestClient(main.app) as client:
        for name in selected:
            case=cases[name];started=time.monotonic();base=None;report=None
            print('RUN live layout:',name,flush=True)
            try:
                paths=[ROOT/name/doc['file'] for doc in case['documents']]
                response=client.post('/api/analyze',files=[('files',(path.name,path.read_bytes(),'application/pdf')) for path in paths],data={'mode':mode})
                response.raise_for_status();report=response.json();base='/api/cases/'+report['id']
                assert report['status']==case['expected_status'] and not report.get('agent_error'),'Unexpected review/status or agent failure'
                assert report['agent'] and report['agent']['tool_trace'],'No actual model tool trace'
                assert len(report['agent']['tool_trace'])<=8,'Tool budget exceeded'
                for expected,doc in zip(case['documents'],report['documents']):assert field_values(doc['statement'])==field_values(expected['truth']),'Extraction differs from truth'
                evidence['cases'].append({'case':name,'result':'passed','status':report['status'],'tool_call_count':len(report['agent']['tool_trace']),
                    'tools':[event['tool'] for event in report['agent']['tool_trace']],
                    'extraction_routes':[doc.get('routing') for doc in report['documents']],'metrics':report.get('metrics'),
                    'fixture_sha256':{path.relative_to(project).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
                    'elapsed_seconds':round(time.monotonic()-started,2)})
                save();print('PASS live layout:',name,flush=True)
            except Exception:
                evidence['status']='failed';evidence['cases'].append({'case':name,'result':'failed',
                    'status':report.get('status') if report else None,'finding_types':[finding['type'] for finding in report['findings']] if report else [],
                    'validation_failures':[event['output'] for event in report.get('trace',[]) if event['kind']=='validation' and event['validation']=='failed'] if report else []});save();raise
            finally:
                if base:client.delete(base)
    evidence['status']='passed';evidence['finished_at']=datetime.now(timezone.utc).isoformat();save()
    print('Sanitized live layout evidence saved:',output)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',type=Path,default=Path('work/live-layout-results.json'));parser.add_argument('--mode',choices=['meta','auto'],default='auto')
    parser.add_argument('--cases',nargs='+',choices=DEFAULT_CASES,default=DEFAULT_CASES)
    args=parser.parse_args();run(args.report,args.mode,args.cases)
