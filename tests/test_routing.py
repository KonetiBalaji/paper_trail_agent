import copy
import io
import json
import pytest
from reportlab.pdfgen import canvas
from app import main,meta
from app.telemetry import usage
from test_api import client,upload,ROOT

def investigation(docs,findings,calculations,trace=None):
    assert calculations
    return {'summary':'Synthetic investigation','sources':[],'checklist':[],'tool_trace':[]}

def test_auto_routes_complete_layout_to_local_extraction_but_runs_investigation(client,monkeypatch):
    monkeypatch.setenv('MODEL_API_KEY','synthetic-key')
    monkeypatch.setattr(meta,'extract',lambda *a,**k:pytest.fail('Recognized layout must not be re-extracted by model'))
    monkeypatch.setattr(meta,'reason',investigation)
    result=upload(client,'contradiction','auto');assert result.status_code==200,result.text
    report=result.json();assert report['findings'][0]['difference']=='25.00'
    assert all(doc['routing']['selected']=='local' for doc in report['documents'])
    assert report['agent']['summary']=='Synthetic investigation'
    assert sum(event['kind']=='routing' for event in report['trace'])==2

def test_auto_unknown_format_calls_grounded_model_extraction(client,monkeypatch):
    monkeypatch.setenv('MODEL_API_KEY','synthetic-key');called=[]
    stream=io.BytesIO();pdf=canvas.Canvas(stream)
    for index,line in enumerate(['Unrecognized financial layout','Loan: UNKNOWN-1','Currency: USD','Period end: 2026-10-31',
        'Facility X principal 1000.00 interest 100.00','Total amount 1100.00']):pdf.drawString(40,750-index*25,line)
    pdf.save()
    def extract(doc,trace=None):
        called.append(doc['id'])
        statement=main.parse_statement({'lines':[]})
        statement.update(loan_id='UNKNOWN-1',currency='USD',period_end='2026-10-31',
            tranches=[{'id':'X','principal':'1000.00','interest':'100.00','source':doc['lines'][4]['id']}],stated_total='1100.00',total_source=doc['lines'][5]['id'])
        return statement
    monkeypatch.setattr(meta,'extract',extract);monkeypatch.setattr(meta,'reason',investigation)
    response=client.post('/api/analyze',files={'files':('unknown.pdf',stream.getvalue(),'application/pdf')},data={'mode':'auto'})
    assert response.status_code==200,response.text
    assert called==['doc1'] and response.json()['documents'][0]['routing']['selected']=='meta'

def test_auto_failure_and_missing_key_never_become_clean(client,monkeypatch):
    assert upload(client,'clean','auto').status_code==503
    monkeypatch.setenv('MODEL_API_KEY','synthetic-key')
    def failed(*args,**kwargs):raise meta.MetaError('Synthetic provider failure')
    monkeypatch.setattr(meta,'reason',failed)
    report=upload(client,'clean','auto').json()
    assert report['status']=='review' and report['agent_error']

def test_usage_counts_unknowns_and_configured_cost_without_inventing_tokens(monkeypatch):
    monkeypatch.setenv('META_INPUT_USD_PER_MILLION','1.00');monkeypatch.setenv('META_OUTPUT_USD_PER_MILLION','2.00')
    trace=[{'kind':'model','validation':'passed','output':{'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150}}}]
    result=usage(trace,12.345)
    assert result['analysis_ms']==12.35 and result['estimated_cost_usd']=='0.00020000'
    assert result['provider_usage_complete'] and result['reported_tokens']['total_tokens']==150
    trace.append({'kind':'model','validation':'passed','output':{'usage':None}})
    result=usage(trace,20);assert not result['provider_usage_complete'] and result['estimated_cost_usd'] is None
    assert result['calls_with_reported_usage']==1 and result['attempted_model_calls']==2
    trace=[{'kind':'model','validation':'passed','output':{'usage':{'completion_tokens':50}}}]
    assert usage(trace,10)['reported_tokens']['prompt_tokens'] is None

def test_failed_call_keeps_total_cost_unknown(monkeypatch):
    monkeypatch.setenv('META_INPUT_USD_PER_MILLION','1');monkeypatch.setenv('META_OUTPUT_USD_PER_MILLION','2')
    events=[{'kind':'model','validation':'passed','output':{'usage':{'prompt_tokens':100,'completion_tokens':20}}},
        {'kind':'model','validation':'failed','output':{'error':'Provider request failed'}}]
    assert usage(events,1)['estimated_cost_usd'] is None

def test_request_usage_metadata_is_not_sent_back_to_provider(monkeypatch):
    import httpx
    monkeypatch.setenv('MODEL_API_KEY','synthetic-key');seen=[]
    def response(url,**kwargs):
        seen.append(copy.deepcopy(kwargs['json']))
        return httpx.Response(200,json={'choices':[{'message':{'content':'{}'}}],
            'usage':{'prompt_tokens':100,'completion_tokens':2,'total_tokens':102,'invalid':1}})
    monkeypatch.setattr(meta.httpx,'post',response);events=[]
    message=meta.model_call([{'role':'user','content':'Synthetic request'}],None,events,'extraction')
    assert '__provider_usage' not in message
    assert events[0]['output']['usage']=={'prompt_tokens':100,'completion_tokens':2,'total_tokens':102}
    meta.model_call([{'role':'assistant',**message}],None,events,'investigation')
    assert '__provider_usage' not in json.dumps(seen)
