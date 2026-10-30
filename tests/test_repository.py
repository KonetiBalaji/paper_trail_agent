import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import pytest
from cryptography.fernet import Fernet,InvalidToken
from sqlalchemy import select,update,delete
from app.repository import Repository,Conflict,Missing,LimitExceeded,audits,audit_heads,documents

@pytest.fixture
def repo(tmp_path):
    db=Repository('sqlite:///'+(tmp_path/'cases.db').as_posix(),Fernet.generate_key())
    yield db
    db.close()

def report(case_id='a'*32):
    return {'id':case_id,'status':'review','documents':[{'id':'doc1','name':'synthetic.pdf',
        'statement':{'loan_id':'PRIVATE-LOAN-123','period_end':'2026-10-31'}}],
        'findings':[{'id':'F1','severity':'review','message':'Needs evidence','sources':[],
            'human_review':{'decision':'pending','revision':0,'history':[]}}],
        'calculations':[{'computed':'975.00'}],'trace':[]}

def create(repo):
    value=report();repo.create_case('team-a','alice',value,[b'%PDF-FICTIONAL-PRIVATE-DOCUMENT'])
    return value

def test_encrypted_durable_roundtrip(repo,tmp_path):
    value=create(repo)
    assert repo.get_case('team-a',value['id'])==value
    assert repo.get_document('team-a',value['id'],'doc1')==b'%PDF-FICTIONAL-PRIVATE-DOCUMENT'
    raw=(tmp_path/'cases.db').read_bytes()
    assert b'PRIVATE-LOAN-123' not in raw and b'FICTIONAL-PRIVATE-DOCUMENT' not in raw
    assert repo.audit('team-a')['verified']

def test_wrong_workspace_cannot_read_update_or_delete(repo):
    value=create(repo)
    for operation in [lambda:repo.get_case('team-b',value['id']),
        lambda:repo.get_document('team-b',value['id'],'doc1'),
        lambda:repo.review('team-b','bob',value['id'],'F1','confirm','',0),
        lambda:repo.delete_case('team-b','bob',value['id'])]:
        with pytest.raises(Missing):operation()
    assert repo.list_cases('team-b')['cases']==[]

def test_versioned_review_actor_and_replay(repo):
    value=create(repo)
    updated=repo.review('team-a','reviewer-1',value['id'],'F1','confirm','Reviewed image',0)
    assert updated['findings'][0]['human_review']['history'][0]['actor']=='reviewer-1'
    assert updated['calculations']==value['calculations'] and updated['status']==value['status']
    assert repo.get_case('team-a',value['id'],1)==value
    assert repo.get_case('team-a',value['id'],2)==updated
    events=repo.audit('team-a',value['id'])['events']
    assert [e['action'] for e in events]==['case_created','finding_reviewed']
    assert events[1]['previous_hash']==events[0]['event_hash']

def test_parallel_review_transaction_across_repository_instances(repo,tmp_path):
    value=create(repo)
    # A second engine with the same actual key models another worker.
    key=Fernet.generate_key();path='sqlite:///'+(tmp_path/'parallel.db').as_posix()
    first=Repository(path,key);second=Repository(path,key);first.create_case('team-a','alice',value,[b'%PDF-fake'])
    def work(store):
        try:store.review('team-a','reviewer',value['id'],'F1','confirm','',0);return 'saved'
        except Conflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(work,[first,second]))==['conflict','saved']
    assert len(first.audit('team-a')['events'])==2
    first.close();second.close()

def test_immutable_original_and_integrity(repo):
    value=create(repo)
    with pytest.raises(Conflict):repo.create_case('team-a','alice',value,[b'REPLACED'])
    with repo.transaction() as conn:
        conn.execute(update(documents).where(documents.c.case_id==value['id']).values(original=repo.cipher.encrypt(b'tampered')))
    with pytest.raises(ValueError,match='integrity'):repo.get_document('team-a',value['id'],'doc1')

def test_audit_tampering_and_truncation_detected(repo):
    create(repo)
    with repo.transaction() as conn:conn.execute(update(audits).values(action='forged'))
    with pytest.raises(ValueError,match='integrity'):repo.audit('team-a')

def test_audit_tail_deletion_detected(repo):
    create(repo)
    with repo.transaction() as conn:conn.execute(delete(audits))
    with pytest.raises(ValueError,match='head'):repo.audit('team-a')

def test_case_search_and_filter_are_workspace_scoped(repo):
    value=create(repo)
    assert repo.list_cases('team-a',query='PRIVATE-LOAN',status='review',decision='pending')['total_in_window']==1
    assert repo.list_cases('team-a',query='2026-10-31')['cases'][0]['version']==1
    repo.review('team-a','alice',value['id'],'F1','reject','',0)
    assert not repo.list_cases('team-a',decision='pending')['cases']
    assert repo.list_cases('team-a',decision='rejected')['cases'][0]['version']==2
    with pytest.raises(ValueError):repo.list_cases('team-a',limit=100000)

def test_deletion_removes_originals_and_versions_retains_noncontent_tombstone(repo):
    value=create(repo);repo.delete_case('team-a','alice',value['id'])
    with pytest.raises(Missing):repo.get_case('team-a',value['id'],1)
    with pytest.raises(Missing):repo.get_document('team-a',value['id'],'doc1')
    assert repo.audit('team-a')['events'][-1]['action']=='case_deleted'

def test_shared_rate_limit_parallel_and_window_reset(repo):
    def consume(_):
        try:repo.consume('demo',3,60,now=120);return True
        except LimitExceeded:return False
    with ThreadPoolExecutor(max_workers=8) as pool:assert sum(pool.map(consume,range(8)))==3
    assert repo.consume('demo',3,60,now=180)==1

def test_job_queue_is_durable_and_claimed_once(repo):
    job=repo.enqueue('team-a','alice','eval',{'case':'synthetic'})
    with ThreadPoolExecutor(max_workers=4) as pool:claims=list(pool.map(lambda _:repo.claim_job(),range(4)))
    claim=next(c for c in claims if c);assert sum(c is not None for c in claims)==1
    with pytest.raises(Missing):repo.get_job('team-b',job)
    with pytest.raises(Conflict):repo.complete_job(job,'wrong-token',{})
    repo.complete_job(job,claim['lease_token'],{'passed':True})
    assert repo.get_job('team-a',job)['result']=={'passed':True}
    with pytest.raises(Conflict):repo.complete_job(job,claim['lease_token'],{})

def test_expired_job_lease_can_be_recovered(repo):
    job=repo.enqueue('team-a','alice','ocr',{'document':'synthetic'})
    first=repo.claim_job(lease_seconds=1,now=time.time()-10)
    second=repo.claim_job();assert second['id']==job and second['attempt']==2
    with pytest.raises(Conflict):repo.complete_job(job,first['lease_token'],{})
    repo.complete_job(job,second['lease_token'],{'review_required':True})

def test_encrypted_backup_and_restoration(tmp_path):
    key=Fernet.generate_key();first=Repository('sqlite:///'+(tmp_path/'source.db').as_posix(),key)
    original=create(first);backup=first.backup_sqlite(tmp_path/'backup.db')
    assert b'PRIVATE-LOAN-123' not in backup.read_bytes()
    restored=Repository('sqlite:///'+backup.as_posix(),key)
    assert restored.get_case('team-a',original['id'])==original
    assert restored.audit('team-a')['verified']
    with pytest.raises(ValueError):first.backup_sqlite(backup)
    restored.close();first.close()

def test_eval_worker_completes_a_durable_job(repo):
    from app.worker import run_once
    job=repo.enqueue('team-a','alice','eval',{})
    assert run_once(repo)
    result=repo.get_job('team-a',job)
    assert result['state']=='completed' and result['result']['summary']['passed']==6
    assert not run_once(repo)

def test_unimplemented_job_handler_never_claims_success(repo):
    from app.worker import run_once
    job=repo.enqueue('team-a','alice','ingest',{'document':'synthetic'})
    assert run_once(repo)
    result=repo.get_job('team-a',job)
    assert result['state']=='failed' and 'not implemented' in result['result']['error']

def test_concurrent_audit_reads_do_not_report_false_tampering(repo):
    value=create(repo)
    def operation(i):
        if i%2:return repo.audit('team-a')['verified']
        try:repo.review('team-a','alice',value['id'],'F1','note','concurrent',i//2);return True
        except Conflict:return True
    with ThreadPoolExecutor(max_workers=4) as pool:assert all(pool.map(operation,range(8)))
    assert repo.audit('team-a')['verified']
