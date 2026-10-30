"""Verify the authorized hosted synthetic demo; never invokes paid model calls."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import httpx


def public_checks(base):
    """Inspect public responses for configured secret values without sending them."""
    from dotenv import dotenv_values
    root=Path(__file__).resolve().parents[1]
    secrets={**dotenv_values(root/'.env'),**dotenv_values(root/'.env.production')}
    values=[value for key,value in secrets.items() if value and len(value)>20
            and any(word in key for word in ('KEY','TOKEN','SECRET','PASSWORD','DATABASE_URL'))]
    responses=[httpx.get(base+path,timeout=60) for path in ('/','/static/app.js','/api/health','/api/platform/config')]
    for response in responses:response.raise_for_status()
    assert all(value not in response.text for value in values for response in responses),'Configured secret exposed in a public response'
    evals=httpx.get(base+'/api/evals',timeout=60);evals.raise_for_status()
    benchmark=httpx.get(base+'/api/benchmark',timeout=60);benchmark.raise_for_status()
    assert evals.json()['summary']['failed']==0
    assert benchmark.json()['summary']['failed']==0 and benchmark.json()['summary']['false_clean_count']==0
    return [{'check':'configured_secrets_absent_from_public_responses','passed':True},
            {'check':'hosted_evals_six_pass','passed':evals.json()['summary']['passed']==6},
            {'check':'hosted_benchmark_nineteen_pass','passed':benchmark.json()['summary']['passed']==19}]


def run(base):
    results=public_checks(base)
    def check(name,condition):
        results.append({'check':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
    with httpx.Client(base_url=base,timeout=60) as first,httpx.Client(base_url=base,timeout=60) as other:
        health=first.get('/api/health');config=first.get('/api/platform/config')
        check('https_health',health.status_code==200 and health.json()['status']=='ok')
        check('service_mode',config.status_code==200 and config.json()['mode']=='service')
        check('public_meta_disabled',config.json()['public_demo_live_meta'] is False)
        check('anonymous_history_denied',first.get('/api/cases').status_code==401)
        for client in (first,other):
            response=client.post('/api/platform/demo/start')
            check('isolated_guest_start',response.status_code==200 and response.json()['role']=='demo')
            cookies=response.headers.get_list('set-cookie')
            check('secure_session_cookie',any(c.startswith('pta_session=') and 'Secure' in c and 'HttpOnly' in c and 'SameSite=strict' in c for c in cookies))
        token=first.cookies.get('pta_csrf');headers={'X-CSRF-Token':token}
        check('csrf_required',first.post('/api/platform/demo/cases/clean').status_code==403)
        reports={}
        for name,status,count in (('clean','consistent',0),('contradiction','discrepancies',1),('math_error','discrepancies',1),('messy','review',0)):
            response=first.post('/api/platform/demo/cases/'+name,headers=headers);response.raise_for_status()
            report=response.json();reports[name]=report
            confirmed=[f for f in report['findings'] if f['severity']=='confirmed']
            check(name+'_outcome',report['status']==status and len(confirmed)==count)
            check(name+'_no_paid_calls',report['demo']['model_calls']==0 and report['agent'] is None)
            if name in ('contradiction','math_error'):
                check(name+'_difference',confirmed[0]['difference']==('25.00' if name=='contradiction' else '50.00'))
        report=reports['math_error'];case='/api/cases/'+report['id']
        check('cross_session_read_denied',other.get(case).status_code==404)
        check('anonymous_case_read_denied',httpx.get(base+case,timeout=30).status_code==401)
        finding=report['findings'][0];source=finding['sources'][-1]
        doc=next(d for d in report['documents'] if any(l['id']==source for l in d['lines']))
        page=first.get(case+'/documents/'+doc['id']+'/page/1',params={'source':source})
        check('highlighted_png',page.status_code==200 and page.content.startswith(b'\x89PNG'))
        raw=first.get(case+'/documents/'+doc['id'])
        check('original_pdf',raw.status_code==200 and raw.content.startswith(b'%PDF-'))
        update={'action':'note','note':'Hosted synthetic smoke: verified candidate total against source.','expected_revision':0}
        review=first.patch(case+'/findings/F1',headers=headers,json=update)
        check('review_saved',review.status_code==200 and review.json()['findings'][0]['human_review']['revision']==1)
        reopened=first.get(case).json()
        check('review_reopened',reopened['findings'][0]['human_review']['revision']==1)
        check('machine_finding_preserved',all(reopened['findings'][0][k]==finding[k] for k in ('severity','message','difference','sources')))
        check('stale_review_rejected',first.patch(case+'/findings/F1',headers=headers,json=update).status_code==409)
        audit=first.get(case+'/audit')
        check('audit_chain',audit.status_code==200 and audit.json()['verified'])
        for format in ('json','md'):
            export=first.get(case+'/export',params={'format':format})
            check(format+'_export',export.status_code==200 and '50.00' in export.text)
        check('guest_jobs_denied',first.post('/api/platform/jobs/eval',headers=headers).status_code==403)
        sample=Path(__file__).resolve().parents[1]/'data/synthetic/clean/statement_A.pdf'
        for mode in ('local','meta','auto'):
            upload=first.post('/api/analyze',headers=headers,files={'files':('synthetic.pdf',sample.read_bytes(),'application/pdf')},data={'mode':mode})
            check('guest_'+mode+'_upload_denied',upload.status_code==403)
        oversized=first.post('/api/analyze',headers=headers,content=b'x'*4_000_001)
        check('hosted_body_limit',oversized.status_code==413)
        # Exactly 12 fixture analyses per session; the 13th must be rejected.
        for _ in range(8):
            response=first.post('/api/platform/demo/cases/clean',headers=headers)
            check('within_guest_quota',response.status_code==200)
        check('guest_quota_enforced',first.post('/api/platform/demo/cases/clean',headers=headers).status_code==429)
        check('logout',first.post('/api/platform/auth/logout',headers=headers).status_code==200)
        check('logout_revoked',first.get(case).status_code==401)
        other.post('/api/platform/auth/logout',headers={'X-CSRF-Token':other.cookies.get('pta_csrf')})
    return {'base_url':base,'checked_at':datetime.now(timezone.utc).isoformat(),
            'scope':'Two new synthetic guest sessions; no private uploads, real customer documents or paid model calls.',
            'checks':results,'passed':all(r['passed'] for r in results)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--base-url',required=True)
    parser.add_argument('--report',default='work/hosted-smoke.json');args=parser.parse_args()
    if not args.base_url.startswith('https://'):parser.error('Use the authorized HTTPS production origin')
    result=run(args.base_url.rstrip('/'));path=Path(args.report);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'passed':result['passed'],'checks':len(result['checks'])}))
