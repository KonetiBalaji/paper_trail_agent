"""Fixed low-volume security probes of the authorized synthetic production demo.

No arbitrary targets, genuine account login, private documents, model calls,
credential guessing, exploit payload execution or rate-limit flooding.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import httpx

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://paper-trail-agent.vercel.app'


def run(report):
    def check(name, condition):
        report['checks'].append({'check': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)
    with httpx.Client(base_url=ORIGIN, timeout=30, follow_redirects=False) as owner, \
            httpx.Client(base_url=ORIGIN, timeout=30, follow_redirects=False) as stranger:
        home = owner.get('/'); home.raise_for_status()
        expected = json.loads((ROOT/'vercel.json').read_text())['headers']
        for group in expected:
            if group['source'] in ('/', '/(.*)'):
                for header in group['headers']:
                    check('home_'+header['key'].lower(), home.headers.get(header['key']) == header['value'])
        check('provider_hsts', 'max-age=' in home.headers.get('Strict-Transport-Security', ''))
        for path in ('/.env', '/.env.production', '/.git/config', '/.git/HEAD',
                     '/storage/private/report.json', '/data/private/statement.pdf', '/app/main.py',
                     '/requirements-lock.txt', '/static/%2e%2e/.env'):
            response = owner.get(path)
            check('private_file_'+path, response.status_code in (400, 403, 404))
        response = owner.get('/api/cases')
        check('anonymous_case_history', response.status_code == 401)
        check('unauthorized_no_store', 'no-store' in response.headers.get('Cache-Control', ''))
        check('no_cross_origin_read_permission', 'access-control-allow-origin' not in response.headers)
        response = owner.post('/api/platform/demo/start', headers={'Origin': 'https://evil.invalid'})
        check('cross_origin_session_creation', response.status_code == 403)
        check('early_rejection_headers', response.headers.get('X-Content-Type-Options') == 'nosniff' and 'no-store' in response.headers.get('Cache-Control', ''))
        case = None; tokens = []
        try:
            for name, client in (('owner', owner), ('stranger', stranger)):
                response = client.post('/api/platform/demo/start'); response.raise_for_status()
                cookies = response.headers.get_list('set-cookie')
                check(name+'_secure_session', any(c.startswith('pta_session=') and 'HttpOnly' in c and 'Secure' in c and 'SameSite=strict' in c for c in cookies))
                check(name+'_demo_only', response.json()['role'] == 'demo')
                tokens.append(client.cookies['pta_csrf'])
            headers = {'X-CSRF-Token': tokens[0]}
            for label, attack_headers in (
                ('missing_csrf', {}), ('foreign_csrf', {'X-CSRF-Token': tokens[1]}),
                ('cross_origin_write', {**headers, 'Origin': 'https://evil.invalid'})):
                response = owner.post('/api/platform/demo/cases/clean', headers=attack_headers)
                check(label, response.status_code == 403)
            response = owner.post('/api/platform/demo/cases/clean', headers=headers); response.raise_for_status()
            case = '/api/cases/' + response.json()['id']
            for suffix in ('', '?version=1', '/audit', '/documents/doc1', '/documents/doc1/page/1',
                           '/search?q=principal', '/export?format=json', '/export?format=csv', '/ocr',
                           '/findings/F1/draft?version=1&revision=0'):
                response = stranger.get(case+suffix)
                check('cross_session_'+suffix, response.status_code == 404)
                check('private_rejection_no_store_'+suffix, 'no-store' in response.headers.get('Cache-Control', ''))
            for path in ('/api/platform/api-keys', '/api/platform/retention'):
                check('guest_denied_'+path, owner.get(path).status_code == 403)
            response = owner.post('/api/platform/jobs/eval', headers=headers)
            check('guest_cannot_schedule', response.status_code == 403)
            response = owner.get('/api/integrations/v1/cases/unknown')
            check('session_is_not_api_key', response.status_code == 401)
            response = owner.get('/api/platform/auth/me', headers={'Authorization': 'Bearer synthetic-invalid-token'})
            check('bearer_does_not_change_cookie_role', response.status_code == 200 and response.json()['role'] == 'demo')
            before = owner.get(case); before.raise_for_status()
            check('failed_writes_did_not_alter_report', before.json()['report_version'] == 1 and before.json()['status'] == 'consistent')
            owner.delete(case, headers=headers).raise_for_status(); case = None
            old_session = owner.cookies['pta_session']
            owner.post('/api/platform/auth/logout', headers=headers).raise_for_status()
            check('logout_revokes', owner.get('/api/platform/auth/me').status_code == 401)
            # Replay only this just-revoked synthetic token, never another user.
            owner.cookies.set('pta_session', old_session, domain='paper-trail-agent.vercel.app', path='/')
            check('revoked_cookie_replay', owner.get('/api/platform/auth/me').status_code == 401)
            owner.cookies.clear()
        finally:
            if case:
                owner.delete(case, headers={'X-CSRF-Token': owner.cookies.get('pta_csrf', '')}).raise_for_status()
            for client in (owner, stranger):
                if client.cookies.get('pta_csrf'):
                    client.post('/api/platform/auth/logout', headers={'X-CSRF-Token': client.cookies['pta_csrf']}).raise_for_status()
    report['passed'] = all(row['passed'] for row in report['checks'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', default='work/hosted-security-results.json')
    args = parser.parse_args()
    report = {'schema_version': 1, 'passed': False, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'base_url': ORIGIN, 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'scope': 'Bounded HTTP boundary probes using two disposable synthetic guests. No independent penetration test, browser CSP execution, load testing, cloud/IAM review, private documents or paid calls.',
              'checks': [], 'input_sha256': {name: hashlib.sha256((ROOT/name).read_text().encode()).hexdigest()
                                             for name in ('vercel.json', 'scripts/hosted_security_smoke.py')}}
    try:
        run(report)
    finally:
        output = Path(args.report); output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8', newline='\n')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks'])}))
