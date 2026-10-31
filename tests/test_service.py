import json
from pathlib import Path
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from app import main,platform
from app.security import Security,Unauthorized,password_hash,password_matches
from app.repository import Repository

ROOT=Path(__file__).resolve().parents[1]/'data'/'synthetic'

@pytest.fixture
def service(tmp_path,monkeypatch):
    monkeypatch.setenv('PAPER_TRAIL_MODE','service')
    monkeypatch.setenv('DATABASE_URL','sqlite:///'+(tmp_path/'service.db').as_posix())
    monkeypatch.setenv('DATA_ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.delenv('VERCEL',raising=False);monkeypatch.delenv('MODEL_API_KEY',raising=False)
    repo,security=platform.runtime(tmp_path)
    security.create_user('admin@example.invalid','synthetic-password-123','team-a','admin')
    security.create_user('viewer@example.invalid','synthetic-password-123','team-a','viewer')
    security.create_user('other@example.invalid','synthetic-password-123','team-b','reviewer')
    with TestClient(main.app,base_url='https://testserver') as client:
        yield client,repo,security
    repo.close();platform._runtime.cache_clear()

def login(client,email='admin@example.invalid'):
    r=client.post('/api/platform/auth/login',json={'email':email,'password':'synthetic-password-123'})
    assert r.status_code==200,r.text
    return {'X-CSRF-Token':client.cookies['pta_csrf']}

def upload(client,headers=None):
    return client.post('/api/analyze',files=[('files',(p.name,p.read_bytes(),'application/pdf'))
        for p in sorted((ROOT/'contradiction').glob('*.pdf'))],headers=headers or {})

def test_draft_approval_version_workspace_and_read_only_viewer(service):
    client,repo,_=service;headers=login(client)
    report=upload(client,headers).json();base='/api/cases/'+report['id'];path=base+'/findings/F1/draft'
    assert client.get(path,params={'version':1,'revision':0}).status_code==409
    reviewed=client.patch(base+'/findings/F1',json={'action':'confirm','note':'Compared both sources','expected_revision':0,'expected_case_version':1},headers=headers).json()
    version=reviewed['report_version']
    response=client.get(path,params={'version':version,'revision':1})
    assert response.status_code==200 and response.json()['difference']=='25.00'
    assert client.get(path,params={'version':1,'revision':1}).status_code==409
    login(client,'viewer@example.invalid')
    assert client.get(path,params={'version':version,'revision':1}).status_code==200
    login(client,'other@example.invalid')
    assert client.get(path,params={'version':version,'revision':1}).status_code==404
    client.cookies.clear()
    assert client.get(path,params={'version':version,'revision':1}).status_code==401

def test_service_requires_auth_no_legacy_bypass(service):
    client,repo,_=service
    assert client.get('/api/cases').status_code==401
    assert upload(client).status_code==401
    assert client.get('/api/platform/cases').status_code==401

def test_login_cookie_csrf_and_logout(service):
    client,_,_=service;headers=login(client)
    assert client.get('/api/platform/auth/me').json()['role']=='admin'
    assert 'httponly' in client.post('/api/platform/auth/login',json={'email':'admin@example.invalid','password':'synthetic-password-123'}).headers['set-cookie'].lower()
    headers={'X-CSRF-Token':client.cookies['pta_csrf']}
    assert upload(client).status_code==403
    assert upload(client,headers).status_code==200
    assert client.post('/api/platform/auth/logout',headers=headers).status_code==200
    assert client.get('/api/cases').status_code==401

def test_encrypted_service_case_review_versions_and_source(service):
    client,repo,_=service;headers=login(client)
    r=upload(client,headers);assert r.status_code==200,r.text
    report=r.json();case=report['id'];base='/api/cases/'+case
    assert client.get(base).json()==report
    assert client.get('/api/cases',params={'q':'DEMO-001','status':'discrepancies'}).json()['total_in_window']==1
    assert client.get(base+'/documents/doc1').content.startswith(b'%PDF-')
    assert client.get(base+'/documents/doc1/page/1').content.startswith(b'\x89PNG')
    changed=client.patch(base+'/findings/F1',json={'action':'confirm','note':'Reviewed','expected_revision':0},headers=headers)
    assert changed.status_code==200,changed.text
    assert client.get(base,params={'version':1}).json()==report
    exported=client.get(base+'/export',params={'version':1}).json()
    assert exported['privacy']['redacted'] and exported['calculations']==report['calculations']
    assert exported['findings'][0]['human_review']['revision']==0
    assert client.get(base+'/audit').json()['verified']
    assert 'Reviewed' in client.get(base+'/export?format=md').text
    assert client.delete(base,headers=headers).status_code==200
    assert client.get(base).status_code==404

def test_workspace_isolation_and_viewer_permissions(service):
    client,_,_=service;headers=login(client);report=upload(client,headers).json();base='/api/cases/'+report['id']
    client.cookies.clear();headers=login(client,'viewer@example.invalid')
    assert client.get(base).status_code==200
    assert upload(client,headers).status_code==403
    assert client.patch(base+'/findings/F1',json={'action':'reject','expected_revision':0},headers=headers).status_code==403
    assert client.delete(base,headers=headers).status_code==403
    client.cookies.clear();headers=login(client,'other@example.invalid')
    assert client.get(base).status_code==404 and client.get(base+'/documents/doc1').status_code==404
    assert client.get('/api/cases').json()['cases']==[]

def test_cross_origin_write_and_invalid_login(service):
    client,_,_=service
    assert client.post('/api/platform/auth/login',json={'email':'admin@example.invalid','password':'wrong'}).status_code==401
    r=client.post('/api/platform/auth/login',json={'email':'admin@example.invalid','password':'synthetic-password-123'},headers={'Origin':'https://evil.invalid'})
    assert r.status_code==403

def test_shared_login_limit(service):
    client,_,_=service
    for _ in range(10):assert client.post('/api/platform/auth/login',json={'email':'no@example.invalid','password':'wrong'}).status_code==401
    assert client.post('/api/platform/auth/login',json={'email':'no@example.invalid','password':'wrong'}).status_code==429

def test_service_body_limit_before_parsing(service):
    client,_,_=service
    r=client.post('/api/analyze',content=b'x'*(16*1024*1024+1),headers={'Content-Type':'application/octet-stream'})
    assert r.status_code==413

def test_admin_cannot_provision_other_workspace(service):
    client,_,_=service;headers=login(client)
    data={'email':'new@example.invalid','password':'synthetic-password-123','workspace':'team-b','role':'reviewer'}
    assert client.post('/api/platform/users',json=data,headers=headers).status_code==403
    data['workspace']='team-a'
    assert client.post('/api/platform/users',json=data,headers=headers).status_code==200

def test_disable_account_revokes_sessions(service):
    client,_,security=service;headers=login(client,'other@example.invalid')
    principal=security.authenticate(client.cookies['pta_session'])
    security.disable('team-b','admin-actor',principal.id)
    assert client.get('/api/platform/auth/me').status_code==401

def test_missing_service_secrets_fail_closed(tmp_path,monkeypatch):
    monkeypatch.setenv('PAPER_TRAIL_MODE','service');monkeypatch.delenv('DATABASE_URL',raising=False)
    monkeypatch.delenv('DATA_ENCRYPTION_KEY',raising=False)
    with TestClient(main.app) as client:
        r=client.get('/api/platform/cases');assert r.status_code==503
    assert not list(tmp_path.glob('*.key'))

def test_passwords_are_salted_and_verified():
    first=password_hash('synthetic-password-123');second=password_hash('synthetic-password-123')
    assert first!=second and password_matches('synthetic-password-123',first)
    assert not password_matches('wrong',first)
    with pytest.raises(ValueError):password_hash('short')

@pytest.mark.parametrize('sslmode',['disable','allow','prefer',''])
def test_vercel_requires_tls_before_database_connect(monkeypatch,tmp_path,sslmode):
    monkeypatch.setenv('VERCEL','1');monkeypatch.setenv('DATABASE_URL','postgresql://synthetic:fake@localhost/not-used?sslmode='+sslmode)
    monkeypatch.setenv('DATA_ENCRYPTION_KEY',Fernet.generate_key().decode())
    with pytest.raises(Exception) as exc:platform.runtime(tmp_path)
    assert getattr(exc.value,'status_code',None)==503

def test_invalid_encryption_key_fails_closed(monkeypatch,tmp_path):
    monkeypatch.setenv('PAPER_TRAIL_MODE','service');monkeypatch.setenv('DATABASE_URL','sqlite:///'+(tmp_path/'bad.db').as_posix())
    monkeypatch.setenv('DATA_ENCRYPTION_KEY','invalid-key')
    with pytest.raises(Exception) as exc:platform.runtime(tmp_path)
    assert getattr(exc.value,'status_code',None)==503

def test_service_review_conflict_and_history_filter(service):
    client,_,_=service;headers=login(client);report=upload(client,headers).json();base='/api/cases/'+report['id']
    body={'action':'reject','note':'Check source version','expected_revision':0}
    assert client.patch(base+'/findings/F1',json=body,headers=headers).status_code==200
    assert client.patch(base+'/findings/F1',json=body,headers=headers).status_code==409
    assert client.get('/api/cases',params={'decision':'rejected'}).json()['total_in_window']==1
    assert client.get('/api/cases',params={'decision':'pending'}).json()['total_in_window']==0

def test_queue_api_and_worker_are_workspace_scoped(service):
    from app.worker import run_once
    client,repo,_=service;headers=login(client)
    r=client.post('/api/platform/jobs/eval',headers=headers);assert r.status_code==202
    job=r.json()['job_id'];assert client.get('/api/platform/jobs/'+job).json()['state']=='queued'
    assert run_once(repo)
    assert client.get('/api/platform/jobs/'+job).json()['result']['summary']['passed']==6
    client.cookies.clear();login(client,'other@example.invalid')
    assert client.get('/api/platform/jobs/'+job).status_code==404

def test_rendering_enforces_pixel_bounds():
    import io
    from reportlab.pdfgen import canvas
    from PIL import Image
    buffer=io.BytesIO();pdf=canvas.Canvas(buffer,pagesize=(10000,10000));pdf.drawString(30,9900,'Synthetic oversized page');pdf.save()
    raw=platform.render_page(buffer.getvalue(),{'lines':[]},1,'')
    image=Image.open(io.BytesIO(raw))
    assert image.width<=1000 and image.height<=1400 and len(raw)<4_500_000

def demo(client):
    response=client.post('/api/platform/demo/start')
    assert response.status_code==200,response.text
    assert response.json()['role']=='demo'
    return {'X-CSRF-Token':client.cookies['pta_csrf']}

@pytest.mark.parametrize('fixture,status,difference',[('clean','consistent',None),('contradiction','discrepancies','25.00'),('math_error','discrepancies','50.00'),('messy','review',None)])
def test_public_demo_cases_are_real_and_grounded(service,fixture,status,difference):
    client,repo,_=service;headers=demo(client)
    result=client.post('/api/platform/demo/cases/'+fixture,headers=headers)
    assert result.status_code==200,result.text
    report=result.json();assert report['status']==status
    assert report['demo']['model_calls']==0
    assert all(event['kind']!='model_call' for event in report['trace'])
    if difference:assert [f['difference'] for f in report['findings'] if f['severity']=='confirmed']==[difference]
    assert client.get('/api/cases/'+report['id']).json()==report
    assert client.get('/api/cases/'+report['id']+'/documents/doc1/page/1').content.startswith(b'\x89PNG')
    if report['findings']:
        result=client.patch('/api/cases/'+report['id']+'/findings/F1',json={'action':'note','note':'Synthetic review','expected_revision':0},headers=headers)
        assert result.status_code==200,result.text
        assert 'Synthetic review' in client.get('/api/cases/'+report['id']+'/export?format=md').text
    assert client.get('/api/cases/'+report['id']+'/audit').json()['verified']

def test_public_demo_cannot_upload_call_models_queue_jobs_or_administer(service,monkeypatch):
    client,_,_=service;headers=demo(client)
    def forbidden(*args,**kwargs):raise AssertionError('Public demo called a provider')
    monkeypatch.setattr(main.meta,'extract',forbidden)
    assert upload(client,headers).status_code==403
    assert client.post('/api/platform/jobs/eval',headers=headers).status_code==403
    assert client.post('/api/platform/users',json={'email':'new@example.invalid','password':'synthetic-password-123','workspace':'x','role':'admin'},headers=headers).status_code==403
    assert client.post('/api/platform/demo/cases/unknown',headers=headers).status_code==404
    assert client.post('/api/platform/demo/cases/clean').status_code==403

def test_demo_sessions_are_isolated_and_logout_revokes_token(service):
    client,_,security=service;headers=demo(client)
    token=client.cookies['pta_session'];csrf=client.cookies['pta_csrf']
    case=client.post('/api/platform/demo/cases/contradiction',headers=headers).json()['id']
    demo(client)
    assert client.get('/api/cases/'+case).status_code==404
    assert client.get('/api/cases').json()['cases']==[]
    client.cookies.set('pta_session',token,domain='testserver.local',path='/')
    client.cookies.set('pta_csrf',csrf,domain='testserver.local',path='/')
    assert client.get('/api/cases/'+case).status_code==200
    assert client.post('/api/platform/auth/logout',headers={'X-CSRF-Token':csrf}).status_code==200
    with pytest.raises(Unauthorized):security.authenticate(token)

def test_demo_rate_limit_and_token_tampering(service):
    client,repo,security=service;headers=demo(client)
    token=client.cookies['pta_session']
    with pytest.raises(Unauthorized):security.authenticate(token[:-5]+'badxx')
    for _ in range(12):assert client.post('/api/platform/demo/cases/clean',headers=headers).status_code==200
    assert client.post('/api/platform/demo/cases/clean',headers=headers).status_code==429

def test_demo_retention_purges_only_guest_synthetic_cases(service):
    import time
    from sqlalchemy import update
    from app.repository import cases
    client,repo,_=service
    owner_headers=login(client);private=upload(client,owner_headers).json()['id']
    headers=demo(client);guest=client.post('/api/platform/demo/cases/clean',headers=headers).json()['id']
    with repo.transaction() as connection:
        connection.execute(update(cases).values(created_at='2020-01-01T00:00:00+00:00'))
    assert repo.expire_demo_data()==1
    assert client.get('/api/cases/'+guest).status_code==404
    login(client)
    assert client.get('/api/cases/'+private).status_code==200
