"""Fixed synthetic guest check of the authorized hosted draft workflow."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone
import httpx

ROOT = Path(__file__).resolve().parents[1]


def run(base):
    checks = []
    def check(name, condition):
        checks.append({'check': name, 'passed': bool(condition)})
        if not condition: raise AssertionError(name)
    with httpx.Client(base_url=base, timeout=30) as client:
        remote = client.get('/static/app.js'); remote.raise_for_status()
        check('served_frontend_matches', remote.text.replace('\r\n', '\n') == (ROOT/'app/static/app.js').read_text(encoding='utf-8'))
        start = client.post('/api/platform/demo/start'); start.raise_for_status()
        check('synthetic_guest', start.json()['role'] == 'demo')
        headers = {'X-CSRF-Token': client.cookies['pta_csrf']}
        check('guest_key_list_denied',client.get('/api/platform/api-keys').status_code==403)
        check('guest_key_creation_denied',client.post('/api/platform/api-keys',json={'label':'Fictional denied request','scopes':['cases:read']},headers=headers).status_code==403)
        check('cookie_cannot_authorize_integration',client.get('/api/integrations/v1/cases/unknown').status_code==401)
        case = None
        try:
            response = client.post('/api/platform/demo/cases/math_error', headers=headers); response.raise_for_status()
            report = response.json(); case = '/api/cases/' + report['id']
            csv=client.get(case+'/export?format=csv');csv.raise_for_status()
            check('csv_exact_finding','3300.00,3350.00,50.00' in csv.text and 'DEMO-001' not in csv.text)
            worksheet=client.get(case+'/export?format=accounting_csv');worksheet.raise_for_status()
            check('loan_accounting_has_no_invented_transactions',len(worksheet.text.strip().splitlines())==1 and 'review_required' in worksheet.text)
            path = case + '/findings/F1/draft'
            check('pending_draft_blocked', client.get(path, params={'version':1,'revision':0}).status_code == 409)
            response = client.patch(case+'/findings/F1', json={'action':'confirm','note':'Fictional hosted draft smoke; checked source total.','expected_revision':0,'expected_case_version':1}, headers=headers)
            response.raise_for_status(); reviewed = response.json()
            for kind in ('lender_enquiry','statement_dispute'):
                response = client.get(path, params={'version':reviewed['report_version'],'revision':1,'kind':kind})
                response.raise_for_status(); draft = response.json()
                check(kind+'_verified_total', draft['difference']=='50.00' and '3300.00 USD; statement says 3350.00 USD' in draft['text'])
                check(kind+'_manual_only', not draft['sent'] and draft['requires_final_human_review'] and draft['delivery']=='manual_only')
                check(kind+'_grounded_sources', [s['source_id'] for s in draft['sources']] == reviewed['findings'][0]['sources'])
                check(kind+'_redacted', 'DEMO-001' not in draft['text'] and draft['privacy']['redacted'])
                check(kind+'_no_cache', response.headers.get('cache-control') == 'no-store')
            response = client.patch(case+'/findings/F1', json={'action':'reject','note':'Fictional stale-draft guard check.','expected_revision':1,'expected_case_version':reviewed['report_version']}, headers=headers)
            response.raise_for_status(); rejected = response.json()
            check('stale_snapshot_blocked', client.get(path, params={'version':reviewed['report_version'],'revision':1}).status_code == 409)
            check('rejected_draft_blocked', client.get(path, params={'version':rejected['report_version'],'revision':2}).status_code == 409)
            client.delete(case, headers=headers).raise_for_status(); case = None
            response = client.post('/api/platform/demo/cases/contradiction', headers=headers); response.raise_for_status()
            report = response.json(); case = '/api/cases/' + report['id']
            response = client.patch(case+'/findings/F1', json={'action':'confirm','note':'Fictional hosted check of both interest lines.','expected_revision':0,'expected_case_version':1}, headers=headers)
            response.raise_for_status(); reviewed = response.json()
            response = client.get(case+'/findings/F1/draft', params={'version':reviewed['report_version'],'revision':1})
            response.raise_for_status(); draft = response.json()
            check('interest_difference_exact', draft['difference'] == '25.00')
            check('both_interest_sources', len(draft['sources']) == 2 and [s['source_id'] for s in draft['sources']] == reviewed['findings'][0]['sources'])
            check('both_interest_amounts', '100.00' in draft['text'] and '125.00' in draft['text'])
        finally:
            if case: client.delete(case, headers=headers).raise_for_status()
            client.post('/api/platform/auth/logout', headers=headers).raise_for_status()
    return {'passed': True, 'checked_at': datetime.now(timezone.utc).isoformat(), 'base_url': base,
            'scope':'One disposable synthetic guest; real hosted APIs and served JS hash. No private uploads, paid calls, sending, payments or browser-rendering proof.',
            'application_commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'source_sha256': {p:hashlib.sha256((ROOT/p).read_text(encoding='utf-8').encode()).hexdigest()
                              for p in ('app/main.py','app/platform.py','app/drafts.py','app/integrations.py','app/security.py','app/exports.py','app/repository.py','app/privacy.py','app/static/app.js')},
            'checks': checks}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True); parser.add_argument('--report', default='work/hosted-draft-results.json')
    args = parser.parse_args()
    if args.base_url.rstrip('/') != 'https://paper-trail-agent.vercel.app':
        parser.error('Use only the authorized Paper Trail Agent production origin')
    result = run(args.base_url.rstrip('/')); output=Path(args.report); output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'checks':len(result['checks'])}))
