import copy
import io
import pytest
from reportlab.pdfgen import canvas
from app.core import read_pdf
from app.historical import evaluate_history


def document(doc_id,start='2026-09-01',end='2026-09-30',kind='bank',opening='1000.00',closing='900.00',extra=()):
    lines=[f'Historical rules: PTA-{ "BANK-PERIOD" if kind=="bank" else "LOAN-PRINCIPAL" }-V1',
        'Account: FICTIONAL-001','Currency: USD',f'Period start: {start}',f'Period end: {end}']
    if kind=='bank':lines += [f'Opening balance: {opening}','Transaction count: 1',
        f'Transaction PAYMENT-1 | {end} | Amount: -100.00',f'Closing balance: {closing}']
    else:lines += [f'Historical principal opening: {opening}','Principal disbursed: 0.00',
        'Principal repaid: 100.00','Principal adjustments: 0.00',f'Historical principal closing: {closing}']
    lines+=list(extra)
    buf=io.BytesIO();pdf=canvas.Canvas(buf,pagesize=(612,792),invariant=True)
    for index,line in enumerate(lines):pdf.drawString(40,750-index*20,line)
    pdf.save()
    return read_pdf(buf.getvalue(),f'{doc_id}.pdf',doc_id)


@pytest.mark.parametrize('separator',['-','/'])
@pytest.mark.parametrize('kind',['bank','loan'])
def test_real_pdfs_legitimate_payment_change_and_carry(kind, separator):
    previous=document('earlier',kind=kind)
    later=document('later',f'2026{separator}10{separator}01',f'2026{separator}10{separator}31',kind,opening='900.00',closing='800.00')
    result=evaluate_history([later,previous])
    assert not result['review'] and all(c['result']=='passed' for c in result['checks'])
    pair=result['pairs'][0]
    assert pair['result']=='passed' and pair['documents']==['earlier','later']
    assert pair['computed']==pair['stated']=='900.00'
    assert {s.split(':')[0] for s in pair['sources']}=={'earlier','later'}
    assert 'status' not in result  # Passing named checks never labels the account clean.


@pytest.mark.parametrize('kind',['bank','loan'])
def test_exact_carry_difference_and_independent_period_math(kind):
    result=evaluate_history([document('a',kind=kind),document('b','2026-10-01','2026-10-31',kind,'950.00','800.00')])
    assert result['pairs'][0]['difference']=='50.00'
    assert result['pairs'][0]['result']=='discrepancy'
    assert result['checks'][1]['difference']=='50.00'
    assert result['checks'][1]['computed']=='850.00'


@pytest.mark.parametrize('start,end,reason',[
    ('2026-11-01','2026-11-30','period_gap'),
    ('2026-09-30','2026-10-31','overlapping_or_same_period')])
def test_gaps_and_partial_overlap_require_review(start,end,reason):
    result=evaluate_history([document('a'),document('b',start,end,opening='900.00',closing='800.00')])
    assert result['pairs'][0]['result']=='review' and result['pairs'][0]['reason']==reason
    assert 'difference' not in result['pairs'][0]


@pytest.mark.parametrize('old,new,reason',[
    ('Account: FICTIONAL-001','Account: OTHER','account_currency_or_rule_mismatch'),
    ('Currency: USD','Currency: EUR','account_currency_or_rule_mismatch'),
    ('Currency: USD','Currency: JPY','incomplete_native_history'),
    ('Period start: 2026-10-01','Period start: 10/01/2026','incomplete_native_history'),
    ('Period end: 2026-10-31','Period end: 2026-02-30','incomplete_native_history'),
    ('Transaction count: 1','Transaction count: 2','incomplete_native_history'),
    ('2026-10-31 | Amount','2026-09-30 | Amount','incomplete_native_history'),
])
def test_native_identity_dates_and_transaction_completeness(old,new,reason):
    later=document('b','2026-10-01','2026-10-31',opening='900.00',closing='800.00')
    for line in later['lines']:line['text']=line['text'].replace(old,new)
    result=evaluate_history([document('a'),later])
    assert result['pairs'][0]['result']=='review' and result['pairs'][0]['reason']==reason


@pytest.mark.parametrize('mutation',['issues','ocr','method','unusable','duplicate','repeated_source'])
def test_uncertain_or_repeated_evidence_is_withheld(mutation):
    a=document('a');b=document('b','2026-10-01','2026-10-31',opening='900.00',closing='800.00')
    if mutation=='issues':b['issues']=[{'type':'partial_extraction'}]
    elif mutation=='ocr':b['ocr']={'performed':True}
    elif mutation=='method':b['lines'][0]['method']='ocr'
    elif mutation=='unusable':b['lines'][0]['usable']=False
    elif mutation=='duplicate':b['duplicate_of']='a'
    else:b['lines'][1]['id']=b['lines'][0]['id']
    result=evaluate_history([a,b])
    assert len(result['review'])==1 and len(result['checks'])==1
    assert result['pairs'][0]['result']=='review'


def test_repeated_label_and_unallocated_total_payment_cannot_be_inferred():
    b=document('b',kind='loan',extra=['Principal repaid: 100.00'])
    assert evaluate_history([b])['review'][0]['reason']=='missing_or_repeated_principal_repaid'
    b=document('b',kind='loan')
    for line in b['lines']:line['text']=line['text'].replace('Principal repaid:','Payment total:')
    assert evaluate_history([b])['review']


def test_exact_duplicate_never_compares_to_itself_and_inputs_not_mutated():
    a=document('a');b=copy.deepcopy(a);b['id']='b'
    for line in b['lines']:line['id']=line['id'].replace('a:','b:')
    before=copy.deepcopy([a,b]);r=evaluate_history([a,b])
    assert r['pairs'][0]['reason']=='duplicate_document' and 'difference' not in r['pairs'][0]
    assert [a,b]==before


def test_aggregate_overflow_and_nonfinite_values_request_review():
    doc=document('a',kind='loan',opening='1000000000000000.00')
    for line in doc['lines']:line['text']=line['text'].replace('Principal disbursed: 0.00','Principal disbursed: 1000000000000000.00')
    assert evaluate_history([doc])['review'][0]['reason']=='calculation_out_of_range'
    doc=document('a',kind='loan')
    for line in doc['lines']:line['text']=line['text'].replace('Principal repaid: 100.00','Principal repaid: NaN')
    assert evaluate_history([doc])['review']


def test_explicit_signed_adjustment_and_disbursement():
    a=document('a',kind='loan',closing='1150.00')
    for line in a['lines']:
        line['text']=line['text'].replace('Principal disbursed: 0.00','Principal disbursed: 300.00').replace('Principal adjustments: 0.00','Principal adjustments: -50.00')
    r=evaluate_history([a]);assert not r['review']
    assert r['checks'][0]['result']=='passed' and r['checks'][0]['computed']=='1150.00'


def test_zero_transactions_explicitly_counted_and_bounds():
    a=document('a',closing='1000.00')
    a['lines']=[l for l in a['lines'] if not l['text'].startswith('Transaction PAYMENT')]
    for line in a['lines']:line['text']=line['text'].replace('Transaction count: 1','Transaction count: 0')
    assert evaluate_history([a])['checks'][0]['result']=='passed'
    with pytest.raises(ValueError):evaluate_history([a]*9)
    with pytest.raises(ValueError):evaluate_history([a,a])


def test_local_http_real_pdfs_history_sources_export_binding(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setenv('PAPER_TRAIL_MODE','local');monkeypatch.delenv('VERCEL',raising=False)
    monkeypatch.setattr(main,'STORE',tmp_path)
    files=[]
    for doc in [document('a'),document('b','2026-10-01','2026-10-31',opening='950.00',closing='850.00')]:
        buf=io.BytesIO();pdf=canvas.Canvas(buf,pagesize=(612,792),invariant=True)
        for index,line in enumerate(doc['lines']):pdf.drawString(40,750-index*20,line['text'])
        pdf.save();files.append(('files',(doc['name'],buf.getvalue(),'application/pdf')))
    with TestClient(main.app) as client:
        created=client.post('/api/analyze',files=files);assert created.status_code==200,created.text
        report=created.json();base='/api/cases/'+report['id']
        response=client.get(base+'/historical');assert response.status_code==200
        result=response.json();assert response.headers['cache-control']=='no-store'
        assert result['pairs'][0]['difference']=='50.00' and len(result['policy_sha256'])==64
        assert result['case_id']==report['id'] and result['report_version']==0
        source=result['pairs'][0]['sources'][0]
        image=client.get(base+'/documents/'+source.split(':')[0]+'/page/1',params={'source':source})
        assert image.status_code==200 and image.headers['content-type']=='image/png'
        assert client.get(base).json()==report  # Read-only policy evaluation.
        assert client.get('/api/cases/'+'0'*32+'/historical').status_code==404

def test_same_period_balances_cite_both_sources():
    pair, = evaluate_history([
        document('a'), document('b', opening='950.00', closing='850.00'),
    ])['pairs']
    assert pair['result'] == 'discrepancy'
    assert pair['reason'] == 'same_period_balances'
    assert pair['balance_field'] == 'opening'
    assert pair['difference'] == '50.00'
    assert len(set(pair['balance_sources'])) == 2
    assert [item['balance_field'] for item in pair['balance_differences']] == ['opening', 'closing']
