import copy
import io
import json
import logging
import pytest
from reportlab.pdfgen import canvas
from uvicorn.logging import AccessFormatter
from app.privacy import redact,report_for_export,install_log_redaction,markdown_text
from app.trace import record
from test_api import client
from test_service import service,login

PRIVATE=['PRIVATE-LOAN-65890123','Avery Example','avery@example.invalid','123-45-6789','202-555-0148','42 Fictional Lane']

def private_pdf():
    stream=io.BytesIO();page=canvas.Canvas(stream)
    for index,line in enumerate(['Loan: '+PRIVATE[0],'Borrower: '+PRIVATE[1],'Email: '+PRIVATE[2],
        'SSN: '+PRIVATE[3],'Phone: '+PRIVATE[4],'Address: '+PRIVATE[5],
        'Currency: USD','Period end: 2026-10-31','Tranche T1 | Principal: 1000.00 | Interest: 100.00',
        'Stated principal plus interest total: 1150.00']):page.drawString(50,790-index*24,line)
    page.save();return stream.getvalue()

def assert_private_export(client,headers=None):
    raw=private_pdf()
    response=client.post('/api/analyze',files={'files':('Avery Example.pdf',raw,'application/pdf')},headers=headers or {})
    assert response.status_code==200,response.text
    original=response.json();base='/api/cases/'+original['id']
    assert original['status']=='discrepancies' and original['findings'][0]['difference']=='50.00'
    assert original['documents'][0]['statement']['loan_id']==PRIVATE[0]
    note='Email: avery@example.invalid | SSN: 123-45-6789 | Call +1 202-555-0148'
    saved=client.patch(base+'/findings/F1',json={'action':'note','note':note,'expected_revision':0},headers=headers or {})
    assert saved.status_code==200,saved.text
    assert saved.json()['findings'][0]['human_review']['history'][0]['note']==note
    assert PRIVATE[2] not in json.dumps(saved.json()['trace'])
    exported=client.get(base+'/export').json();markdown=client.get(base+'/export?format=md').text
    serialized=json.dumps(exported)
    for value in PRIVATE:assert value not in serialized and value not in markdown
    assert exported['privacy']['redacted'] and not exported['privacy']['originals_included']
    assert exported['calculations']==original['calculations']
    assert exported['findings'][0]['difference']=='50.00'
    source=exported['findings'][0]['sources'][0]
    lines={line['id']:line for doc in exported['documents'] for line in doc['lines']}
    assert '1000.00' in lines[source]['text'] and '100.00' in lines[source]['text']
    assert client.get(base+'/documents/doc1').content==raw
    assert client.get(base).json()['documents'][0]['statement']['loan_id']==PRIVATE[0]

def test_local_exports_and_trace_redact_without_changing_private_record(client):assert_private_export(client)

def test_service_exports_and_trace_redact_without_changing_private_record(service):
    client,_,_=service;assert_private_export(client,login(client))

def test_recursive_trace_redaction_preserves_amounts_and_input():
    inputs={'loan_id':PRIVATE[0],'text':'Borrower: Avery Example | Interest: 100.00',
        'nested':[{'email':PRIVATE[2],'amount':'100.00','source':'doc1:p1:l9'}]}
    before=copy.deepcopy(inputs);events=[];event=record(events,'tool','search_evidence',inputs,{'computed':'1100.00'})
    assert inputs==before
    assert PRIVATE[0] not in json.dumps(event) and PRIVATE[1] not in json.dumps(event) and PRIVATE[2] not in json.dumps(event)
    assert event['input']['nested'][0]['source']=='doc1:p1:l9'
    assert event['input']['nested'][0]['amount']=='100.00' and event['output']['computed']=='1100.00'

def test_export_is_pure_idempotent_and_duplicate_filenames_are_distinct():
    value={'documents':[{'id':'doc1','name':'Avery Example.pdf','statement':{'loan_id':PRIVATE[0]}},
        {'id':'doc2','name':'Avery Example.pdf','statement':{'loan_id':PRIVATE[0]}}],
        'calculations':[{'operands':['1000.00','100.00'],'computed':'1100.00','sources':['doc1:p1:l9']}]}
    before=copy.deepcopy(value);exported=report_for_export(value)
    assert value==before and exported==report_for_export(exported)
    assert [doc['name'] for doc in exported['documents']]==['doc1.pdf','doc2.pdf']
    assert exported['calculations']==value['calculations']

@pytest.mark.parametrize('value',['1000.00','-25.00','2026-10-31','doc1:p1:l9','T1','USD','3300.00'])
def test_redaction_preserves_financial_tokens(value):assert redact(value)==value

def test_logging_redacts_args_queries_secrets_and_exception_text(caplog,monkeypatch):
    install_log_redaction();monkeypatch.setenv('MODEL_API_KEY','synthetic-secret-never-print-123456789')
    logger=logging.getLogger('paper_trail.privacy_test')
    with caplog.at_level(logging.INFO):
        logger.info('Contact %s at %s',PRIVATE[2],'/api/cases?q=PRIVATE-LOAN-65890123')
        try:raise RuntimeError('avery@example.invalid synthetic-secret-never-print-123456789')
        except RuntimeError:logger.exception('Synthetic exception')
    assert PRIVATE[0] not in caplog.text and PRIVATE[2] not in caplog.text
    assert 'synthetic-secret-never-print-123456789' not in caplog.text
    assert '[REDACTED_QUERY]' in caplog.text and 'RuntimeError' in caplog.text

def test_uvicorn_access_formatter_still_accepts_sanitized_arg_tuple():
    factory=logging.getLogRecordFactory()
    value=factory('uvicorn.access',logging.INFO,__file__,1,'%s - "%s %s HTTP/%s" %d',
        ('127.0.0.1:1234','GET','/api/cases?q=avery%40example.invalid','1.1',200),None)
    rendered=AccessFormatter('%(request_line)s %(status_code)s',use_colors=False).format(value)
    assert 'avery' not in rendered and '200' in rendered and '[REDACTED_QUERY]' in rendered

def test_markdown_evidence_cannot_embed_html_or_link_instructions():
    untrusted='<script>alert(1)</script>\n![image](https://example.invalid/track)'
    escaped=markdown_text(untrusted)
    assert '<script>' not in escaped and '![image]' not in escaped and '\n' not in escaped
    assert 'example.invalid' in escaped


def test_search_body_keeps_private_filters_out_of_request_url(service):
    client,_,_=service;headers=login(client)
    response=client.post('/api/analyze',files={'files':('synthetic.pdf',private_pdf(),'application/pdf')},headers=headers)
    assert response.status_code==200
    client.cookies.clear();headers=login(client,'viewer@example.invalid')
    search=client.post('/api/cases/search',json={'q':PRIVATE[0],'status':'discrepancies'},headers=headers)
    assert search.status_code==200 and search.json()['total_in_window']==1
    assert not search.request.url.query
    assert client.post('/api/cases/search',json={'q':PRIVATE[0]}).status_code==403
    assert client.post('/api/cases/search',json={'q':'x'*201},headers=headers).status_code==422


def test_local_search_body_and_export_html_safety(client):
    response=client.post('/api/analyze',files={'files':('synthetic.pdf',private_pdf(),'application/pdf')})
    base='/api/cases/'+response.json()['id']
    note='<img src="https://example.invalid/track"> ![x](https://example.invalid)'
    assert client.patch(base+'/findings/F1',json={'action':'note','note':note,'expected_revision':0}).status_code==200
    search=client.post('/api/cases/search',json={'q':PRIVATE[0]})
    assert search.status_code==200 and search.json()['total_in_window']==1
    markdown=client.get(base+'/export?format=md').text
    assert '<img' not in markdown and '![x]' not in markdown


def test_legacy_trace_is_redacted_on_read_without_rewriting_service_version(service):
    import uuid
    client,repo,_=service;headers=login(client)
    response=client.post('/api/analyze',files={'files':('Avery Example.pdf',private_pdf(),'application/pdf')},headers=headers)
    legacy=response.json();legacy['id']=uuid.uuid4().hex
    legacy['trace'].append({'id':'old','output':'avery@example.invalid Avery Example.pdf','input':{'loan_id':PRIVATE[0]}})
    repo.create_case('team-a','legacy-import',legacy,[private_pdf()])
    returned=client.get('/api/cases/'+legacy['id'],params={'version':1}).json()
    assert PRIVATE[2] not in json.dumps(returned['trace']) and 'Avery Example.pdf' not in json.dumps(returned['trace'])
    assert returned['documents'][0]['name']=='Avery Example.pdf'
    assert repo.get_case('team-a',legacy['id'],1)==legacy
