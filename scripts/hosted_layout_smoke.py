"""Verify only the authorized hosted synthetic reviewed-layout demo; no model calls."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import httpx

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://paper-trail-agent.vercel.app'


def run():
    checks = []
    def check(name, condition):
        checks.append({'check': name, 'passed': bool(condition)})
        if not condition: raise AssertionError(name)
    expected = json.loads((ROOT / 'data/layout_registry.json').read_text())['report_sha256']
    with httpx.Client(base_url=ORIGIN, timeout=60) as client:
        response = client.get('/api/layouts'); response.raise_for_status(); status = response.json()
        check('active_source_bound_registry', status['status'] == 'active')
        check('exact_deployed_receipt', status['receipt_sha256'] == expected)
        check('full_corpus_count', status['corpus_cases'] == 44)
        check('three_reviewed_native_layouts', {r['id'] for r in status['layouts']} == {'cedar_capital_v1', 'cedar_movement_v1', 'spanish_loan_v1'}
              and all(r['max_pages'] == 1 and not r['ocr_supported'] and r['review_kind'] == 'assistant' for r in status['layouts']))
        check('status_does_not_create_session', not client.cookies)
        response = client.post('/api/platform/demo/start'); response.raise_for_status()
        check('isolated_synthetic_demo_role', response.json()['role'] == 'demo')
        headers = {'X-CSRF-Token': client.cookies.get('pta_csrf')}; owned = []
        try:
            for fixture, difference, computed in [('reviewed_math_error', '50.00', '2437.10'),
                ('reviewed_contradiction', '25.00', None), ('reviewed_bank_clean', None, '913.65')]:
                response = client.post('/api/platform/demo/cases/' + fixture, headers=headers)
                response.raise_for_status(); report = response.json(); owned.append(report['id'])
                confirmed = [r for r in report['findings'] if r['severity'] == 'confirmed']
                check(fixture + '_outcome', report['status'] == ('discrepancies' if difference else 'consistent')
                      and len(confirmed) == (1 if difference else 0))
                check(fixture + '_no_paid_model', report['demo']['model_calls'] == 0 and report['metrics']['attempted_model_calls'] == 0)
                check(fixture + '_receipt_provenance', all(d['layout_support']['promoted']
                      and d['layout_support']['receipt_sha256'] == expected and d['layout_support']['review_kind'] == 'assistant'
                      for d in report['documents']))
                if difference:
                    check(fixture + '_exact_difference', confirmed[0]['difference'] == difference)
                    lines = {line['id']: line for d in report['documents'] for line in d['lines']}
                    check(fixture + '_grounded_sources', bool(confirmed[0]['sources']) and all(s in lines for s in confirmed[0]['sources']))
                    source = confirmed[0]['sources'][0]; doc = next(d for d in report['documents'] if any(line['id'] == source for line in d['lines']))
                    page = lines[source]['page']
                    image = client.get(f"/api/cases/{report['id']}/documents/{doc['id']}/page/{page}", params={'source': source})
                    check(fixture + '_highlighted_original', image.status_code == 200 and image.headers.get('content-type') == 'image/png')
                if computed:
                    check(fixture + '_exact_calculator', any(c['computed'] == computed for c in report['calculations']))
                reread = client.get('/api/cases/' + report['id']); reread.raise_for_status()
                check(fixture + '_saved_provenance', reread.json()['documents'][0]['layout_support']['receipt_sha256'] == expected)
        finally:
            for case in owned:
                response = client.delete('/api/cases/' + case, headers=headers)
                check('delete_own_synthetic_case', response.status_code == 200)
            client.post('/api/platform/auth/logout', headers=headers)
    return {'schema_version': 1, 'passed': True, 'checked_at': datetime.now(timezone.utc).isoformat(),
            'base_url': ORIGIN, 'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'receipt_sha256': expected, 'checks': checks,
            'scope': 'One isolated fictional guest; fixed reviewed $50/$25/bank cases, source PNGs, saved provenance and self-cleanup. No uploads, real accounts or paid model calls.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--report', type=Path, default=ROOT / 'work/hosted-layout-results.json')
    args = parser.parse_args(); result = run(); args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'passed': result['passed'], 'checks': len(result['checks'])}))
