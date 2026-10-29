"""Smoke and sanity checks against an already running local HTTP server."""
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
with httpx.Client(base_url='http://127.0.0.1:8765',timeout=60) as client:
    assert client.get('/').status_code==200
    assert client.get('/api/health').json()['status']=='ok'
    for case,status,diff in [('clean','consistent',None),('contradiction','discrepancies','25.00'),('math_error','discrepancies','50.00'),('messy','review',None)]:
        files=[('files',(p.name,p.read_bytes(),'application/pdf')) for p in sorted((ROOT/'data'/'synthetic'/case).glob('*.pdf'))]
        response=client.post('/api/analyze',files=files)
        response.raise_for_status();report=response.json();base='/api/cases/'+report['id']
        try:
            assert report['status']==status
            if diff: assert report['findings'][0]['difference']==diff
            if case=='clean':assert report['findings']==[]
            if case=='messy':assert all(f['severity']=='review' for f in report['findings'])
            assert client.get(base+'/documents/doc1').content.startswith(b'%PDF-')
            assert client.get(base+'/export').json()==report
            assert client.get(base+'/export?format=md').status_code==200
            print(f'PASS {case}: {status}')
        finally:assert client.delete(base).status_code==200
print('HTTP smoke and sanity checks passed.')
