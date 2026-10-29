"""Live Meta acceptance gate. Sends only the included synthetic PDFs."""
import sys
import argparse
import json
import os
import subprocess
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app
from app.meta import configured


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',default='work/live-meta-results.json',help='Sanitized synthetic-test evidence JSON path')
    args=parser.parse_args()
    if not configured():
        print('NOT RUN: Enter MODEL_API_KEY in the project .env file. No API key was found.')
        raise SystemExit(2)
    root=Path(__file__).resolve().parents[1]/'data'/'synthetic'
    evidence={'started_at':datetime.now(timezone.utc).isoformat(),'model':os.getenv('META_MODEL','muse-spark-1.3'),
        'data':'repository synthetic PDFs only','cases':[],'status':'running','max_tool_calls_per_case':8}
    project=root.parents[1]
    evidence['source_sha256']={path.relative_to(project).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((project/'app').glob('*.py'))}
    evidence['fixture_sha256']={path.relative_to(project).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
        for case in ('clean','contradiction','math_error','messy') for path in sorted((root/case).glob('*.pdf'))}
    try:evidence['revision']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root.parents[1],text=True).strip()
    except (OSError,subprocess.CalledProcessError):evidence['revision']='unknown'
    try:evidence['working_tree_modified']=bool(subprocess.check_output(['git','status','--porcelain'],cwd=project,text=True).strip())
    except (OSError,subprocess.CalledProcessError):evidence['working_tree_modified']=None
    output=Path(args.report);output.parent.mkdir(parents=True,exist_ok=True)
    def save():output.write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    save()
    with TestClient(app) as client:
        for case,expected in [('clean',0),('contradiction',1),('math_error',1),('messy',0)]:
            started=time.monotonic()
            print('RUN live Meta:',case,flush=True)
            files=[('files',(p.name,p.read_bytes(),'application/pdf')) for p in sorted((root/case).glob('*.pdf'))]
            response=client.post('/api/analyze',files=files,data={'mode':'meta'})
            response.raise_for_status();report=response.json();base='/api/cases/'+report['id']
            try:
                assert not report.get('agent_error'),report.get('agent_error')
                assert report['agent'] is not None
                assert not any(f['type']=='model_extraction_failed' for f in report['findings']), 'Model extraction failed'
                confirmed=[f for f in report['findings'] if f['severity']=='confirmed']
                assert len(confirmed)==expected,(case,report['findings'])
                if case=='clean':assert report['findings']==[]
                if case=='contradiction':assert confirmed[0]['difference']=='25.00' and len(confirmed[0]['sources'])==2
                if case=='math_error':assert confirmed[0]['difference']=='50.00'
                if case=='messy':assert report['status']=='review'
                assert report['agent']['tool_trace'], 'Expected actual tool use'
                assert len(report['agent']['tool_trace'])<=8, 'Eight total tool-call budget exceeded'
                evidence['cases'].append({'case':case,'result':'passed','status':report['status'],
                    'confirmed_findings':len(confirmed),'review_items':sum(f['severity']=='review' for f in report['findings']),
                    'differences':[f['difference'] for f in confirmed if 'difference' in f],
                    'source_counts':[len(f['sources']) for f in confirmed],
                    'tools':[t['tool'] for t in report['agent']['tool_trace']],
                    'tool_call_count':len(report['agent']['tool_trace']),
                    'elapsed_seconds':round(time.monotonic()-started,2)})
                save()
                print('PASS live Meta:',case,flush=True)
            except Exception:
                evidence['status']='failed'
                evidence['cases'].append({'case':case,'result':'failed'})
                save()
                raise
            finally:client.delete(base)
    evidence['status']='passed';evidence['finished_at']=datetime.now(timezone.utc).isoformat();save()
    print('Sanitized evidence saved:',output,flush=True)

if __name__ == '__main__':
    main()
