"""Low-volume synthetic proof of intake reuse/isolation on the owned deployment."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import httpx

ROOT=Path(__file__).resolve().parents[1]
ORIGIN='https://paper-trail-agent.vercel.app'


def run():
    checks=[]
    def check(name,condition):
        checks.append({'check':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
    with httpx.Client(base_url=ORIGIN,timeout=60) as client,httpx.Client(base_url=ORIGIN,timeout=60) as peer:
        owned=[];headers={};peer_headers={}
        try:
            for session in (client,peer):
                response=session.post('/api/platform/demo/start');response.raise_for_status()
                check('isolated_demo_session',response.json()['role']=='demo')
            headers={'X-CSRF-Token':client.cookies.get('pta_csrf')};peer_headers={'X-CSRF-Token':peer.cookies.get('pta_csrf')}
            def post(session,fixture,auth):
                response=session.post('/api/platform/demo/cases/'+fixture,headers=auth);response.raise_for_status()
                report=response.json();owned.append((session,auth,report['id']));return report
            first=post(client,'math_error',headers)
            check('first_intake_created',first['intake_receipt']['created'])
            base='/api/cases/'+first['id']
            reviewed=client.patch(base+'/findings/F1',headers=headers,json={'action':'confirm','note':'Synthetic source checked',
                'expected_revision':0,'expected_case_version':first['report_version']})
            reviewed.raise_for_status()
            repeated=post(client,'math_error',headers)
            check('same_case_reused',repeated['id']==first['id'] and not repeated['intake_receipt']['created'])
            check('saved_review_preserved',repeated['report_version']==reviewed.json()['report_version']
                and repeated['findings'][0]['human_review']['decision']=='confirmed')
            check('reuse_has_no_new_model_calls',repeated['intake_receipt']['model_calls_this_request']==0)
            other=post(peer,'math_error',peer_headers)
            check('no_cross_workspace_reuse',other['id']!=first['id'] and other['intake_receipt']['created'])
            check('cross_workspace_report_denied',peer.get(base).status_code==404)
            duplicate=post(client,'duplicate_document',headers)
            check('duplicate_document_review',duplicate['status']=='review' and not any(f['severity']=='confirmed' for f in duplicate['findings']))
            check('self_comparison_skipped',{'duplicate_document','comparison_skipped'}<={f['type'] for f in duplicate['findings']})
            check('single_unique_source',duplicate['ingestion']['unique_sources']==1 and len(duplicate['calculations'])==1)
            check('no_paid_or_ocr_calls',duplicate['demo']['model_calls']==0 and duplicate['metrics']['attempted_model_calls']==0)
            audit=client.get(base+'/audit');audit.raise_for_status()
            check('verified_intake_audit',audit.json()['verified'] and any(e['action']=='intake_reused' for e in audit.json()['events']))
            check('original_version_unchanged',client.get(base,params={'version':1}).json()['findings'][0]['human_review']['decision']=='pending')
        finally:
            seen=set()
            for session,auth,case in owned:
                if case in seen:continue
                seen.add(case)
                check('delete_owned_synthetic_case',session.delete('/api/cases/'+case,headers=auth).status_code==200)
            if headers:client.post('/api/platform/auth/logout',headers=headers)
            if peer_headers:peer.post('/api/platform/auth/logout',headers=peer_headers)
    return {'schema_version':1,'passed':True,'checked_at':datetime.now(timezone.utc).isoformat(),'base_url':ORIGIN,
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'checks':checks,
        'scope':'Two isolated synthetic guests only; saved-review reuse, source duplication, tenant denial and cleanup. No uploads, private account login, OCR or paid model calls.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',type=Path,default=ROOT/'work/hosted-ingestion-results.json')
    args=parser.parse_args();result=run();args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'passed':result['passed'],'checks':len(result['checks'])}))
