import copy
import pytest
from app.core import parse_statement, reconcile, retrieve
from app.ocr import source_lines, extract, candidate_checks, recognize


def boxes(texts, score=.99):
    return [[[[10,y],[500,y],[500,y+20],[10,y+20]], text, score]
            for y,text in enumerate(texts, 1) for y in [y*40]]


TEXT = ['Loan: DEMO-001', 'Currency: USD', 'Period end: 2026-10-01',
        'Tranche T1 | Principal: 1000.00 | Interest: 100.00',
        'Stated principal plus interest total: 1150.00']


def original():
    return {'id':'doc1','name':'scan.pdf','lines':[],
            'issues':[{'type':'ocr_required','page':1,'message':'OCR needed'}]}


def fake(raw, doc_id, pages):
    return source_lines(boxes(TEXT),doc_id,1,600,800,600,800)


def test_candidates_preserve_original_and_require_review():
    source=original(); before=copy.deepcopy(source)
    doc=extract(b'%PDF-fixture',source,fake)
    assert source==before
    assert doc['statement']['stated_total']=='1150.00'
    assert doc['ocr']['confidence_calibrated'] is False
    assert len(doc['ocr']['field_candidates'])==3
    assert all(not field['verified'] for field in doc['ocr']['field_candidates'])
    findings, calculations=candidate_checks(doc)
    wrong=next(f for f in findings if f['type']=='incorrect_statement_total')
    assert wrong['difference']=='50.00' and wrong['severity']=='review'
    assert calculations[0]['computed']=='1100.00' and calculations[0]['provisional']
    assert all(f['severity']=='review' for f in findings)
    assert any(f['type']=='ocr_review' for f in findings)
    # Normal reconciliation also cannot turn OCR into a confirmed finding.
    assert all(f['severity']=='review' for f in reconcile([doc])[0])


def test_low_confidence_retained_but_excluded():
    def low(*args):return source_lines(boxes(TEXT,.7),'doc1',1,600,800,600,800)
    doc=extract(b'%PDF-fixture',original(),low)
    assert len(doc['lines'])==5 and doc['statement']['stated_total'] is None
    assert not retrieve([doc],'1000')
    assert not candidate_checks(doc)[1]
    assert any(i['type']=='ocr_low_confidence' for i in doc['issues'])


def test_empty_and_correct_candidates_never_clean():
    empty=extract(b'%PDF-fixture',original(),lambda *args:[])
    assert not candidate_checks(empty)[1]
    def correct(*args):return source_lines(boxes(TEXT[:-1]+['Stated principal plus interest total: 1100.00']),'doc1',1,600,800,600,800)
    doc=extract(b'%PDF-fixture',original(),correct)
    assert [f['type'] for f in candidate_checks(doc)[0]]==['ocr_review']


def test_ocr_cannot_exceed_native_document_text_limit():
    source=original()
    def excessive(*args):
        lines=source_lines(boxes(['synthetic text']),'doc1',1,600,800,600,800)
        lines[0]['text']='x'*100001
        return lines
    with pytest.raises(ValueError,match='100,000'):
        extract(b'%PDF-fixture',source,excessive)


def test_missing_date_stays_missing_with_conditional_math():
    def no_date(*args):return source_lines(boxes([text for text in TEXT if not text.startswith('Period')]),'doc1',1,600,800,600,800)
    doc=extract(b'%PDF-fixture',original(),no_date)
    findings,calculations=candidate_checks(doc)
    assert doc['statement']['period_end'] is None
    assert any(f['type']=='incomplete_extraction' for f in findings)
    assert any(f.get('difference')=='50.00' and f['severity']=='review' for f in findings)
    assert calculations[0]['computed']=='1100.00'


def test_fixture_generation_is_image_only_and_reproducible(tmp_path):
    import hashlib,json
    from scripts.generate_ocr_fixtures import generate
    from app.core import read_pdf
    generate(tmp_path/'one');generate(tmp_path/'two')
    manifest=json.loads((tmp_path/'one/manifest.json').read_text())
    assert (tmp_path/'one/manifest.json').read_bytes()==(tmp_path/'two/manifest.json').read_bytes()
    for case in manifest['cases']:
        raw=(tmp_path/'one'/case['file']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==case['sha256']
        assert not read_pdf(raw,case['file'],'doc1')['lines']


def test_geometry_grouping_and_min_score():
    detections=[[[[10,10],[80,10],[80,30],[10,30]],'Principal',.99],
                [[[90,11],[180,11],[180,31],[90,31]],'1000.00',.96]]
    lines=source_lines(detections,'doc2',3,300,400,600,800)
    assert len(lines)==1 and lines[0]['text']=='Principal 1000.00'
    assert lines[0]['bbox']==[5,5,90,15.5]
    assert lines[0]['confidence']==.96 and lines[0]['id']=='doc2:p3:o1'


@pytest.mark.parametrize('score',[float('nan'),float('inf'),-1,1.1])
def test_invalid_scores_rejected(score):
    with pytest.raises(ValueError):source_lines(boxes(['bad'],score),'d',1,600,800,600,800)


@pytest.mark.parametrize('pages',[[0],[51],[],[1,1],list(range(1,7)),[True]])
def test_limits_before_spawning(pages):
    with pytest.raises(ValueError):recognize(b'%PDF-fixture','d',pages)


def test_boxes_outside_original_rejected():
    with pytest.raises(ValueError):source_lines(boxes(['bad']),'d',1,600,800,20,20)


def test_native_text_not_duplicated():
    source=original();source['issues'][0]['page']=2
    source['lines']=[{'id':'doc1:p1:l1','page':1,'line':1,'text':'Loan: DEMO-001','bbox':[1,1,200,20]}]
    def second(*args):return source_lines(boxes(TEXT[1:]),'doc1',2,600,800,600,800)
    doc=extract(b'%PDF-fixture',source,second)
    assert doc['statement']['loan_id']=='DEMO-001'
    assert doc['lines'][0]['id']=='doc1:p1:l1'


def test_timeout_terminates_owned_child(monkeypatch):
    events=[]
    class Pipe:
        def close(self):events.append('pipe_closed')
        def poll(self,timeout):return False
    class Child:
        pid=10
        alive=True
        def start(self):events.append('started')
        def join(self,*args):pass
        def is_alive(self):return self.alive
        def terminate(self):events.append('terminated');self.alive=False
        def close(self):events.append('closed')
    class Context:
        def Pipe(self,**kwargs):return Pipe(),Pipe()
        def Process(self,**kwargs):return Child()
    monkeypatch.setattr('app.ocr.multiprocessing.get_context',lambda *args:Context())
    with pytest.raises(TimeoutError):recognize(b'%PDF-fixture','doc1',[1],timeout=.1)
    assert 'terminated' in events and 'closed' in events
