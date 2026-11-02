import copy
import io
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from cryptography.fernet import Fernet
from fastapi import UploadFile
from sqlalchemy import select,func,update
from app import main,meta,ingestion
from app.repository import Repository,cases,statement_sources,intake_sets

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path):
    repo=Repository('sqlite:///'+(tmp_path/'cases.db').as_posix(),Fernet.generate_key())
    yield repo
    repo.close()


def files(case='math_error',reverse=False):
    paths=sorted((ROOT/'data/synthetic'/case).glob('*.pdf'))
    if reverse:paths.reverse()
    return [UploadFile(filename=p.name,file=io.BytesIO(p.read_bytes())) for p in paths]


def submit(repo,case='math_error',workspace='team',analyzer=main.analyze_files,reverse=False,mode='local'):
    return ingestion.intake(repo,workspace,'actor',files(case,reverse),mode,'upload',analyzer)


def test_exact_retry_preserves_review_and_avoids_analysis(repo):
    first=submit(repo)
    assert first['intake_receipt']['created']
    finding=first['findings'][0]
    saved=repo.review('team','reviewer',first['id'],finding['id'],'confirm','Checked original',0,1)
    def forbidden(*a,**k):pytest.fail('Retry analyzed identical input')
    retry=submit(repo,analyzer=forbidden,reverse=True)
    assert retry['id']==first['id'] and retry['report_version']==saved['report_version']
    assert retry['findings'][0]['human_review']['decision']=='confirmed'
    assert retry['intake_receipt']=={'created':False,'reused_analysis':True,'model_calls_this_request':0}
    assert repo.list_cases('team')['total_in_window']==1
    assert 'intake_receipt' not in repo.get_case('team',first['id'])
    assert repo.audit('team')['verified']


def test_renamed_files_are_the_same_input_but_workspace_isolation_remains(repo):
    first=submit(repo)
    renamed=files()
    for n,file in enumerate(renamed):file.filename='renamed-'+str(n)+'.pdf'
    retry=ingestion.intake(repo,'team','other',renamed,'local','api',main.analyze_files)
    other=submit(repo,workspace='other-team')
    assert retry['id']==first['id'] and other['id']!=first['id']
    with repo.engine.connect() as conn:
        tags=conn.execute(select(statement_sources.c.account_tag).where(statement_sources.c.account_tag.is_not(None))).scalars().all()
        assert len(set(tags))==2


def test_duplicate_pdf_is_review_and_never_independent_evidence():
    raw=files('clean')[0].file.read()
    report=main.analyze_files([UploadFile(filename=n,file=io.BytesIO(raw)) for n in ('first.pdf','copy.pdf')],'local',persist=False)
    assert report['status']=='review'
    assert not any(f['severity']=='confirmed' for f in report['findings'])
    assert {'duplicate_document','comparison_skipped'} <= {f['type'] for f in report['findings']}
    assert report['documents'][1]['duplicate_of']=='doc1'
    assert len(report['calculations'])==1


def test_duplicate_is_blocked_before_second_model_extraction(monkeypatch):
    from app.core import parse_statement
    calls=[]
    def extract(doc,trace):calls.append(doc['id']);return parse_statement(doc)
    monkeypatch.setattr(meta,'extract',extract)
    from app.orchestration import extract_documents
    raw=files('clean')[0].file.read()
    docs,_=extract_documents([UploadFile(filename=n,file=io.BytesIO(raw)) for n in ('first.pdf','copy.pdf')],'meta',[])
    assert calls==['doc1'] and docs[1]['routing']['selected']=='blocked'


def test_input_key_is_a_multiset_and_engine_changes_reanalyze(repo,monkeypatch):
    source=files('clean')[0].file.read()
    def one(count):return [UploadFile(filename='statement.pdf',file=io.BytesIO(source)) for _ in range(count)]
    monkeypatch.setattr(ingestion,'engine_fingerprint',lambda mode:'engine-one')
    first=ingestion.intake(repo,'team','actor',one(1),'local','upload',main.analyze_files)
    duplicate=ingestion.intake(repo,'team','actor',one(2),'local','upload',main.analyze_files)
    assert duplicate['id']!=first['id'] and duplicate['status']=='review'
    monkeypatch.setattr(ingestion,'engine_fingerprint',lambda mode:'engine-two')
    fresh=ingestion.intake(repo,'team','actor',one(1),'local','upload',main.analyze_files)
    assert fresh['id']!=first['id'] and fresh['ingestion']['previously_seen_sources']==1


def test_atomic_commit_from_two_concurrent_analyses(repo):
    inputs=files();blobs=[f.file.read() for f in inputs]
    reports=[main.analyze_files(files(),'local',persist=False) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda r:repo.ingest_case('team','actor','a'*64,r,blobs,'upload'),reports))
    assert len({r[0]['id'] for r in results})==1 and sorted(r[1] for r in results)==[False,True]
    assert repo.list_cases('team')['total_in_window']==1 and repo.audit('team')['verified']


def test_delete_and_retention_remove_index_and_permit_reimport(repo):
    first=submit(repo)
    repo.delete_case('team','actor',first['id'])
    fresh=submit(repo)
    assert fresh['id']!=first['id']
    with repo.transaction() as conn:conn.execute(update(cases).values(created_at='2000-01-01T00:00:00+00:00'))
    policy=repo.set_retention('team','actor',1,True,0)
    assert repo.purge_workspace('team',expected_revision=policy['revision'])['deleted']==1
    with repo.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(intake_sets)).scalar_one()==0
        assert conn.execute(select(func.count()).select_from(statement_sources)).scalar_one()==0


def test_source_identity_stays_encrypted_and_unknown_identity_unindexed(repo,tmp_path):
    report=submit(repo,'messy')
    with repo.engine.connect() as conn:
        rows=conn.execute(select(statement_sources)).mappings().all()
    assert any(row['account_tag'] is None for row in rows)
    assert all(not row['identity'].startswith(b'{') for row in rows)
    assert b'DEMO-001' not in (tmp_path/'cases.db').read_bytes()


def test_failed_model_attempt_is_not_a_permanent_cached_result(repo):
    calls=[]
    def failed(*a,**k):
        calls.append(1);report=main.analyze_files(*a,**k);report['agent_error']='Simulated provider failure';report['status']='review'
        return report
    first=submit(repo,analyzer=failed);second=submit(repo,analyzer=failed)
    assert len(calls)==2 and first['id']!=second['id']
    with repo.engine.connect() as conn:assert conn.execute(select(func.count()).select_from(intake_sets)).scalar_one()==0


def test_racing_analysis_receipt_does_not_hide_calls_already_made(repo,monkeypatch):
    first=submit(repo)
    monkeypatch.setattr(repo,'find_intake',lambda *a:None)
    def raced(*a,**k):
        report=main.analyze_files(*a,**k);report['metrics']['attempted_model_calls']=7
        return report
    result=submit(repo,analyzer=raced)
    assert result['id']==first['id'] and not result['intake_receipt']['created']
    assert result['intake_receipt']['model_calls_this_request']==7
    assert repo.audit('team')['events'][-1]['payload']['attempted_model_calls']==7


def test_model_only_identity_cannot_silently_become_a_grouping_key(repo):
    inputs=files();blobs=[f.file.read() for f in inputs]
    report=main.analyze_files(files(),'local',persist=False)
    # Fault injection: an apparently passed model schema is insufficient when
    # the account identity has no matching explicit native source label.
    for doc in report['documents']:
        doc['lines']=[line for line in doc['lines'] if 'Loan:' not in line['text']]
    repo.ingest_case('team','actor','d'*64,report,blobs,'upload')
    with repo.engine.connect() as conn:
        assert all(tag is None for tag in conn.execute(select(statement_sources.c.account_tag)).scalars())


def test_existing_originals_are_known_before_the_new_intake_index(repo):
    sources=files();blobs=[f.file.read() for f in sources]
    old=main.analyze_files(files(),'local',persist=False)
    repo.create_case('team','legacy-uploader',old,blobs)
    current=submit(repo)
    assert current['ingestion']['previously_seen_sources']==2
