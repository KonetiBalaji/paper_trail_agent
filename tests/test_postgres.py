"""PostgreSQL integration gate; uses disposable isolated schemas, never user data."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from app.repository import Repository,Conflict,Missing,LimitExceeded
from app.security import Security,Unauthorized

@pytest.fixture
def postgres():
    raw=os.getenv('TEST_DATABASE_URL')
    if not raw:pytest.skip('Dedicated TEST_DATABASE_URL not configured')
    url=make_url(raw).set(drivername='postgresql+psycopg')
    name='pta_test_'+uuid.uuid4().hex
    admin=create_engine(url,hide_parameters=True)
    with admin.begin() as conn:conn.execute(text('CREATE SCHEMA '+name))
    isolated=url.update_query_dict({'options':'-csearch_path='+name})
    key=Fernet.generate_key();repo=Repository(isolated.render_as_string(hide_password=False),key)
    try:yield repo,isolated,key
    finally:
        repo.close()
        with admin.begin() as conn:conn.execute(text('DROP SCHEMA '+name+' CASCADE'))
        admin.dispose()

def sample():
    return {'id':uuid.uuid4().hex,'status':'review','documents':[{'id':'doc1','name':'synthetic.pdf','statement':{'loan_id':'DEMO-001','period_end':'2026-10-31'}}],
        'findings':[{'id':'F1','severity':'review','message':'Synthetic review','sources':[],
            'human_review':{'decision':'pending','revision':0,'history':[]}}],'calculations':[],'trace':[]}

def test_postgres_roundtrip_review_replay_isolation_delete(postgres):
    repo,_,_=postgres;report=sample();repo.create_case('team-a','alice',report,[b'%PDF-synthetic'])
    assert repo.get_document('team-a',report['id'],'doc1')==b'%PDF-synthetic'
    assert repo.list_cases('team-a',query='DEMO-001')['total_in_window']==1
    with pytest.raises(Missing):repo.get_case('other-team',report['id'])
    reviewed=repo.review('team-a','reviewer',report['id'],'F1','confirm','Checked',0)
    assert reviewed['findings'][0]['human_review']['revision']==1
    assert repo.get_case('team-a',report['id'],1)==report
    assert repo.audit('team-a')['verified']
    repo.delete_case('team-a','alice',report['id'])
    with pytest.raises(Missing):repo.get_case('team-a',report['id'])
    assert repo.audit('team-a')['verified']

def test_postgres_concurrent_review_and_shared_limit(postgres):
    repo,url,key=postgres;report=sample();repo.create_case('team-a','alice',report,[b'%PDF-synthetic'])
    second=Repository(url.render_as_string(hide_password=False),key)
    def review(store):
        try:store.review('team-a','reviewer',report['id'],'F1','confirm','',0);return 'saved'
        except Conflict:return 'conflict'
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(review,[repo,second]))==['conflict','saved']
        def consume(index):
            try:[repo,second][index%2].consume('shared',3,60,now=120);return True
            except LimitExceeded:return False
        with ThreadPoolExecutor(max_workers=6) as pool:assert sum(pool.map(consume,range(10)))==3
        assert repo.audit('team-a')['verified']
    finally:second.close()

def test_postgres_jobs_sessions_and_guest_cleanup(postgres):
    repo,_,key=postgres;security=Security(repo,key)
    security.create_user('reviewer@example.invalid','synthetic-password-123','team-a','reviewer')
    token,csrf=security.login('reviewer@example.invalid','synthetic-password-123')
    actor=security.authenticate(token);security.validate_csrf(actor,csrf,csrf)
    job=repo.enqueue('team-a',actor.id,'eval',{})
    claimed=repo.claim_job();assert claimed['id']==job
    assert repo.claim_job() is None
    repo.complete_job(job,claimed['lease_token'],{'passed':True})
    assert repo.get_job('team-a',job)['state']=='completed'
    guest,csrf=security.demo_session();assert security.authenticate(guest).role=='demo'
    security.logout(guest)
    with pytest.raises(Unauthorized):security.authenticate(guest)
    assert repo.expire_demo_data()==0


def test_postgres_ocr_commit_races_review_without_lost_updates(postgres,monkeypatch):
    from app import ocr_case
    from test_ocr_jobs import scanned_case,recognition
    repo,_,_=postgres;original=scanned_case(repo);case=original['id']
    repo.enqueue_ocr('team-a','alice',case,1)
    monkeypatch.setattr(ocr_case,'recognize',recognition)
    job=repo.claim_job(kinds=['ocr']);derived=ocr_case.build_report(repo,job)
    def review():
        try:repo.review('team-a','bob',case,'F1','note','Concurrent review',0,1);return 'reviewed'
        except Conflict:return 'stale'
    def complete():return repo.complete_ocr(job['id'],job['lease_token'],derived)
    with ThreadPoolExecutor(max_workers=2) as pool:
        saved=pool.submit(review);committed=pool.submit(complete)
        review_result=saved.result();committed.result()
    current=repo.get_case('team-a',case);state=repo.get_job('team-a',job['id'])['state']
    assert current['report_version']==2
    if state=='completed':
        assert review_result=='stale' and current['derived_from']['kind']=='ocr'
        assert all(f['human_review']['revision']==0 for f in current['findings'])
    else:
        assert state=='failed' and review_result=='reviewed'
        assert current['findings'][0]['human_review']['history'][0]['note']=='Concurrent review'
    assert repo.get_case('team-a',case,1)==original
    assert repo.audit('team-a')['verified']
