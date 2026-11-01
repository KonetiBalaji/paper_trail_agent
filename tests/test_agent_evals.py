import copy
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app import agent_evals,main,core


@pytest.fixture(scope='module')
def scorecard():return agent_evals.evaluate()


def test_agent_components_have_real_denominators_and_visible_weaknesses(scorecard):
    agent_evals.validate_report(scorecard)
    assert scorecard['passed'] and scorecard['generation_model_calls']==0
    assert scorecard['critic']['catch_rate']==agent_evals.rate(30,30)
    assert scorecard['critic']['false_alarm_rate']==agent_evals.rate(0,17)
    assert scorecard['tools']['contract_correctness']==agent_evals.rate(12,12)
    assert scorecard['tools']['retrieval_precision']==agent_evals.rate(2,4)
    assert scorecard['tools']['retrieval_recall']==agent_evals.rate(2,2)
    assert len(scorecard['extraction']['layouts'])==17 and scorecard['extraction']['summary']['total']==19
    assert scorecard['extraction']['fields']['principal']['fn']>0
    assert next(g for g in scorecard['extraction']['layouts'] if g['layout']=='loan_partial')['review_modes']


@pytest.mark.parametrize('mutation',['passed','fault','denominator','false_clean','field_counts'])
def test_report_rejects_inconsistent_pass_flags_and_metrics(scorecard,mutation):
    value=copy.deepcopy(scorecard)
    if mutation=='passed':value['passed']=False
    elif mutation=='fault':value['critic']['review_faults'][0]['caught']=False
    elif mutation=='denominator':value['tools']['contract_correctness']['total']=999
    elif mutation=='false_clean':value['extraction']['summary']['false_clean_count']=1
    elif mutation=='field_counts':value['extraction']['fields']['principal']['tp']+=1
    with pytest.raises(ValueError):agent_evals.validate_report(value)


def test_api_serves_artifact_without_model_calls_and_marks_stale_source(scorecard,tmp_path,monkeypatch):
    path=tmp_path/'score.json';path.write_text(json.dumps(scorecard));monkeypatch.setattr(agent_evals,'REPORT',path)
    monkeypatch.setenv('PAPER_TRAIL_MODE','local');monkeypatch.delenv('VERCEL',raising=False)
    def forbidden(*args):raise AssertionError('Reading scorecard must not call a provider')
    monkeypatch.setattr(main.meta,'request',forbidden)
    with TestClient(main.app) as client:
        response=client.get('/api/agent-evals');assert response.status_code==200
        assert response.json()['current_source_match'] and response.json()['current_fixture_match']
        stale=copy.deepcopy(scorecard);stale['source_sha256']['app/core.py']='0'*64;path.write_text(json.dumps(stale))
        response=client.get('/api/agent-evals');assert response.status_code==200 and not response.json()['current_source_match']
        path.write_text('{bad JSON');assert client.get('/api/agent-evals').status_code==503


def test_fixture_freshness_checks_pdf_bytes_not_just_manifest(scorecard,tmp_path,monkeypatch):
    source=agent_evals.benchmark.ROOT;target=tmp_path/'fixtures';target.mkdir()
    manifest=(source/'manifest.json').read_bytes();(target/'manifest.json').write_bytes(manifest)
    changed=None
    for case in json.loads(manifest)['cases']:
        for entry in case['documents']:
            p=source/case['case']/entry['file']
            if not p.exists():continue
            output=target/case['case']/entry['file'];output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(p.read_bytes());changed=output
    changed.write_bytes(changed.read_bytes()+b'changed')
    path=tmp_path/'score.json';path.write_text(json.dumps(scorecard));monkeypatch.setattr(agent_evals,'REPORT',path)
    monkeypatch.setattr(agent_evals.benchmark,'ROOT',target)
    assert not agent_evals.load_report()['current_fixture_match']


def test_independent_oracle_rejects_extremes_without_using_application_calculator(monkeypatch):
    def forbidden(*args):raise AssertionError('Oracle must be independent')
    monkeypatch.setattr(core,'calculate',forbidden)
    assert agent_evals.exact_sum(['0.10','0.20'])=='0.30'
    for values in (['NaN'],['0.001'],['1e999999999']):
        with pytest.raises(ValueError):agent_evals.exact_sum(values)


def test_live_scores_do_not_conflate_math_with_grounding_or_full_check_coverage(tmp_path):
    first={'id':'doc1:p1:l1','text':'Principal 1000.00 Interest 100.00','page':1,'line':1}
    second={'id':'doc1:p1:l2','text':'Principal 2000.00 Interest 200.00','page':1,'line':2}
    requests=[{'tool':'calculator','input':{'values':['1000.00','100.00']},'result':{'sum':'1100.00'},'validation':'passed','transport':'mcp_stdio'},
              {'tool':'calculator','input':{'values':['42.00']},'result':{'sum':'42.00'},'validation':'passed','transport':'mcp_stdio'},
              {'tool':'search_evidence','input':{'query':'principal'},'result':[first],'validation':'passed','transport':'mcp_stdio'}]
    context={'gold_lines':[first,second],'required_checks':[{'operands':['1000.00','100.00','2000.00','200.00'],'computed':'3300.00'}],
             'verified_differences':[],'required_finding_sources':[first['id'],second['id']],'final_agent_sources':[first['id']],
             'tool_requests':requests,'fields':{},'native_fields':{},'image_abstention_fn':0}
    artifact={'status':'passed','source_sha256':agent_evals.source_hashes(),'cases':[{'case':'unit_fixture','elapsed_seconds':1,'agent_evaluation':context}]}
    path=tmp_path/'live.json';path.write_text(json.dumps(artifact));result=agent_evals.live_metrics(path)['summary']
    assert result['calculator_exactness']==agent_evals.rate(2,2)
    assert result['calculator_input_grounding']==agent_evals.rate(1,2)
    assert result['requests']==agent_evals.rate(2,3)
    assert result['distinct_check_coverage']==agent_evals.rate(0,1)
    assert result['finding_source_retrieval']==agent_evals.rate(1,2)
    requests.append({'tool':'calculator','input':{'values':['200.00','100.00','2000.00','0.00','1000.00']},'result':{'sum':'3300.00'},'validation':'passed','transport':'mcp_stdio'})
    path.write_text(json.dumps(artifact));result=agent_evals.live_metrics(path)['summary']
    assert result['distinct_check_coverage']==agent_evals.rate(1,1)
    assert result['requests']==agent_evals.rate(3,4)


def test_agent_prompt_exposes_budget_and_unsearchable_evidence(monkeypatch):
    captured={}
    def respond(messages,tools):
        captured['developer']=messages[0]['content'];captured['data']=json.loads(messages[1]['content'])
        return {'content':json.dumps({'summary':'Manual review required.','checklist':['Inspect the original image.'],'sources':[]})}
    monkeypatch.setattr(main.meta,'request',respond)
    main.meta.reason([{'id':'doc1','name':'fictional.pdf','lines':[],'issues':[{'type':'ocr_required'}]}],[],[])
    assert '8 tool calls total' in captured['developer'] and '6 investigation turns' in captured['developer']
    assert 'Tools cannot perform OCR' in captured['developer']
    assert captured['data']['documents'][0]['available_text_lines']==0
    assert captured['data']['documents'][0]['extraction_issues']==['ocr_required']
