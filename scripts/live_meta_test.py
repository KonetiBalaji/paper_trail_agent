"""Live Meta acceptance gate. Sends only the included synthetic PDFs."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app
from app.meta import configured


def main():
    if not configured():
        print('NOT RUN: Enter MODEL_API_KEY in the project .env file. No API key was found.')
        raise SystemExit(2)
    root=Path(__file__).resolve().parents[1]/'data'/'synthetic'
    with TestClient(app) as client:
        for case,expected in [('clean',0),('contradiction',1),('math_error',1),('messy',0)]:
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
                print('PASS live Meta:',case)
            finally:client.delete(base)

if __name__ == '__main__':
    main()
