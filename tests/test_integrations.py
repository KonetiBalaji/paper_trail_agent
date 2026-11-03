import csv
import io
import time
from pathlib import Path
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select,update
from app import main,platform
from app.repository import api_keys
from app.exports import csv_report,cell
from app.privacy import text

ROOT=Path(__file__).resolve().parents[1]/'data/synthetic'


@pytest.fixture
def service(tmp_path,monkeypatch):
    monkeypatch.setenv('PAPER_TRAIL_MODE','service');monkeypatch.setenv('DATABASE_URL','sqlite:///'+(tmp_path/'api.db').as_posix())
    monkeypatch.setenv('DATA_ENCRYPTION_KEY',Fernet.generate_key().decode());monkeypatch.delenv('VERCEL',raising=False)
    repo,security=platform.runtime(tmp_path)
    for email,workspace,role in [('admin','a','admin'),('other','b','admin'),('viewer','a','viewer')]:
        security.create_user(email+'@example.invalid','synthetic-api-password-123',workspace,role)
    with TestClient(main.app,base_url='https://testserver') as client:yield client,repo,security
    repo.close();platform._runtime.cache_clear()


def login(client,name='admin'):
    client.cookies.clear()
    result=client.post('/api/platform/auth/login',json={'email':name+'@example.invalid','password':'synthetic-api-password-123'})
    assert result.status_code==200
    return {'X-CSRF-Token':client.cookies['pta_csrf']}


def key(client,scopes=('cases:read','cases:submit')):
    headers=login(client)
    response=client.post('/api/platform/api-keys',json={'label':'Fictional accounting tool','scopes':list(scopes),'days':7},headers=headers)
    assert response.status_code==201,response.text
    return response.json(),headers


def submit(client,token,mode='local'):
    return client.post('/api/integrations/v1/cases',headers={'Authorization':'Bearer '+token},data={'mode':mode},
        files=[('files',(p.name,p.read_bytes(),'application/pdf')) for p in sorted((ROOT/'math_error').glob('*.pdf'))])


def test_api_scopes_redaction_and_no_cookie_or_billing_bypass(service):
    client,repo,_=service;issued,csrf=key(client);token=issued['token'];auth={'Authorization':'Bearer '+token}
    result=submit(client,token);assert result.status_code==201,result.text
    receipt=result.json();assert set(receipt)=={'id','status','report_version','mode','created'}
    assert receipt['created'] is True
    repeated=submit(client,token)
    assert repeated.status_code==200 and repeated.json()['id']==receipt['id'] and repeated.json()['created'] is False
    base='/api/integrations/v1/cases/'+receipt['id']
    report=client.get(base,headers=auth).json()
    assert report['findings'][0]['difference']=='50.00' and report['privacy']['redacted']
    assert report['documents'][0]['statement']['loan_id']=='[REDACTED]'
    assert client.get(base).status_code==401  # A valid cookie cannot replace an API key.
    assert submit(client,token,mode='meta').status_code==422
    read_only,_=key(client,('cases:read',));assert submit(client,read_only['token']).status_code==401
    write_only,_=key(client,('cases:submit',))
    assert client.get(base,headers={'Authorization':'Bearer '+write_only['token']}).status_code==401
    client.cookies.clear()
    assert client.get('/api/cases/'+receipt['id'],headers=auth).status_code==401
    assert client.patch('/api/cases/'+receipt['id']+'/findings/F1',headers=auth,json={'action':'confirm','note':'','expected_revision':0}).status_code==401
    assert repo.audit('a')['verified']


def test_keys_are_once_only_hashed_encrypted_expiring_revocable_and_isolated(service):
    client,repo,security=service;issued,csrf=key(client);token=issued['token'];identifier=issued['id']
    listing=client.get('/api/platform/api-keys').json()
    assert token not in str(listing) and 'token_hash' not in str(listing)
    with repo.engine.connect() as conn:
        row=conn.execute(select(api_keys).where(api_keys.c.id==identifier)).mappings().one()
    assert row['token_hash']==security.digest(token) and token.encode() not in row['label']
    assert b'Fictional accounting tool' not in row['label']
    assert text('Bearer '+token)=='Bearer [REDACTED_API_KEY]'
    receipt=submit(client,token).json();path='/api/integrations/v1/cases/'+receipt['id']
    foreign,_=key(client);login(client,'other')
    assert client.delete('/api/platform/api-keys/'+identifier,headers={'X-CSRF-Token':client.cookies['pta_csrf']}).status_code==404
    other_response=client.post('/api/platform/api-keys',json={'label':'Other workspace','scopes':['cases:read']},headers={'X-CSRF-Token':client.cookies['pta_csrf']})
    assert client.get(path,headers={'Authorization':'Bearer '+other_response.json()['token']}).status_code==404
    csrf=login(client)
    assert client.delete('/api/platform/api-keys/'+identifier,headers=csrf).status_code==200
    assert client.get(path,headers={'Authorization':'Bearer '+token}).status_code==401
    with repo.transaction() as conn:conn.execute(update(api_keys).where(api_keys.c.id==foreign['id']).values(expires_at=time.time()-1))
    assert client.get(path,headers={'Authorization':'Bearer '+foreign['token']}).status_code==401


def test_key_administration_requires_admin_csrf_and_limits(service):
    client,repo,_=service;csrf=login(client)
    assert client.post('/api/platform/api-keys',json={'label':'Tool','scopes':['cases:read']}).status_code==403
    assert client.post('/api/platform/api-keys',json={'label':'Tool','scopes':['cases:read'],'days':91},headers=csrf).status_code==422
    assert client.post('/api/platform/api-keys',json={'label':'Tool','scopes':['cases:read','cases:read']},headers=csrf).status_code==422
    for n in range(10):
        assert client.post('/api/platform/api-keys',json={'label':str(n),'scopes':['cases:read']},headers=csrf).status_code==201
    assert client.post('/api/platform/api-keys',json={'label':'11','scopes':['cases:read']},headers=csrf).status_code==429
    login(client,'viewer');assert client.get('/api/platform/api-keys').status_code==403
    assert client.post('/api/platform/api-keys',json={'label':'Tool','scopes':['cases:read']},headers={'X-CSRF-Token':client.cookies['pta_csrf']}).status_code==403


def test_bearer_quota_and_disabled_owner_are_enforced(service):
    client,repo,security=service;issued,_=key(client);result=submit(client,issued['token']).json()
    path='/api/integrations/v1/cases/'+result['id'];auth={'Authorization':'Bearer '+issued['token']}
    for _ in range(59):repo.consume('api-minute:'+issued['id'],60,60)
    assert client.get(path,headers=auth).status_code==429
    # A different key is invalidated immediately when its owner is disabled.
    issued,_=key(client)
    owner=security.authenticate(client.cookies['pta_session'])
    security.disable('a','test-admin',owner.id)
    assert client.get(path,headers={'Authorization':'Bearer '+issued['token']}).status_code==401


def test_csv_has_exact_values_and_neutralizes_text_formulas(service):
    client,_,_=service;issued,_=key(client);receipt=submit(client,issued['token']).json();base='/api/cases/'+receipt['id']
    response=client.get(base+'/export?format=csv');assert response.status_code==200 and response.headers['cache-control']=='no-store'
    rows=list(csv.DictReader(io.StringIO(response.text.lstrip('\ufeff'))))
    finding=next(r for r in rows if r['record_type']=='finding')
    assert (finding['computed'],finding['stated'],finding['difference'])==('3300.00','3350.00','50.00')
    assert 'DEMO-001' not in response.text
    for value in ('=HYPERLINK("https://example.invalid")',' +cmd','\t@SUM(1)','-formula'):
        assert cell(value).startswith("'")
    assert cell('-25.00',numeric=True)=='-25.00'
    from scripts.generate_bank_fixtures import generate
    import tempfile
    from fastapi import UploadFile
    with tempfile.TemporaryDirectory() as folder:
        raw=generate(Path(folder))['bank_clean'].read_bytes()
    report=main.analyze_files([UploadFile(filename='fictional.pdf',file=io.BytesIO(raw))],persist=False)
    rows=list(csv.DictReader(io.StringIO(csv_report(report,accounting=True).lstrip('\ufeff'))))
    assert len(rows)==2 and all(r['review_required']=='yes' and r['currency']=='USD' for r in rows)
    assert sum(float(r['amount']) for r in rows)==-25.0
    report['documents'][0]['statement']['transactions'][0]['id']='=DANGEROUS()'
    assert "'=DANGEROUS()" in csv_report(report,accounting=True)


def test_email_intake_authentication_privacy_and_cross_channel_dedup(service):
    from email.message import EmailMessage

    client, repo, _ = service
    issued, _ = key(client)
    auth = {'Authorization': 'Bearer ' + issued['token']}
    message = EmailMessage()
    message['From'] = 'private-sender@example.invalid'
    message['Subject'] = 'Private subject canary'
    message.set_content('Private body canary')
    endpoint = '/api/integrations/v1/email'

    def send(headers):
        return client.post(endpoint, headers=headers,
                           files={'message': ('private-name.eml', message.as_bytes(), 'message/rfc822')})

    assert send({}).status_code == 401
    assert send(auth).status_code == 422
    for path in sorted((ROOT / 'math_error').glob('*.pdf')):
        message.add_attachment(path.read_bytes(), maintype='application', subtype='pdf', filename='private-name.pdf')
    result = send(auth)
    assert result.status_code == 201, result.text
    case_id = result.json()['id']
    assert repo.get_case('a', case_id)['ingestion']['origin'] == 'email'
    exported = client.get('/api/integrations/v1/cases/' + case_id, headers=auth)
    assert exported.status_code == 200
    for value in ('private-sender', 'Private subject canary', 'Private body canary', 'private-name'):
        assert value not in exported.text
    repeated = submit(client, issued['token'])
    assert repeated.status_code == 200 and repeated.json()['id'] == case_id
    read_key, _ = key(client, ('cases:read',))
    assert send({'Authorization': 'Bearer ' + read_key['token']}).status_code == 401
