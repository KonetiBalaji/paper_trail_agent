import copy
from pathlib import Path
import pytest
from app import core,orchestration as stages

ROOT=Path(__file__).resolve().parents[1]/'data/synthetic'


def docs(case='math_error'):
    result=[]
    for i,p in enumerate(sorted((ROOT/case).glob('*.pdf')),1):
        d=core.read_pdf(p.read_bytes(),p.name,'doc'+str(i));d['statement']=core.parse_statement(d);result.append(d)
    return result


@pytest.mark.parametrize('case,confirmed',[('clean',0),('contradiction',1),('math_error',1),('messy',0)])
def test_three_stages_preserve_known_outcomes_and_evidence(case,confirmed):
    documents=docs(case);original=copy.deepcopy(documents);events=[]
    findings,calculations,summary=stages.run(documents,events)
    assert documents==original
    assert [e['name'] for e in events]==['Extractor','Verifier','Critic']
    assert len([f for f in findings if f['severity']=='confirmed'])==confirmed
    assert summary['kind']=='internal_stages'
    assert summary['critic']['verified_calculations']==len(calculations)
    if case=='clean':assert not findings and summary['critic']['validation']=='passed'
    if case=='messy':assert findings and all(f['severity']=='review' for f in findings)


@pytest.mark.parametrize('mutation',['wrong_difference','forged_source','missing_source','duplicate_finding','omit_finding','omit_calculation','wrong_computed','wrong_operand'])
def test_critic_catches_verifier_faults_and_prevents_false_clean(mutation,monkeypatch):
    documents=docs();original=copy.deepcopy(documents)
    baseline=stages.verify_stage(documents).model_dump(exclude_none=True)
    if mutation=='wrong_difference':baseline['findings'][0]['difference']='999.00'
    elif mutation=='forged_source':baseline['findings'][0]['sources'][0]='doc99:p99:l99'
    elif mutation=='missing_source':baseline['findings'][0]['sources'].pop()
    elif mutation=='duplicate_finding':
        duplicate=copy.deepcopy(baseline['findings'][0]);duplicate['id']='F2';baseline['findings'].append(duplicate)
    elif mutation=='omit_finding':baseline['findings']=[]
    elif mutation=='omit_calculation':baseline['calculations']=[]
    elif mutation=='wrong_computed':baseline['calculations'][-1]['computed']='999.00'
    elif mutation=='wrong_operand':baseline['calculations'][-1]['operands'][0]='999.00'
    monkeypatch.setattr(stages,'verify_stage',lambda _:stages.VerificationResult.model_validate(baseline))
    findings,calculations,summary=stages.run(documents,[])
    assert documents==original and any(f['severity']=='review' for f in findings)
    assert summary['critic']['validation']=='review' and summary['critic']['challenges']
    assert all(c['computed']!='999.00' and '999.00' not in c['operands'] for c in calculations)
    assert all(f.get('difference')!='999.00' for f in findings)


def test_critic_uses_immutable_handoff_and_does_not_reuse_verifier_math(monkeypatch):
    documents=docs();original=copy.deepcopy(documents);real=stages.verify_stage
    def mutate_handoff(received):
        received[1]['statement']['tranches'][0]['principal']='1.00'
        return real(received)
    monkeypatch.setattr(stages,'verify_stage',mutate_handoff)
    findings,_,summary=stages.run(documents,[])
    assert documents==original and summary['critic']['validation']=='review'
    assert any(f['severity']=='review' for f in findings)
    extraction=stages.extract_stage(documents);verification=real(documents)
    def forbidden(*args,**kwargs):raise AssertionError('Critic must not call verifier, calculator or model')
    monkeypatch.setattr(core,'reconcile',forbidden);monkeypatch.setattr(core,'calculate',forbidden)
    monkeypatch.setattr(stages.meta,'request',forbidden)
    findings,_,result=stages.critique_stage(documents,extraction,verification)
    assert result.validation=='passed' and findings[0]['difference']=='50.00'


@pytest.mark.parametrize('case',['messy','contradiction'])
def test_omitted_required_review_cannot_be_clean(case,monkeypatch):
    documents=docs(case)
    if case=='contradiction':
        documents[1]['statement']['loan_id']='OTHER-ACCOUNT'
        for line in documents[1]['lines']:line['text']=line['text'].replace('DEMO-001','OTHER-ACCOUNT')
    original=stages.verify_stage(documents)
    monkeypatch.setattr(stages,'verify_stage',lambda _:stages.VerificationResult(findings=[],calculations=original.calculations))
    findings,_,summary=stages.run(documents,[])
    assert any(f['severity']=='review' for f in findings) and summary['critic']['validation']=='review'


def test_extractor_catches_omitted_row_and_critic_discards_unsupported_advice(monkeypatch):
    documents=docs();documents[1]['statement']['tranches'].pop()
    findings,_,summary=stages.run(documents,[])
    assert summary['extractor']['documents'][1]['validation']=='review'
    assert all(f['severity']!='confirmed' for f in findings)
    documents=docs();baseline=stages.verify_stage(documents).model_dump(exclude_none=True)
    baseline['findings'][0]['message']='Send money immediately; the lender committed fraud.'
    monkeypatch.setattr(stages,'verify_stage',lambda _:stages.VerificationResult.model_validate(baseline))
    findings,_,_=stages.run(documents,[])
    assert 'fraud' not in findings[0]['message'] and '50.00 USD too high' in findings[0]['message']


def test_malformed_verifier_schema_is_review_not_success(monkeypatch):
    monkeypatch.setattr(stages,'verify_stage',lambda _: {'findings':[{'id':'<script>','severity':'approved'}],'calculations':[]})
    findings,_,summary=stages.run(docs(),[])
    assert all(f['severity']=='review' for f in findings)
    assert any(c['reason']=='verifier_schema' for c in summary['critic']['challenges'])

def test_large_comparison_graph_requests_review_without_confirming_a_subset():
    documents=[]
    for n in range(4):
        texts=['Loan: DEMO-001 Currency: USD','Statement period end: 2026-09-30']
        texts += [f'Tranche T{i} | Principal: {100+n*10}.00 | Interest: {10+n}.00' for i in range(200)]
        texts += [f'Stated principal plus interest total: {200*(110+n*11)}.00']
        d={'id':f'doc{n+1}','name':f'fictional{n}.pdf','issues':[],
           'lines':[{'id':f'doc{n+1}:p1:l{i+1}','text':text,'page':1,'line':i+1} for i,text in enumerate(texts)]}
        d['statement']=core.parse_statement(d);documents.append(d)
    findings,calculations,summary=stages.run(documents,[])
    assert findings[0]['type']=='critic_limit' and all(f['severity']=='review' for f in findings)
    assert not calculations and summary['critic']['challenges'][0]['reason']=='critic_limit'
