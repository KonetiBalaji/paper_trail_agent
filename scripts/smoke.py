"""Smoke and sanity checks against an already running local HTTP server."""
from pathlib import Path
import httpx
import argparse

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base-url',default='http://127.0.0.1:8765')
args=parser.parse_args()
with httpx.Client(base_url=args.base_url,timeout=60) as client:
    assert client.get('/').status_code==200
    assert client.get('/api/health').json()['status']=='ok'
    evaluation=client.get('/api/evals');evaluation.raise_for_status()
    assert evaluation.json()['summary']['passed']==6 and evaluation.json()['model_calls']==0
    print('PASS offline Evals API: 6/6')
    for case,status,diff in [('clean','consistent',None),('contradiction','discrepancies','25.00'),('math_error','discrepancies','50.00'),('messy','review',None)]:
        files=[('files',(p.name,p.read_bytes(),'application/pdf')) for p in sorted((ROOT/'data'/'synthetic'/case).glob('*.pdf'))]
        response=client.post('/api/analyze',files=files)
        response.raise_for_status();report=response.json();base='/api/cases/'+report['id']
        try:
            assert report['status']==status
            assert report['trace'] and all('validation' in event for event in report['trace'])
            if diff: assert report['findings'][0]['difference']==diff
            if case=='clean':assert report['findings']==[]
            if case=='messy':assert all(f['severity']=='review' for f in report['findings'])
            assert client.get(base+'/documents/doc1').content.startswith(b'%PDF-')
            exported=client.get(base+'/export').json()
            assert exported['privacy']['redacted'] and exported['calculations']==report['calculations']
            assert exported['status']==report['status']
            assert client.get(base+'/export?format=md').status_code==200
            if report['findings']:
                finding=report['findings'][0]
                review=client.patch(base+'/findings/'+finding['id'],json={
                    'action':'note','note':'Smoke review persisted','expected_revision':0})
                review.raise_for_status()
                reopened=client.get(base).json()
                assert reopened['findings'][0]['human_review']['history'][0]['note']=='Smoke review persisted'
                assert reopened['status']==report['status'] and reopened['calculations']==report['calculations']
                assert 'Smoke review persisted' in client.get(base+'/export?format=md').text
                assert reopened['trace'][-1]['kind']=='human_review'
            print(f'PASS {case}: {status}')
        finally:assert client.delete(base).status_code==200
print('HTTP smoke and sanity checks passed.')
