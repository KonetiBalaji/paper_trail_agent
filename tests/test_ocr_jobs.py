"""OCR job trust boundaries. Recognition is mocked except the explicit real gate."""
import copy
import importlib.util
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from sqlalchemy import update,select
from app import ocr_case
from app.ocr import source_lines,OCRUnavailable
from app.repository import Conflict,jobs,versions,Missing
from app.worker import run_once
from test_service import service,login
from test_repository import repo

ROOT=Path(__file__).resolve().parents[1]
SCAN=ROOT/'data/ocr/labeled_error.pdf'
LABELS=['Loan: OCR-001','Currency: USD','As of: 2026-10-31',
        'Tranche T1 | Principal: 1000.00 | Interest: 100.00',
        'Stated principal plus interest total: 1150.00']


def recognition(raw,doc_id,pages,timeout=90,score=.99):
    assert 0<timeout<=90 and pages==[1]
    boxes=[[[[20,y],[580,y],[580,y+20],[20,y+20]],text,score]
           for index,text in enumerate(LABELS,1) for y in [index*45]]
    return source_lines(boxes,doc_id,1,612,792,612,792)


def scanned_case(repo):
    from app.main import analyze_files
    from fastapi import UploadFile
    import io
    raw=SCAN.read_bytes()
    report=analyze_files([UploadFile(filename='scan.pdf',file=io.BytesIO(raw))],persist=False)
    repo.create_case('team-a','alice',report,[raw])
    return report


def upload(client,headers):
    response=client.post('/api/analyze',headers=headers,files={'files':('scan.pdf',SCAN.read_bytes(),'application/pdf')})
    assert response.status_code==200,response.text
    return response.json()


def test_queue_permissions_worker_availability_and_dedup(service):
    client,repo,_=service;headers=login(client);report=upload(client,headers)
    path='/api/cases/'+report['id']+'/ocr';data={'expected_version':1}
    assert client.post(path,headers=headers,json=data).status_code==503
    repo.touch_worker('a'*32,['ocr'])
    assert client.get('/api/platform/config').json()['ocr']['available']
    assert client.post(path,json=data).status_code==403
    first=client.post(path,headers=headers,json=data);assert first.status_code==202
    second=client.post(path,headers=headers,json=data)
    assert second.json()['reused'] and first.json()['job_id']==second.json()['job_id']
    assert client.post(path,headers=headers,json={'expected_version':2}).status_code==409
    client.cookies.clear();other=login(client,'other@example.invalid')
    assert client.get(path).status_code==404
    assert client.post(path,headers=other,json=data).status_code==404
    client.cookies.clear();viewer=login(client,'viewer@example.invalid')
    assert client.get(path).status_code==200
    assert client.post(path,headers=viewer,json=data).status_code==403
    client.cookies.clear();client.post('/api/platform/demo/start')
    assert client.post(path,headers={'X-CSRF-Token':client.cookies['pta_csrf']},json=data).status_code==403
    client.cookies.clear();assert client.post(path,json=data).status_code==401


def test_worker_heartbeat_expires_and_capability_filtered_claim(repo):
    repo.touch_worker('a'*32,['eval'],now=100)
    repo.touch_worker('b'*32,['ocr'],now=100)
    assert repo.worker_status(now=189)=={'eval':True,'ocr':True}
    assert repo.worker_status(now=190)=={'eval':False,'ocr':False}
    repo.retire_worker('b'*32)
    assert not repo.worker_status(now=101)['ocr']
    job=repo.enqueue('team-a','alice','ocr',{})
    assert repo.claim_job(kinds=['eval']) is None
    assert repo.claim_job(kinds=['ocr'])['id']==job


def test_parallel_enqueue_reuses_one_job_and_limits(repo):
    report=scanned_case(repo)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:repo.enqueue_ocr('team-a','alice',report['id'],1),range(4)))
    assert len({r['job_id'] for r in results})==1
    with pytest.raises(Missing):repo.enqueue_ocr('other','alice',report['id'],1)
    value=copy.deepcopy(report);value['id']='b'*32
    value['documents'][0]['issues']=[{'type':'ocr_required','page':p} for p in range(1,7)]
    repo.create_case('team-a','alice',value,[SCAN.read_bytes()])
    with pytest.raises(ValueError,match='1 to 5'):repo.enqueue_ocr('team-a','alice',value['id'],1)


def test_api_job_original_versions_review_guard_and_exports(service,monkeypatch):
    client,repo,_=service;headers=login(client);original=upload(client,headers);case=original['id'];base='/api/cases/'+case
    reviewed=client.patch(base+'/findings/F1',headers=headers,json={'action':'confirm','note':'Original scan needs review','expected_revision':0,'expected_case_version':1})
    assert reviewed.status_code==200 and reviewed.json()['report_version']==2
    repo.touch_worker('a'*32,['ocr']);monkeypatch.setattr(ocr_case,'recognize',recognition)
    queued=client.post(base+'/ocr',headers=headers,json={'expected_version':2}).json()
    assert run_once(repo,kinds=['ocr'])
    job=client.get('/api/platform/jobs/'+queued['job_id']).json()
    assert job['state']=='completed' and job['result']['report_version']==3
    derived=client.get(base).json()
    assert derived['status']=='review' and derived['report_version']==3
    assert derived['mode']=='ocr' and derived['previous_mode']=='local'
    assert derived['metrics']['attempted_model_calls']==0 and derived['agent'] is None
    assert all(f['human_review']['revision']==0 and f['severity']=='review' for f in derived['findings'])
    wrong=next(f for f in derived['findings'] if f.get('difference')=='50.00')
    assert wrong['provisional'] and derived['calculations'][0]['provisional']
    assert client.get(base+'/documents/doc1').content==SCAN.read_bytes()
    assert client.get(base,params={'version':2}).json()==reviewed.json()
    assert client.get(base,params={'version':1}).json()==original
    request={'action':'confirm','expected_revision':0,'expected_case_version':2}
    assert client.patch(base+'/findings/F1',headers=headers,json=request).status_code==409
    request.pop('expected_case_version')
    assert client.patch(base+'/findings/F1',headers=headers,json=request).status_code==409
    request['expected_case_version']=3
    assert client.patch(base+'/findings/F1',headers=headers,json=request).status_code==200
    latest=client.get(base).json();assert latest['status']=='review'
    assert all(not field['verified'] for field in latest['documents'][0]['ocr']['field_candidates'])
    source=wrong['sources'][-1]
    image=client.get(base+'/documents/doc1/page/1',params={'source':source})
    assert image.status_code==200 and image.content.startswith(b'\x89PNG')
    exported=client.get(base+'/export').json()
    assert exported['privacy']['redacted'] and exported['documents'][0]['ocr']['performed']
    assert 'If OCR values are correct' in client.get(base+'/export?format=md').text
    assert client.get(base+'/audit').json()['verified']


def test_concurrent_review_discards_ocr_without_losing_review(repo,monkeypatch):
    original=scanned_case(repo);case=original['id'];queued=repo.enqueue_ocr('team-a','alice',case,1)
    def concurrent(*args,**kwargs):
        repo.review('team-a','bob',case,'F1','note','Changed during OCR',0,1)
        return recognition(*args,**kwargs)
    monkeypatch.setattr(ocr_case,'recognize',concurrent)
    assert run_once(repo,kinds=['ocr'])
    assert repo.get_job('team-a',queued['job_id'])['state']=='failed'
    current=repo.get_case('team-a',case)
    assert current['report_version']==2 and not current.get('derived_from')
    assert current['findings'][0]['human_review']['history'][0]['note']=='Changed during OCR'
    assert repo.audit('team-a')['verified']


def test_lost_lease_cannot_commit_and_recovery_commits_once(repo,monkeypatch):
    original=scanned_case(repo);case=original['id'];repo.enqueue_ocr('team-a','alice',case,1)
    monkeypatch.setattr(ocr_case,'recognize',recognition)
    first=repo.claim_job();derived=ocr_case.build_report(repo,first)
    with repo.transaction() as conn:conn.execute(update(jobs).where(jobs.c.id==first['id']).values(lease_until=time.time()-1))
    with pytest.raises(Conflict):repo.complete_ocr(first['id'],first['lease_token'],derived)
    assert repo.get_case('team-a',case)==original
    second=repo.claim_job();assert second['attempt']==2
    repo.complete_ocr(second['id'],second['lease_token'],derived)
    assert repo.get_case('team-a',case)['report_version']==2
    with pytest.raises(Conflict):repo.complete_ocr(first['id'],first['lease_token'],derived)
    with pytest.raises(Conflict):repo.complete_ocr(second['id'],second['lease_token'],derived)


def test_transaction_rollback_preserves_case_and_unfinished_job(repo,monkeypatch):
    original=scanned_case(repo);repo.enqueue_ocr('team-a','alice',original['id'],1)
    monkeypatch.setattr(ocr_case,'recognize',recognition)
    job=repo.claim_job();derived=ocr_case.build_report(repo,job)
    audit=repo._audit
    def fail(*args,**kwargs):raise RuntimeError('Simulated failure before commit')
    monkeypatch.setattr(repo,'_audit',fail)
    with pytest.raises(RuntimeError):repo.complete_ocr(job['id'],job['lease_token'],derived)
    assert repo.get_case('team-a',original['id'])==original
    assert repo.get_job('team-a',job['id'])['state']=='running'
    with repo.engine.connect() as conn:assert len(conn.execute(select(versions)).all())==1
    monkeypatch.setattr(repo,'_audit',audit)
    assert repo.audit('team-a')['verified']


@pytest.mark.parametrize('change',['identity','lineage','confirmed'])
def test_invalid_derived_report_cannot_commit(repo,monkeypatch,change):
    original=scanned_case(repo);repo.enqueue_ocr('team-a','alice',original['id'],1)
    monkeypatch.setattr(ocr_case,'recognize',recognition)
    job=repo.claim_job();derived=ocr_case.build_report(repo,job)
    if change=='identity':derived['documents'][0]['name']='replacement.pdf'
    if change=='lineage':derived['derived_from']['version']=999
    if change=='confirmed':
        finding=next(f for f in derived['findings'] if f.get('difference')=='50.00');finding['severity']='confirmed'
    with pytest.raises(ValueError):repo.complete_ocr(job['id'],job['lease_token'],derived)
    assert repo.get_case('team-a',original['id'])==original
    assert repo.get_job('team-a',job['id'])['state']=='running'


@pytest.mark.parametrize('error',[OCRUnavailable('private text'),TimeoutError('private text'),ValueError('private text')])
def test_failed_ocr_preserves_original_and_has_safe_error(repo,monkeypatch,error):
    original=scanned_case(repo);queued=repo.enqueue_ocr('team-a','alice',original['id'],1)
    def fail(*args,**kwargs):raise error
    monkeypatch.setattr(ocr_case,'recognize',fail)
    assert run_once(repo,kinds=['ocr'])
    result=repo.get_job('team-a',queued['job_id'])
    assert result['state']=='failed' and 'private text' not in result['result']['error']
    assert repo.get_case('team-a',original['id'])==original


def test_low_scores_never_enter_candidate_calculation(repo,monkeypatch):
    original=scanned_case(repo);repo.enqueue_ocr('team-a','alice',original['id'],1)
    monkeypatch.setattr(ocr_case,'recognize',lambda *args,**kwargs:recognition(*args,**kwargs,score=.6))
    run_once(repo,kinds=['ocr']);current=repo.get_case('team-a',original['id'])
    assert current['status']=='review' and not current['calculations']
    assert current['documents'][0]['lines'] and not any(l['usable'] for l in current['documents'][0]['lines'])


def test_deleted_case_is_not_recreated(repo,monkeypatch):
    original=scanned_case(repo);repo.enqueue_ocr('team-a','alice',original['id'],1)
    monkeypatch.setattr(ocr_case,'recognize',recognition)
    job=repo.claim_job();derived=ocr_case.build_report(repo,job)
    repo.delete_case('team-a','alice',original['id'])
    repo.complete_ocr(job['id'],job['lease_token'],derived)
    assert repo.get_job('team-a',job['id'])['state']=='failed'
    with pytest.raises(Missing):repo.get_case('team-a',original['id'])


@pytest.mark.skipif(importlib.util.find_spec('rapidocr_onnxruntime') is None,reason='Actual OCR runs in its optional CI environment')
def test_actual_ocr_worker_derives_a_version_without_model_calls(repo):
    original=scanned_case(repo);job=repo.enqueue_ocr('team-a','alice',original['id'],1)
    assert run_once(repo,kinds=['ocr'])
    result=repo.get_job('team-a',job['job_id']);assert result['state']=='completed'
    derived=repo.get_case('team-a',original['id'])
    assert derived['status']=='review' and derived['report_version']==2
    assert any(f.get('difference')=='50.00' and f['severity']=='review' for f in derived['findings'])
    assert derived['metrics']['attempted_model_calls']==0
    assert repo.get_case('team-a',original['id'],1)==original
    assert repo.get_document('team-a',original['id'],'doc1')==SCAN.read_bytes()
