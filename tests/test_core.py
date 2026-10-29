import json
from pathlib import Path
import pytest
from app.core import calculate,money,read_pdf,parse_statement,reconcile,retrieve

ROOT=Path(__file__).resolve().parents[1]/'data'/'synthetic'

@pytest.mark.parametrize('values,total',[(['0.10','0.20'],'0.30'),(['1,000.00','(25.00)'],'975.00'),(['-2.00','1.00'],'-1.00')])
def test_exact_calculator(values,total): assert calculate(values)==total

@pytest.mark.parametrize('value',['NaN','Infinity','0.001','oops','1e99'])
def test_invalid_money(value):
    with pytest.raises(ValueError): money(value)

def documents(case):
    docs=[]
    for i,p in enumerate(sorted((ROOT/case).glob('*.pdf'))):
        d=read_pdf(p.read_bytes(),p.name,f'doc{i+1}');d['statement']=parse_statement(d);docs.append(d)
    return docs

@pytest.mark.parametrize('case',['clean','contradiction','math_error','messy'])
def test_fixtures_against_ground_truth(case):
    truth=json.loads((ROOT/case/'ground_truth.json').read_text())
    docs=documents(case);findings,calculations=reconcile(docs)
    confirmed=[f for f in findings if f['severity']=='confirmed']
    assert len(confirmed)==truth['expected_confirmed_contradictions']
    for expected,actual in zip(truth['documents'],docs):
        s=actual['statement']
        if not expected['text_layer']:
            assert actual['issues'][0]['type']=='ocr_required'
            assert s['tranches']==[]
            continue
        for field in ('loan_id','period_end','currency','stated_total'): assert s[field]==expected[field]
        assert len(s['tranches'])==len(expected['tranches'])
        for t,e in zip(s['tranches'],expected['tranches']):
            for k in ('id','principal','interest'): assert t[k]==e[k]
            line=next(l for l in actual['lines'] if l['id']==t['source'])
            assert e['source_line'] in line['text']
            x0,y0,x1,y1=line['bbox'];assert 0<=x0<x1<=line['page_width'];assert 0<=y0<y1<=line['page_height']
    if case=='clean': assert findings==[] and len(calculations)==2
    if case=='contradiction':
        assert confirmed[0]['difference']=='25.00'
        assert confirmed[0]['field']=='interest' and len(confirmed[0]['sources'])==2
    if case=='math_error': assert confirmed[0]['difference']=='50.00' and confirmed[0]['computed']=='3300.00'
    if case=='messy': assert not confirmed and any(f['type']=='ocr_required' for f in findings)

def test_period_guard():
    docs=documents('contradiction');docs[1]['statement']['period_end']='2026-09-30'
    findings,_=reconcile(docs)
    assert [f['type'] for f in findings]==['period_mismatch']
    assert findings[0]['severity']=='review'

def test_missing_tranche_review():
    docs=documents('clean');docs[1]['statement']['tranches'].pop();docs[1]['statement']['stated_total']='1100.00'
    findings,_=reconcile(docs)
    assert [f['type'] for f in findings]==['missing_tranche']
    assert findings[0]['severity']=='review'

def test_duplicate_not_summed():
    docs=documents('clean');docs[0]['statement']['tranches']*=2
    findings,calculations=reconcile(docs)
    assert any(f['type']=='duplicate_tranche' for f in findings)
    assert len(calculations)==1

def test_retrieval_is_source_evidence():
    results=retrieve(documents('clean'),'T1 principal')
    assert results and 'Principal' in results[0]['text'] and results[0]['id'].startswith('doc')

def test_corrupt_pdf():
    with pytest.raises(ValueError):read_pdf(b'not pdf','bad.pdf','doc1')

@pytest.mark.parametrize('field,value',[('loan_id','OTHER-ACCOUNT'),('currency','EUR')])
def test_identity_mismatch_is_review(field,value):
    docs=documents('clean');docs[1]['statement'][field]=value
    findings,_=reconcile(docs)
    assert [f['type'] for f in findings]==['identity_mismatch']
    assert findings[0]['severity']=='review'

def test_blocked_comparison_is_explicit():
    findings,_=reconcile(documents('messy'))
    assert {f['type'] for f in findings}=={'ocr_required','comparison_skipped'}
    assert all(f['severity']=='review' for f in findings)
    docs=documents('clean');docs[1]['statement']['loan_id']=None
    findings,_=reconcile(docs)
    assert any(f['type']=='identity_incomplete' and f['severity']=='review' for f in findings)
