"""Independent bank statement PDFs, generated in memory; no fixture-label dependency."""
import io
from reportlab.pdfgen import canvas
import pytest
from app.core import read_pdf,parse_statement,reconcile
from app.meta import validate_statement

def bank_document(closing='975.00',doc_id='bank1',period='2026-10-31',duplicate=False):
    buf=io.BytesIO();c=canvas.Canvas(buf)
    lines=['Account: BANK-DEMO Currency: USD',f'Statement period end: {period}',
           'Opening balance: 1,000.00','Transaction PAY-1 | 2026-10-05 | Amount: +100.00',
           'Transaction FEE-1 | 2026-10-10 | Amount: (125.00)',f'Closing balance: {closing}']
    if duplicate:lines.insert(5,lines[4])
    for i,line in enumerate(lines):c.drawString(30,780-i*30,line)
    c.save();doc=read_pdf(buf.getvalue(),'bank.pdf',doc_id);doc['statement']=parse_statement(doc);return doc

def test_bank_clean():
    doc=bank_document();findings,calculations=reconcile([doc])
    assert findings==[] and calculations[0]['computed']=='975.00'
    assert doc['statement']['transactions'][1]['amount']=='-125.00'

def test_bank_closing_error():
    findings,_=reconcile([bank_document('1000.00')])
    assert len(findings)==1 and findings[0]['type']=='incorrect_closing_balance'
    assert findings[0]['difference']=='25.00' and len(findings[0]['sources'])==4

def test_bank_duplicate_is_review():
    findings,calculations=reconcile([bank_document(duplicate=True)])
    assert len(findings)==1 and findings[0]['severity']=='review' and calculations==[]

def test_bank_cross_document_balance():
    docs=[bank_document(),bank_document('1000.00','bank2')]
    findings,_=reconcile(docs)
    assert any(f['type']=='cross_document_closing_balance_mismatch' and f['difference']=='25.00' for f in findings)

def test_bank_period_guard():
    findings,_=reconcile([bank_document(),bank_document('975.00','bank2','2026-09-30')])
    assert [f['type'] for f in findings]==['period_mismatch']

def test_bank_meta_grounding_signed_parentheses():
    doc=bank_document()
    validated=validate_statement(doc['statement'],doc)
    assert validated['transactions'][1]['amount']=='-125.00'

def test_partial_transaction_prevents_false_arithmetic_finding():
    doc=bank_document()
    doc['lines'].append({'id':'bank1:p1:l7','text':'Transaction X | 2026-10-25 | Amount: UNKNOWN'})
    doc['statement']=parse_statement(doc)
    findings,calculations=reconcile([doc])
    assert all(f['severity']=='review' for f in findings)
    assert calculations==[]

def test_bank_fixture_pdfs(tmp_path):
    import json
    from scripts.generate_bank_fixtures import generate,ROOT
    for case,path in generate(tmp_path).items():
        truth=json.loads((ROOT/case/'ground_truth.json').read_text())
        doc=read_pdf(path.read_bytes(),path.name,'bank1');doc['statement']=parse_statement(doc)
        findings,calculations=reconcile([doc])
        assert len(findings)==truth['expected_confirmed_contradictions']
        assert calculations[0]['computed']==truth['computed_closing_balance']
        index={l['id'] for l in doc['lines']}
        if case=='bank_error':
            assert findings[0]['type']=='incorrect_closing_balance'
            assert findings[0]['difference']=='25.00' and set(findings[0]['sources'])<=index
