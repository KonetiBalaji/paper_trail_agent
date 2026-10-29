import copy
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from app import main,meta,evals
from test_api import client,upload
from test_core import documents

def test_eval_endpoint_offline(client,monkeypatch):
    monkeypatch.setattr(meta,'request',lambda *a:pytest.fail('Evals must not call a model'))
    r=client.get('/api/evals');assert r.status_code==200
    data=r.json();s=data['summary']
    assert s['passed']==6 and s['failed']==0 and s['at_risk_count']==4
    assert s['false_clean_rate']==0 and s['citation_accuracy']==1
    assert data['model_calls']==0 and len(data['cases'])==6
    cases={row['case']:row for row in data['cases']}
    assert cases['contradiction']['differences']==['25.00']
    assert cases['math_error']['differences']==['50.00']
    assert cases['clean']['citation_accuracy'] is None
    assert cases['messy']['status']=='review' and cases['messy']['review_count']==2

def test_eval_detects_false_clean_and_does_not_fake_pass(monkeypatch):
    monkeypatch.setattr(evals,'reconcile',lambda docs:([],[]))
    result=evals.evaluate_suite();s=result['summary']
    # The bank clean control also fails because its expected calculation disappeared.
    assert s['failed']==5 and s['false_clean_count']==4 and s['false_clean_rate']==1

def test_eval_detects_invalid_citations(monkeypatch):
    real=evals.reconcile
    def invalid(docs):
        findings,calculations=real(docs)
        for f in findings:
            if f['severity']=='confirmed':f['sources']=['forged-source']
        return findings,calculations
    monkeypatch.setattr(evals,'reconcile',invalid)
    result=evals.evaluate_suite()
    assert result['summary']['failed']==3 and result['summary']['citation_accuracy']==0

def test_eval_fixture_failure_visible(monkeypatch):
    def fail(*args):raise ValueError('no fixtures')
    monkeypatch.setattr(evals,'evaluate_case',fail)
    result=evals.evaluate_suite()
    assert result['summary']['failed']==6 and all(c['status']=='error' for c in result['cases'])

def test_review_persists_and_keeps_machine_result(client):
    original=upload(client,'messy').json();case=original['id'];f=original['findings'][0]
    url=f"/api/cases/{case}/findings/{f['id']}"
    for revision,action,note in [(0,'confirm','Looked at scan'),(1,'note','Request clearer PDF'),(2,'reject','Wrong source version')]:
        response=client.patch(url,json={'action':action,'note':note,'expected_revision':revision})
        assert response.status_code==200,response.text
    saved=client.get('/api/cases/'+case).json();finding=saved['findings'][0]
    assert finding['human_review']['decision']=='rejected'
    assert finding['human_review']['revision']==3 and len(finding['human_review']['history'])==3
    assert all(x['timestamp'] for x in finding['human_review']['history'])
    assert {k:v for k,v in finding.items() if k!='human_review'}=={k:v for k,v in f.items() if k!='human_review'}
    assert saved['status']==original['status']=='review' and saved['calculations']==original['calculations']
    exported=client.get('/api/cases/'+case+'/export').json()
    assert exported['privacy']['redacted'] and exported['calculations']==saved['calculations']
    assert exported['findings'][0]['human_review']==finding['human_review']
    markdown=client.get('/api/cases/'+case+'/export?format=md').text
    assert 'Human review: rejected' in markdown and 'Request clearer PDF' in markdown
    assert saved['trace'][-1]['kind']=='human_review'

def test_note_preserves_pending_and_treats_html_as_data(client):
    r=upload(client).json();url=f"/api/cases/{r['id']}/findings/F1"
    note='<script>alert(1)</script>'
    updated=client.patch(url,json={'action':'note','note':note,'expected_revision':0}).json()
    review=updated['findings'][0]['human_review']
    assert review['decision']=='pending' and review['history'][0]['note']==note

@pytest.mark.parametrize('body',[{'action':'change','expected_revision':0},{'action':'note','note':'   ','expected_revision':0},
    {'action':'note','note':'x'*2001,'expected_revision':0},{'action':'confirm','expected_revision':-1},
    {'action':'confirm','expected_revision':True},{'action':'confirm'},
    {'action':'confirm','expected_revision':0,'severity':'clean'}])
def test_invalid_review_rejected_without_mutation(client,body):
    r=upload(client).json();url=f"/api/cases/{r['id']}/findings/F1"
    assert client.patch(url,json=body).status_code==422
    assert client.get('/api/cases/'+r['id']).json()==r

def test_unknown_finding_and_stale_revision(client):
    r=upload(client).json();base='/api/cases/'+r['id']+'/findings/'
    body={'action':'confirm','expected_revision':0}
    assert client.patch(base+'fake',json=body).status_code==404
    assert client.patch(base+'F1',json=body).status_code==200
    assert client.patch(base+'F1',json=body).status_code==409
    assert client.patch('/api/cases/invalid/findings/F1',json=body).status_code==404

def test_parallel_review_conflict_is_safe(client):
    r=upload(client).json();url=f"/api/cases/{r['id']}/findings/F1"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda action:client.patch(url,json={'action':action,'expected_revision':0}).status_code,['confirm','reject']))
    assert sorted(responses)==[200,409]
    review=client.get('/api/cases/'+r['id']).json()['findings'][0]['human_review']
    assert review['revision']==1 and len(review['history'])==1

def test_review_legacy_case(client):
    r=upload(client).json();path=main.STORE/r['id']
    del r['findings'][0]['human_review'];del r['trace']
    main.save_report(path,r)
    response=client.patch(f"/api/cases/{r['id']}/findings/F1",json={'action':'confirm','expected_revision':0})
    assert response.status_code==200 and response.json()['findings'][0]['human_review']['decision']=='confirmed'

def test_local_trace_in_json_and_reopen(client):
    r=upload(client,'math_error').json();events=r['trace']
    assert [e['id'] for e in events]==[f'E{i+1}' for i in range(len(events))]
    assert all(e['timestamp'] and (e['duration_ms'] is None or e['duration_ms']>=0) for e in events)
    total=next(e for e in events if e['name']=='deterministic_total' and e['document']=='doc2')
    assert total['input']['operands']==['1000.00','100.00','2000.00','200.00']
    assert total['output']=={'computed':'3300.00','stated':'3350.00'} and total['finding_ids']==['F1']
    assert r['harness']['cost'] is None
    assert client.get('/api/cases/'+r['id']).json()['trace']==events

def test_extraction_validation_failure_trace(monkeypatch):
    monkeypatch.setattr(meta,'request',lambda *a:{'content':'not json'})
    trace=[]
    with pytest.raises(meta.MetaError):meta.extract(documents('clean')[0],trace)
    assert [e['kind'] for e in trace]==['model','validation']
    assert trace[-1]['validation']=='failed'

def test_tool_trace_inputs_outputs_and_failed_validation(monkeypatch):
    replies=iter([{'role':'assistant','tool_calls':[{'id':'t1','function':{'name':'calculator','arguments':json.dumps({'values':['NaN']})}}]},
        {'content':json.dumps({'summary':'Review required.','checklist':[],'sources':[]})}])
    monkeypatch.setattr(meta,'request',lambda *a:next(replies));events=[]
    result=meta.reason(documents('clean'),[],[],events)
    tool=next(e for e in events if e['kind']=='tool')
    assert tool['input']=={'values':['NaN']} and tool['validation']=='failed'
    assert result['tool_trace'][0]['event_id']==tool['id'] and 'error' in tool['output']

def test_total_tool_budget_enforced(monkeypatch):
    def request(*args):return {'role':'assistant','tool_calls':[{'id':str(i),'function':{'name':'calculator','arguments':'{"values":["1.00"]}'}} for i in range(5)]}
    monkeypatch.setattr(meta,'request',request);events=[]
    with pytest.raises(meta.MetaError,match='budget'):meta.reason(documents('clean'),[],[],events)
    assert len([e for e in events if e['kind']=='tool'])==5
    assert events[-1]['name']=='tool_budget' and events[-1]['validation']=='failed'

def test_provider_failure_trace_does_not_record_credentials(monkeypatch):
    monkeypatch.setenv('MODEL_API_KEY','NEVER-RECORD-SECRET')
    def fail(*args):raise meta.MetaError('Provider unavailable')
    monkeypatch.setattr(meta,'request',fail);events=[]
    with pytest.raises(meta.MetaError):meta.reason(documents('clean'),[],[],events)
    assert events[0]['kind']=='model' and events[0]['validation']=='failed'
    assert 'NEVER-RECORD-SECRET' not in json.dumps(events)

@pytest.mark.parametrize('message',[[],{'tool_calls':'invalid'},{'tool_calls':[None]}])
def test_malformed_provider_message_becomes_review(monkeypatch,message):
    monkeypatch.setattr(meta,'request',lambda *a:message);events=[]
    with pytest.raises(meta.MetaError):meta.reason(documents('clean'),[],[],events)
    assert events[-1]['validation']=='failed'

def test_tool_success_trace_is_ordered_and_grounded(monkeypatch):
    doc=documents('clean')[0];source=doc['statement']['tranches'][0]['source']
    messages=iter([
        {'role':'assistant','tool_calls':[{'id':'t1','function':{'name':'search_evidence','arguments':'{"query":"T1 principal"}'}},
            {'id':'t2','function':{'name':'calculator','arguments':'{"values":["1000.00","100.00"]}'}}]},
        {'content':json.dumps({'summary':'Verified sources.','checklist':[],'sources':[source]})}])
    monkeypatch.setattr(meta,'request',lambda *a:next(messages));events=[]
    result=meta.reason([doc],[],[],events)
    assert [e['kind'] for e in events]==['model','tool','tool','model','validation']
    assert events[1]['input']=={'query':'T1 principal'} and events[1]['output'][0]['id']
    assert events[2]['input']=={'values':['1000.00','100.00']} and events[2]['output']=={'sum':'1100.00'}
    assert all(e['validation']=='passed' for e in events)
    assert result['tool_trace'][1]['result']==events[2]['output']
