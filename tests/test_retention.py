import time
from datetime import datetime,timezone
import pytest
from sqlalchemy import select,update,func
from app.repository import cases,documents,versions,Conflict,Missing
from test_repository import repo,report
from test_service import service,login,upload


def aged(repo,workspace='team-a',case_id='a'*32,age=31,now=None):
    now=time.time() if now is None else now
    value=report(case_id);repo.create_case(workspace,'alice',value,[b'%PDF-FICTIONAL-PRIVATE-DOCUMENT'])
    created=datetime.fromtimestamp(now-age*86400,timezone.utc).isoformat()
    with repo.transaction() as conn:conn.execute(update(cases).where(cases.c.id==case_id).values(created_at=created))
    return value


def test_retention_is_disabled_until_explicit_policy(repo):
    old=aged(repo);preview=repo.retention_info('team-a')
    assert not preview['enabled'] and preview['revision']==0 and preview['eligible_cases']==1
    assert repo.purge_retained_cases()==0 and repo.get_case('team-a',old['id'])
    repo.set_retention('team-a','admin',30,False,0)
    assert repo.purge_workspace('team-a')['deleted']==0


def test_retention_removes_all_versions_originals_but_keeps_minimal_audit(repo):
    now=time.time();old=aged(repo,now=now);aged(repo,'team-b','b'*32,now=now)
    aged(repo,case_id='c'*32,age=30,now=now)  # Strict cutoff boundary is preserved.
    repo.review('team-a','reviewer',old['id'],'F1','note','Private note that must be deleted',0)
    policy=repo.set_retention('team-a','admin',30,True,0)
    result=repo.purge_workspace('team-a',expected_revision=policy['revision'],now=now)
    assert result['deleted']==1
    for version in (None,1,2):
        with pytest.raises(Missing):repo.get_case('team-a',old['id'],version)
    with pytest.raises(Missing):repo.get_document('team-a',old['id'],'doc1')
    with repo.engine.connect() as conn:
        for table in (documents,versions):
            assert conn.execute(select(func.count()).select_from(table).where(table.c.case_id==old['id'])).scalar_one()==0
    assert repo.get_case('team-b','b'*32) and repo.get_case('team-a','c'*32)
    audit=repo.audit('team-a');assert audit['verified'] and audit['events'][-1]['action']=='case_retention_deleted'
    assert 'Private note' not in str(audit) and 'PRIVATE-LOAN-123' not in str(audit)


def test_stale_policies_cannot_change_or_run_cleanup(repo):
    old=aged(repo);repo.set_retention('team-a','admin',30,True,0)
    with pytest.raises(Conflict):repo.set_retention('team-a','admin',1,True,0)
    with pytest.raises(Conflict):repo.purge_workspace('team-a',expected_revision=0)
    assert repo.get_case('team-a',old['id'])
    repo.set_retention('team-a','admin',30,False,1)
    assert repo.purge_retained_cases()==0


def test_cleanup_batch_limit_and_workspace_rotation(repo):
    for n in range(26):aged(repo,case_id=format(n,'032x'))
    repo.set_retention('team-a','admin',30,True,0)
    assert repo.purge_workspace('team-a')['deleted']==25
    assert repo.purge_workspace('team-a')['deleted']==1
    for n in range(26):
        workspace='w'+format(n,'02d');repo.provision_workspace(workspace);repo.set_retention(workspace,'admin',30,True,0)
    aged(repo,'w25','f'*32)
    assert repo.purge_retained_cases()==0  # First 25 empty policies rotate out.
    assert repo.purge_retained_cases()==1


def test_in_flight_ocr_cannot_restore_retained_case(repo,monkeypatch):
    from test_ocr_jobs import scanned_case,recognition
    from app import ocr_case
    original=scanned_case(repo);case=original['id']
    repo.enqueue_ocr('team-a','alice',case,1);job=repo.claim_job(kinds=['ocr'])
    monkeypatch.setattr(ocr_case,'recognize',recognition);derived=ocr_case.build_report(repo,job)
    with repo.transaction() as conn:conn.execute(update(cases).where(cases.c.id==case).values(created_at='2000-01-01T00:00:00+00:00'))
    repo.set_retention('team-a','admin',30,True,0)
    assert repo.purge_retained_cases()==1
    result=repo.complete_ocr(job['id'],job['lease_token'],derived)
    assert 'error' in result and repo.get_job('team-a',job['id'])['state']=='failed'
    with pytest.raises(Missing):repo.get_case('team-a',case)
    assert repo.audit('team-a')['verified']


def test_retention_api_admin_csrf_acknowledgement_and_workspace(service):
    client,repo,_=service;headers=login(client)
    assert client.get('/api/platform/retention').json()['enabled'] is False
    data={'days':30,'enabled':True,'expected_revision':0}
    assert client.put('/api/platform/retention',json=data).status_code==403
    assert client.put('/api/platform/retention',json=data,headers=headers).status_code==422
    data['acknowledge_deletion']='DELETE_EXPIRED_CASES'
    assert client.put('/api/platform/retention',json=data,headers=headers).json()['revision']==1
    assert client.post('/api/platform/retention/run',json={'expected_revision':0},headers=headers).status_code==409
    assert client.post('/api/platform/retention/run',json={'expected_revision':1},headers=headers).json()['deleted']==0
    assert not repo.retention_info('team-b')['enabled']
    login(client,'viewer@example.invalid')
    assert client.get('/api/platform/retention').status_code==403
    assert client.post('/api/platform/retention/run',json={'expected_revision':1},headers={'X-CSRF-Token':client.cookies['pta_csrf']}).status_code==403
    client.cookies.clear()
    notice=client.get('/api/policies');assert notice.status_code==200
    assert {'title','text'}==set(notice.json()['sections'][0])
    assert 'disabled until' in str(notice.json()) and 'backups' in str(notice.json())
