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


def test_http_duplicate_upload_reopens_latest_review_without_new_case(service):
    client,repo,_=service;headers=login(client)
    first=upload(client,headers).json();base='/api/cases/'+first['id']
    saved=client.patch(base+'/findings/F1',headers=headers,json={'action':'confirm','note':'Synthetic check',
        'expected_revision':0,'expected_case_version':1})
    assert saved.status_code==200
    retry=upload(client,headers)
    assert retry.status_code==200 and retry.json()['id']==first['id']
    assert retry.json()['intake_receipt']=={'created':False,'reused_analysis':True,'model_calls_this_request':0}
    assert retry.json()['findings'][0]['human_review']['decision']=='confirmed'
    assert retry.json()['report_version']==2 and repo.list_cases('team-a')['total_in_window']==1
    assert repo.audit('team-a')['events'][-1]['action']=='intake_reused'


def test_historical_endpoint_is_versioned_read_only_and_workspace_scoped(service):
    client,repo,_=service;headers=login(client)
    report=upload(client,headers).json();base='/api/cases/'+report['id']
    first=client.get(base+'/historical?version=1')
    assert first.status_code==200 and first.json()['report_version']==1
    assert first.json()['review'] and not first.json()['checks']
    assert client.patch(base+'/findings/F1',headers=headers,json={'action':'note','note':'History test',
        'expected_revision':0,'expected_case_version':1}).status_code==200
    assert client.get(base+'/historical').json()['report_version']==2
    assert client.get(base+'/historical?version=1').json()==first.json()
    login(client,'viewer@example.invalid')
    assert client.get(base+'/historical').status_code==200
    login(client,'other@example.invalid')
    assert client.get(base+'/historical').status_code==404
    assert client.get(base+'/historical?version=1').status_code==404
    client.post('/api/platform/auth/logout',headers={'X-CSRF-Token':client.cookies['pta_csrf']})
    assert client.get(base+'/historical').status_code==401

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
    assert report.pop('intake_receipt')=={'created':True,'reused_analysis':False,'model_calls_this_request':0}
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

@pytest.mark.parametrize('fixture,status,difference',[('clean','consistent',None),('contradiction','discrepancies','25.00'),('math_error','discrepancies','50.00'),('messy','review',None),('duplicate_document','review',None)])
def test_public_demo_cases_are_real_and_grounded(service,fixture,status,difference):
    client,repo,_=service;headers=demo(client)
    result=client.post('/api/platform/demo/cases/'+fixture,headers=headers)
    assert result.status_code==200,result.text
    report=result.json();assert report['status']==status
    assert report['demo']['model_calls']==0
    assert all(event['kind']!='model_call' for event in report['trace'])
    if difference:assert [f['difference'] for f in report['findings'] if f['severity']=='confirmed']==[difference]
    assert report.pop('intake_receipt')=={'created':True,'reused_analysis':False,'model_calls_this_request':0}
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
    from sqlalchemy import update,select,func
    from app.repository import cases,intake_sets,statement_sources
    client,repo,_=service
    owner_headers=login(client);private=upload(client,owner_headers).json()['id']
    headers=demo(client);guest=client.post('/api/platform/demo/cases/clean',headers=headers).json()['id']
    guest_workspace=client.get('/api/platform/auth/me').json()['workspace']
    with repo.transaction() as connection:
        connection.execute(update(cases).values(created_at='2020-01-01T00:00:00+00:00'))
    assert repo.expire_demo_data()==1
    assert client.get('/api/cases/'+guest).status_code==404
    with repo.engine.connect() as connection:
        for table in (intake_sets,statement_sources):
            assert connection.execute(select(func.count()).select_from(table).where(table.c.workspace==guest_workspace)).scalar_one()==0
    login(client)
    assert client.get('/api/cases/'+private).status_code==200


def test_demo_repeated_fixture_preserves_human_review(service):
    client,repo,_=service;headers=demo(client)
    first=client.post('/api/platform/demo/cases/math_error',headers=headers).json();base='/api/cases/'+first['id']
    reviewed=client.patch(base+'/findings/F1',headers=headers,json={'action':'confirm','note':'Synthetic original checked',
        'expected_revision':0,'expected_case_version':1})
    assert reviewed.status_code==200
    retry=client.post('/api/platform/demo/cases/math_error',headers=headers).json()
    assert retry['id']==first['id'] and retry['report_version']==2
    assert retry['intake_receipt']['reused_analysis'] and retry['intake_receipt']['model_calls_this_request']==0
    assert retry['findings'][0]['human_review']['decision']=='confirmed'


def test_prior_history_separate_pdf_uploads(service, monkeypatch):
    import io
    from reportlab.pdfgen import canvas
    from app.worker import run_once

    client, repo, _ = service
    headers = login(client)

    def upload_period(start, end, opening, closing):
        raw = io.BytesIO()
        pdf = canvas.Canvas(raw, invariant=True)
        lines = [
            'Historical rules: PTA-BANK-PERIOD-V1', 'Account: FICTIONAL-001',
            'Currency: USD', f'Period start: {start}', f'Period end: {end}',
            f'Opening balance: {opening}', 'Transaction count: 1',
            f'Transaction PAYMENT-1 | {end} | Amount: -100.00', f'Closing balance: {closing}',
        ]
        for index, line in enumerate(lines):
            pdf.drawString(40, 750 - index * 20, line)
        pdf.save()
        response = client.post('/api/analyze', headers=headers,
            files={'files': ('statement.pdf', raw.getvalue(), 'application/pdf')})
        assert response.status_code == 200, response.text
        return response.json()['id']

    earlier = upload_period('2026-09-01', '2026-09-30', '1000.00', '900.00')
    later = upload_period('2026-10-01', '2026-10-31', '950.00', '850.00')
    path = f'/api/cases/{later}/documents/doc1/historical'
    response = client.get(path)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['identity_verified'] and result['next_offset'] is None
    comparison, = result['comparisons']
    assert comparison['prior']['case_id'] == earlier
    assert comparison['pair']['difference'] == '50.00'
    job_ids = [event['payload']['job_id'] for event in repo.audit('team-a')['events']
               if event['action'] == 'job_queued' and event['payload']['kind'] == 'monitor']
    assert len(job_ids) == 2
    assert run_once(repo, kinds=['monitor']) and run_once(repo, kinds=['monitor'])
    assert repo.get_job('team-a', job_ids[-1])['result']['comparison_counts']['discrepancy'] == 1
    monitor = f'/api/cases/{later}/monitor'
    assert client.get(monitor).json()['worker_available'] is False
    worker_id = '9' * 32
    repo.touch_worker(worker_id, ['monitor'])
    assert client.get(monitor).json()['worker_available'] is True
    repo.retire_worker(worker_id)
    assert client.get(monitor).json()['worker_available'] is False
    entry, = client.get(monitor).json()['entries']
    entry_path = f"{monitor}/{entry['id']}"
    assert client.patch(entry_path, headers=headers, json={'action': 'resolve', 'expected_revision': 0}).status_code == 409
    for revision, action in enumerate(('review', 'resolve')):
        assert client.patch(entry_path, headers=headers, json={'action': action, 'expected_revision': revision}).status_code == 200
    saved, = client.get(monitor).json()['entries']
    assert saved['comparison'] == entry['comparison']
    assert [event['action'] for event in saved['history']] == ['review', 'resolve']
    closing, opening = saved['comparison']['pair']['carry_sources']
    assert closing.startswith(earlier + '/')
    for case_id, source, label in [(earlier, closing.split('/', 1)[1], 'Closing balance: 900.00'),
                                   (later, opening, 'Opening balance: 950.00')]:
        report = client.get(f'/api/cases/{case_id}').json()
        line = next(line for line in report['documents'][0]['lines'] if line['id'] == source)
        assert line['text'] == label
        image = client.get(f'/api/cases/{case_id}/documents/doc1/page/1', params={'source': source})
        assert image.status_code == 200 and image.headers['content-type'] == 'image/png'
    assert client.delete(f'/api/cases/{earlier}', headers=headers).status_code == 200
    assert client.get(monitor).json()['entries'] == []
    revised = upload_period('2026/10/01', '2026/10/31', '975.00', '875.00')
    assert run_once(repo, kinds=['monitor'])
    entries = client.get(f'/api/cases/{revised}/monitor').json()['entries']
    assert len({entry['id'] for entry in entries}) == 2
    pairs = {entry['comparison']['pair']['balance_field']: entry['comparison']['pair']
             for entry in entries}
    assert {field: pair['difference'] for field, pair in pairs.items()} == {
        'opening': '25.00', 'closing': '25.00',
    }
    for field, pair in pairs.items():
        prior_source, current_source = pair['balance_sources']
        assert prior_source.startswith(later + '/')
        for case, source, value in (
            (later, prior_source.split('/', 1)[1], pair['computed']),
            (revised, current_source, pair['stated']),
        ):
            lines = client.get(f'/api/cases/{case}').json()['documents'][0]['lines']
            assert next(line['text'] for line in lines if line['id'] == source) == (
                f'{field.capitalize()} balance: {value}'
            )
    latest = upload_period('2026-10-01', '2026-10-31', '990.00', '890.00')
    complete_job = repo.complete_job

    def delete_before_save(job_id, token, result, **kwargs):
        assert len(kwargs['detections']) == 4
        assert client.delete(f'/api/cases/{revised}', headers=headers).status_code == 200
        complete_job(job_id, token, result, **kwargs)
        saved_job = repo.get_job('team-a', job_id)
        assert saved_job['state'] == 'completed'
        assert saved_job['result']['findings_with_deleted_sources'] == 2

    with monkeypatch.context() as patch:
        patch.setattr(repo, 'complete_job', delete_before_save)
        assert run_once(repo, kinds=['monitor'])
    surviving = client.get(f'/api/cases/{latest}/monitor').json()['entries']
    assert len(surviving) == 2
    assert {item['comparison']['prior']['case_id'] for item in surviving} == {later}
    login(client, 'other@example.invalid')
    assert client.get(path).status_code == 404


def test_eval_candidate_is_versioned_and_reviewer_only(service):
    client, _, _ = service
    headers = login(client)
    report = upload(client, headers).json()
    base = '/api/cases/' + report['id'] + '/findings/F1'
    candidate = base + '/eval-candidate'
    assert client.get(candidate, params={'version': 1}).status_code == 409
    updated = client.patch(base, headers=headers, json={'action': 'reject', 'note': 'private-canary-note',
        'expected_revision': 0, 'expected_case_version': 1})
    assert updated.status_code == 200
    response = client.get(candidate, params={'version': 2})
    assert response.status_code == 200
    assert response.json()['review_decision'] == 'rejected'
    assert response.json()['admission'] == 'pending_independent_ground_truth_and_regression'
    assert 'private-canary-note' not in response.text
    assert client.get(candidate, params={'version': 1}).status_code == 409
    login(client, 'viewer@example.invalid')
    assert client.get(candidate, params={'version': 2}).status_code == 403
    login(client, 'other@example.invalid')
    assert client.get(candidate, params={'version': 2}).status_code == 404

def test_prior_statement_sources_deduplicate_before_paging(service):
    from app.repository import statement_sources

    client, repo, _ = service
    current = upload(client, login(client)).json()['id']
    with repo.transaction() as conn:
        conn.execute(statement_sources.delete().where(statement_sources.c.case_id == current))
        for case_id, digest, day in (
            ('first', 'a', 1), ('copy', 'a', 2), ('second', 'b', 3),
            ('self-copy', 'c', 4), (current, 'c', 5),
        ):
            conn.execute(statement_sources.insert().values(
                workspace='team-a', case_id=case_id, document_id='doc1',
                sha256=digest * 64, account_tag='account', identity=b'fixture',
                created_at=f'2026-09-0{day}T00:00:00+00:00',
            ))
    first = repo.prior_statement_sources('team-a', current, 'doc1', limit=1)
    assert [row['case_id'] for row in first['sources']] == ['first']
    assert first['next_offset'] == 1
    second = repo.prior_statement_sources('team-a', current, 'doc1', limit=1, offset=1)
    assert [row['case_id'] for row in second['sources']] == ['second']
    assert second['next_offset'] is None

    cursor_page = repo.prior_statement_sources('team-a', current, 'doc1', limit=1, by_digest=True)
    with repo.transaction() as conn:
        conn.execute(statement_sources.delete().where(statement_sources.c.case_id == 'first'))
    remaining = repo.prior_statement_sources(
        'team-a', current, 'doc1', limit=1, after=cursor_page['next_cursor'], by_digest=True,
    )
    assert [row['case_id'] for row in remaining['sources']] == ['second']

def test_monitor_claim_refreshes_worker_readiness(service, monkeypatch):
    from app import historical
    from app.repository import jobs
    from app.worker import run_once
    import time

    _, repo, _ = service
    worker_id = 'a' * 32
    with repo.transaction() as conn:
        conn.execute(jobs.insert().values(
            id='monitor-fixture', workspace='team-a', kind='monitor', state='queued',
            payload=repo.seal({'case_id': 'fixture', 'documents': ['doc1']}),
            created_at=time.time(),
        ))

    def compare(*args, **kwargs):
        assert repo.worker_status(now=time.time() + 100)['monitor']
        return {'comparisons': [], 'next_cursor': None}

    monkeypatch.setattr(historical, 'prior_case_history', compare)
    assert run_once(repo, kinds=['monitor'], worker_id=worker_id)
    assert repo.get_job('team-a', 'monitor-fixture')['state'] == 'completed'
