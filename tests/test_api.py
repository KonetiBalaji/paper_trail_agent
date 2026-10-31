from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient
from app import main,meta

ROOT=Path(__file__).resolve().parents[1]/'data'/'synthetic'

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'STORE',tmp_path)
    monkeypatch.delenv('MODEL_API_KEY',raising=False)
    with TestClient(main.app) as client: yield client

def upload(client,case='contradiction',mode='local'):
    return client.post('/api/analyze',files=[('files',(p.name,p.read_bytes(),'application/pdf'))
        for p in sorted((ROOT/case).glob('*.pdf'))],data={'mode':mode})

def test_local_draft_requires_approval_and_rejects_stale_review(client):
    report=upload(client,'math_error').json();base='/api/cases/'+report['id']
    path=base+'/findings/F1/draft'
    assert client.get(path,params={'version':0,'revision':0}).status_code==409
    assert client.patch(base+'/findings/F1',json={'action':'confirm','note':'Verified sources','expected_revision':0}).status_code==200
    result=client.get(path,params={'version':0,'revision':1})
    assert result.status_code==200 and result.json()['difference']=='50.00'
    assert result.headers['cache-control']=='no-store'
    assert client.get(path,params={'version':0,'revision':0}).status_code==409

@pytest.mark.parametrize('case,status',[('clean','consistent'),('contradiction','discrepancies'),('math_error','discrepancies'),('messy','review')])
def test_end_to_end(client,case,status):
    r=upload(client,case);assert r.status_code==200,r.text
    report=r.json();assert report['status']==status
    base='/api/cases/'+report['id']
    assert client.get(base).json()==report
    pdf=client.get(base+'/documents/doc1');assert pdf.status_code==200 and pdf.content.startswith(b'%PDF-')
    source=report['documents'][0]['lines'][0]['id']
    image=client.get(base+'/documents/doc1/page/1',params={'source':source})
    assert image.status_code==200 and image.content.startswith(b'\x89PNG')
    assert client.get(base+'/documents/doc1/page/99').status_code==404
    assert client.get(base+'/documents/fake/page/1').status_code==404
    assert client.get(base+'/search',params={'q':'T1 principal'}).json()
    exported=client.get(base+'/export').json()
    assert exported['privacy']['redacted'] and exported['calculations']==report['calculations']
    assert exported['status']==report['status'] and exported['documents'][0]['statement']['loan_id']=='[REDACTED]'
    checklist=client.get(base+'/export?format=md').text
    for f in exported['findings']:
        assert f['message'] in checklist
        for source in f['sources']:assert source in checklist
    assert client.delete(base).status_code==200
    assert client.get(base).status_code==404

def test_smoke_routes(client):
    assert client.get('/').status_code==200
    assert 'Paper Trail Agent' in client.get('/').text
    assert client.get('/static/app.js').status_code==200
    assert client.get('/api/health').json()['meta_configured'] is False

def test_bad_upload(client):
    r=client.post('/api/analyze',files={'files':('bad.pdf',b'fake','application/pdf')})
    assert r.status_code==422

def test_limits(client):
    assert client.post('/api/analyze',files=[('files',('a.pdf',b'%PDF-','application/pdf'))]*9).status_code==422
    assert client.post('/api/analyze',files={'files':('big.pdf',b'x'*(10*1024*1024+1),'application/pdf')}).status_code==413

def test_missing_key(client):
    r=upload(client,mode='meta');assert r.status_code==503 and 'MODEL_API_KEY' in r.text

def test_identifiers_and_export(client):
    assert client.get('/api/cases/not-a-case').status_code==404
    r=upload(client);base='/api/cases/'+r.json()['id']
    assert client.get(base+'/documents/not-a-doc').status_code==404
    assert client.get(base+'/export?format=exe').status_code==422

def test_meta_failure_not_silently_clean(client,monkeypatch):
    monkeypatch.setenv('MODEL_API_KEY','test-only')
    def fail(*args,**kwargs):raise meta.MetaError('Test provider unavailable')
    monkeypatch.setattr(meta,'request',fail)
    report=upload(client,mode='meta').json()
    assert report['status']=='review' and report['agent_error']
    assert all(f['severity']=='review' for f in report['findings'])

def test_meta_extraction_through_report(client,monkeypatch):
    from app.core import parse_statement
    monkeypatch.setenv('MODEL_API_KEY','test-only')
    calls=[]
    def provider(messages,tools=None):
        calls.append(messages)
        if tools is None:
            lines=json.loads(messages[1]['content'])
            return {'content':json.dumps(parse_statement({'lines':lines}))}
        return {'content':json.dumps({'summary':'Review the verified discrepancy.','checklist':['Compare original statements.'],'sources':[]})}
    monkeypatch.setattr(meta,'request',provider)
    response=upload(client,mode='meta')
    assert response.status_code==200
    report=response.json()
    assert len(calls)==3 and report['agent'] is not None
    assert report['findings'][0]['difference']=='25.00'
    assert report['mode']=='meta'

def test_agent_only_failure_is_review(client,monkeypatch):
    from app.core import parse_statement
    monkeypatch.setenv('MODEL_API_KEY','test-only')
    def provider(messages,tools=None):
        if tools:raise meta.MetaError('Test reasoning failure')
        return {'content':json.dumps(parse_statement({'lines':json.loads(messages[1]['content'])}))}
    monkeypatch.setattr(meta,'request',provider)
    report=upload(client,case='clean',mode='meta').json()
    assert report['status']=='review' and report['agent_error']

def test_hostile_filename_is_data(client):
    raw=(ROOT/'clean'/'statement_A.pdf').read_bytes()
    response=client.post('/api/analyze',files={'files':('../../evil.pdf',raw,'application/pdf')})
    assert response.status_code==200
    report=response.json()
    assert report['documents'][0]['name']=='evil.pdf'
    assert (main.STORE/report['id']/'doc1.pdf').is_file()

def test_bank_upload_export_and_source(client):
    import io
    from reportlab.pdfgen import canvas
    buf=io.BytesIO();pdf=canvas.Canvas(buf)
    for i,line in enumerate(['Account: CHECKING-1 Currency: USD','Statement period end: 2026-10-31',
        'Opening balance: 1000.00','Transaction T1 | 2026-10-02 | Amount: -25.00','Closing balance: 1000.00']):
        pdf.drawString(30,750-i*25,line)
    pdf.save()
    response=client.post('/api/analyze',files={'files':('bank.pdf',buf.getvalue(),'application/pdf')})
    assert response.status_code==200
    report=response.json();finding=report['findings'][0]
    assert finding['type']=='incorrect_closing_balance' and finding['difference']=='25.00'
    assert report['calculations'][0]['computed']=='975.00'
    base='/api/cases/'+report['id']
    assert 'doc1.pdf: closing balance is 25.00 USD too high.' in client.get(base+'/export?format=md').text
    assert client.get(base+'/documents/doc1/page/1',params={'source':finding['sources'][0]}).status_code==200
