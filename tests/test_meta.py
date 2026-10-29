import json
import pytest
from app import meta
from test_core import documents

def test_grounding_rejects_hallucinated_values():
    doc=documents('clean')[0]
    assert meta.validate_statement(doc['statement'],doc)['stated_total']=='3300.00'
    doc['statement']['tranches'][0]['interest']='999.00'
    with pytest.raises(ValueError):meta.validate_statement(doc['statement'],doc)

def test_grounding_rejects_forged_source():
    doc=documents('clean')[0];doc['statement']['tranches'][0]['source']='fake'
    with pytest.raises(ValueError):meta.validate_statement(doc['statement'],doc)

def test_grounding_rejects_substring_amount():
    doc=documents('clean')[0]
    doc['statement']['tranches'][0]['principal']='0.00'
    with pytest.raises(ValueError):meta.validate_statement(doc['statement'],doc)

def test_extract_validated_contract(monkeypatch):
    doc=documents('clean')[0]
    monkeypatch.setattr(meta,'request',lambda *args:{'content':json.dumps(doc['statement'])})
    assert meta.extract(doc)==doc['statement']

def test_extract_bad_json_is_review(monkeypatch):
    monkeypatch.setattr(meta,'request',lambda *args:{'content':'not json'})
    with pytest.raises(meta.MetaError,match='review'):meta.extract(documents('clean')[0])

def test_swapped_principal_interest_rejected():
    doc=documents('clean')[0];t=doc['statement']['tranches'][0]
    t['principal'],t['interest']=t['interest'],t['principal']
    with pytest.raises(ValueError):meta.validate_statement(doc['statement'],doc)

def test_omitted_row_rejected():
    doc=documents('clean')[0];doc['statement']['tranches'].pop()
    with pytest.raises(ValueError,match='omitted'):meta.validate_statement(doc['statement'],doc)

def test_agent_tool_loop(monkeypatch):
    docs=documents('clean');source=next(l['id'] for l in docs[0]['lines'] if 'Tranche T1' in l['text'])
    replies=iter([
        {'role':'assistant','content':None,'tool_calls':[{'id':'a','type':'function','function':{'name':'search_evidence','arguments':json.dumps({'query':'T1 principal'})}}]},
        {'role':'assistant','content':None,'tool_calls':[{'id':'b','type':'function','function':{'name':'calculator','arguments':json.dumps({'values':['1000.00','100.00']})}}]},
        {'role':'assistant','content':json.dumps({'summary':'Verified evidence.','checklist':['Review source.'],'sources':[source]})}])
    monkeypatch.setattr(meta,'request',lambda *args:next(replies))
    result=meta.reason(docs,[],[])
    assert result['tool_trace'][1]['result']=={'sum':'1100.00'}
    assert result['sources']==[source]

def test_agent_rejects_unretrieved_citation(monkeypatch):
    monkeypatch.setattr(meta,'request',lambda *args:{'content':json.dumps({'summary':'Claim','checklist':[],'sources':['fake']})})
    with pytest.raises(meta.MetaError):meta.reason(documents('clean'),[],[])

def test_tool_budget(monkeypatch):
    monkeypatch.setattr(meta,'request',lambda *args:{'role':'assistant','content':None,'tool_calls':[{'id':'a','type':'function','function':{'name':'calculator','arguments':'{}'}}]})
    with pytest.raises(meta.MetaError,match='budget'):meta.reason(documents('clean'),[],[])

@pytest.mark.parametrize('code',[401,429,500])
def test_provider_error_is_safe(monkeypatch,code):
    import httpx
    monkeypatch.setenv('MODEL_API_KEY','secret-do-not-log')
    monkeypatch.setattr(meta.httpx,'post',lambda *a,**k:httpx.Response(code))
    with pytest.raises(meta.MetaError) as err:meta.request([])
    assert str(code) in str(err.value) and 'secret-do-not-log' not in str(err.value)
