"""Agent scorecard: independent oracles, controlled faults and live call evidence.

Generation is offline except for local MCP subprocesses. The public API serves
the saved report with explicit source/fixture freshness, never calls a model.
"""
import asyncio
from collections import Counter,defaultdict
import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from datetime import datetime,timezone
from . import benchmark,orchestration as stages
from .mcp_client import CaseTools

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'docs/agent-evals-results.json'
LAYOUTS={
    'loan_columns_clean':'loan_columns','loan_columns_error':'loan_columns','loan_columns_contradiction':'loan_columns',
    'loan_reverse_columns':'loan_reverse','loan_cross_page':'loan_cross_page','loan_split_row':'loan_linked_split',
    'loan_duplicate':'loan_duplicate','loan_partial':'loan_partial','bank_debit_credit':'bank_debit_credit',
    'bank_signed':'bank_signed','bank_cross_page':'bank_cross_page','bank_bad_carry':'bank_carried_balance',
    'injection_note':'prompt_injection_note','identity_conflict':'identity_conflict','ambiguous_date':'ambiguous_date',
    'currency_guard':'currency_mismatch','missing_tranche':'missing_tranche','corrupt_pdf':'corrupt_pdf','oversized_pdf':'oversized_pdf'}


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def source_hashes():return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_text(encoding='utf-8').encode()).hexdigest() for p in sorted((ROOT/'app').glob('*.py'))}
def rate(n,d):return {'correct':n,'total':d,'rate':n/d if d else None}


def exact_sum(values):
    """Independent decimal oracle; does not use the application calculator."""
    total=Decimal('0')
    for value in values:
        if not isinstance(value,str):raise ValueError('Monetary string required')
        value=value.strip().replace(',','').replace('$','')
        if value.startswith('(') and value.endswith(')'):value='-'+value[1:-1]
        n=Decimal(value)
        if not n.is_finite() or n.copy_abs()>Decimal('1000000000000000') or n!=n.quantize(Decimal('.01')):raise ValueError('Unsupported amount')
        total+=n
    return format(total,'.2f')


def check_key(values):
    # Addition is commutative. Keep multiplicity, normalize formatting, and
    # ignore neutral zero addends without pretending no-call coverage exists.
    return tuple(sorted(n for v in values if (n:=exact_sum([v]))!='0.00'))


def signature(files):
    hashes=[]
    for file in files:
        position=file.file.tell();hashes.append(hashlib.sha256(file.file.read()).hexdigest());file.file.seek(position)
    return tuple(hashes)


def corpus():
    from .main import analyze_files
    captured={}
    def analyze(files,mode,persist=False):
        key=signature(files);report=analyze_files(files,mode,persist=False);captured[key]=report;return report
    result=benchmark.evaluate_suite(analyzer=analyze)
    manifest=json.loads((benchmark.ROOT/'manifest.json').read_text(encoding='utf-8'))
    reports={case['case']:captured.get(tuple(d['sha256'] for d in case['documents'])) for case in manifest['cases']}
    return result,reports


def layout_metrics(result,reports):
    grouped={}
    for row in result['cases']:
        family=LAYOUTS[row['case']]
        group=grouped.setdefault(family,{'layout':family,'cases':0,'failed_cases':0,'review_cases':0,'false_clean':0,'fields':{},'failure_modes':[],'review_modes':{}})
        group['cases']+=1;group['failed_cases']+=not row['passed'];group['review_cases']+=row['status']=='review';group['false_clean']+=row['false_clean']
        for field,values in row['fields'].items():
            counts=group['fields'].setdefault(field,{'tp':0,'fp':0,'fn':0})
            for key in counts:counts[key]+=values[key]
        for error in row['errors']:group['failure_modes'].append({'case':row['case'],'reason':error})
        report=reports.get(row['case'])
        if report:
            for kind in {f['type'] for f in report['findings'] if f['severity']=='review'}:
                group['review_modes'][kind]=group['review_modes'].get(kind,0)+1
    for group in grouped.values():group['fields']={k:benchmark.ratios(v) for k,v in group['fields'].items()}
    return list(grouped.values())


FAULTS=('wrong_difference','forged_source','missing_finding','duplicate_finding','missing_calculation','wrong_computed','wrong_operand','wrong_calculation_source','empty_output','invalid_schema')


def critic_metrics(reports):
    controls=[];faults=[];rewrites=[]
    for name,report in reports.items():
        if report is None:continue
        summary=report['orchestration']['critic']
        controls.append({'case':name,'layout':LAYOUTS[name],'false_alarm':bool(summary['challenges'])})
    for name in ('loan_columns_error','loan_columns_contradiction','bank_bad_carry'):
        report=reports.get(name)
        if report is None:raise ValueError('Required critic fixture unavailable')
        documents=report['documents'];base=stages.verify_stage(copy.deepcopy(documents)).model_dump(exclude_none=True)
        golden=Counter(stages.claim_key(f) for f in base['findings'] if f['severity']=='confirmed')
        for fault in FAULTS:
            changed=copy.deepcopy(base);f=next(f for f in changed['findings'] if f['severity']=='confirmed')
            if fault=='wrong_difference':f['difference']='999.00'
            elif fault=='forged_source':f['sources'][0]='doc99:p99:l99'
            elif fault=='missing_finding':changed['findings'].remove(f)
            elif fault=='duplicate_finding':
                duplicate=copy.deepcopy(f);duplicate['id']='F'+str(len(changed['findings'])+1);changed['findings'].append(duplicate)
            elif fault=='missing_calculation':changed['calculations'].pop()
            elif fault=='wrong_computed':changed['calculations'][0]['computed']='999.00'
            elif fault=='wrong_operand':changed['calculations'][0]['operands'][0]='999.00'
            elif fault=='wrong_calculation_source':changed['calculations'][0]['sources'][0]='doc99:p99:l99'
            elif fault=='empty_output':changed['findings']=[];changed['calculations']=[]
            elif fault=='invalid_schema':f['severity']='approved'
            if changed==base:raise ValueError('Fault did not change the handoff')
            findings,calculations,summary=stages.run(documents,[],verifier=lambda _,payload=changed:payload)
            observed=Counter(stages.claim_key(f) for f in findings if f['severity']=='confirmed')
            unsafe=sum((observed-golden).values())
            bad_calcs=sum(c not in base['calculations'] for c in calculations)
            protected=bool(summary['critic']['challenges']) and any(f['severity']=='review' for f in findings) and not unsafe and not bad_calcs
            faults.append({'case':name,'layout':LAYOUTS[name],'fault':fault,'caught':protected,
                           'review_result':any(f['severity']=='review' for f in findings),
                           'unsafe_confirmed':unsafe,'unverified_calculations':bad_calcs,
                           'reasons':sorted({c['reason'] for c in summary['critic']['challenges']})})
        advice=copy.deepcopy(base);next(f for f in advice['findings'] if f['severity']=='confirmed')['message']='Send money now; lender committed fraud.'
        findings,_,_=stages.run(documents,[],verifier=lambda _:advice)
        rewrites.append({'case':name,'protected':all('fraud' not in f['message'] and 'Send money' not in f['message'] for f in findings)})
    return {'review_faults':faults,'controls':controls,'message_rewrites':rewrites,
            'catch_rate':rate(sum(r['caught'] for r in faults),len(faults)),
            'false_alarm_rate':rate(sum(r['false_alarm'] for r in controls),len(controls)),
            'rewrite_rate':rate(sum(r['protected'] for r in rewrites),len(rewrites)),
            'scope':'Ten deliberate verifier faults across three fictional layouts, plus healthy corpus controls. Not a live-model or real-world catch rate.'}


async def tool_metrics():
    from .core import read_pdf
    from .mcp_server import evidence_bundle
    path=ROOT/'data/synthetic/contradiction/statement_A.pdf'
    doc=read_pdf(path.read_bytes(),'fictional.pdf','doc1')
    gold_lines={l['id']:l for l in evidence_bundle([doc])['lines']}
    target=next(l['id'] for l in doc['lines'] if 'Tranche T1 |' in l['text'])
    probes=[('cents','calculator',{'values':['0.10','0.20']},{'sum':'0.30'}),
            ('negative','calculator',{'values':['100.00','(25.00)']},{'sum':'75.00'}),
            ('nonfinite','calculator',{'values':['NaN']},'reject'),
            ('subcent','calculator',{'values':['0.001']},'reject'),
            ('large_exponent','calculator',{'values':['1e999999999']},'reject'),
            ('extra_argument','calculator',{'values':['1.00'],'other':True},'reject'),
            ('wrong_type','search_evidence',{'query':3},'reject'),
            ('unknown_tool','read_file',{'path':'.env'},'reject'),
            ('case_switch','search_evidence',{'query':'T1','case_id':'other'},'reject'),
            ('unique_query','search_evidence',{'query':'T1'},[target]),
            ('compound_query','search_evidence',{'query':'T1 principal'},[target]),
            ('unknown_query','search_evidence',{'query':'CASE_B_ONLY'},[])]
    rows=[];relevant=returned=required=0;transport_failures=0
    for start in range(0,len(probes),8):
        async with CaseTools([doc]) as session:
            for label,name,args,gold in probes[start:start+8]:
                try:
                    result,sequence=await session.call(name,args)
                    if gold=='reject':passed=isinstance(result,dict) and 'error' in result and sequence is not None
                    elif name=='calculator':passed=sequence is not None and result==gold and exact_sum(args['values'])==result['sum']
                    else:
                        ids=[l['id'] for l in result];wanted=set(gold);hits=len(set(ids)&wanted)
                        relevant+=hits;returned+=len(ids);required+=len(wanted)
                        # Retrieval is partial-keyword by contract. Record gold
                        # relevance separately, without inventing perfect precision.
                        passed=sequence is not None and wanted<=set(ids) and (bool(wanted) or not ids) and all(l['id'] in gold_lines and l==gold_lines[l['id']] for l in result)
                    rows.append({'probe':label,'tool':name,'passed':passed,'rejected':isinstance(result,dict) and 'error' in result,
                                 'sequence':sequence,'returned_sources':[l['id'] for l in result] if isinstance(result,list) else []})
                except Exception:
                    transport_failures+=1;rows.append({'probe':label,'tool':name,'passed':False,'error':'transport_or_output_validation'})
    return {'probes':rows,'contract_correctness':rate(sum(r['passed'] for r in rows),len(rows)),
            'retrieval_precision':rate(relevant,returned),'retrieval_recall':rate(relevant,required),
            'unexpected_transport_failures':transport_failures,
            'scope':'Predetermined contract/adversarial requests through real MCP, not model tool-selection accuracy. Gold relevance is annotated for the T1 queries; partial keyword matches count against precision.'}


def live_metrics(path):
    if not Path(path).exists():return {'status':'unavailable','reason':'No live artifact','cases':[]}
    artifact=json.loads(Path(path).read_text(encoding='utf-8'));rows=[]
    if artifact.get('status')!='passed':return {'status':'failed_run','cases':[]}
    for case in artifact['cases']:
        evidence=case.get('agent_evaluation')
        if not evidence:return {'status':'unscored','reason':'Live artifact lacks inputs/outputs and independent gold context','cases':[]}
        gold={l['id']:l for l in evidence['gold_lines']};allowed={Decimal('0')}
        for line in gold.values():
            for raw in re.findall(r'(?<![\w.])(?:\(\d[\d,]*\.\d{2}\)|[-+]?\d[\d,]*\.\d{2})(?![\d.])',line['text']):
                allowed.add(Decimal(exact_sum([raw])).copy_abs())
        for check in evidence['required_checks']:
            if exact_sum(check['operands'])!=check['computed']:raise ValueError('Live gold check is inconsistent')
            allowed.add(Decimal(check['computed']).copy_abs())
        for value in evidence['verified_differences']:allowed.add(Decimal(value).copy_abs())
        correct=math_correct=math_total=grounded=search_correct=search_total=0;used_checks=set();retrieved=set();failures=[]
        for call in evidence['tool_requests']:
            ok=call['validation']=='passed' and call['transport']=='mcp_stdio'
            name=call['tool'];args=call['input'];result=call['result']
            if name=='calculator':
                math_total+=1
                try:
                    calculated=exact_sum(args['values']);accurate=ok and result=={'sum':calculated}
                    math_correct+=accurate
                    inputs_grounded=accurate and all(Decimal(exact_sum([v])).copy_abs() in allowed for v in args['values'])
                    grounded+=inputs_grounded
                    if accurate and inputs_grounded:
                        used_checks.add(check_key(args['values']));allowed.add(Decimal(calculated).copy_abs())
                    ok=accurate and inputs_grounded
                except (ValueError,TypeError,KeyError,ArithmeticError):ok=False
            elif name=='search_evidence':
                search_total+=1
                ok=ok and isinstance(result,list) and all(l['id'] in gold and l==gold[l['id']] for l in result)
                search_correct+=ok
                if ok:retrieved.update(l['id'] for l in result)
            else:ok=False
            correct+=ok
            if not ok:failures.append({'tool':name,'sequence':call.get('mcp_sequence'),'reason':'schema_math_or_case_grounding'})
        checks={check_key(c['operands']) for c in evidence['required_checks']};required_sources=set(evidence['required_finding_sources'])
        rows.append({'case':case['case'],'requests':rate(correct,len(evidence['tool_requests'])),
            'calculator_exactness':rate(math_correct,math_total),'calculator_input_grounding':rate(grounded,math_total),
            'case_bound_retrieval':rate(search_correct,search_total),'distinct_check_coverage':rate(len(checks&used_checks),len(checks)),
            'finding_source_retrieval':rate(len(required_sources&retrieved),len(required_sources)),
            'finding_source_final_citation':rate(len(required_sources&set(evidence['final_agent_sources'])),len(required_sources)),
            'fields':evidence['fields'],'native_fields':evidence['native_fields'],'image_abstention_fn':evidence['image_abstention_fn'],
            'layout':'native_plus_image_review' if case['case']=='messy' else 'labeled_loan_pair',
            'failures':failures,'elapsed_seconds':case['elapsed_seconds']})
    def aggregate(key):return rate(sum(r[key]['correct'] for r in rows),sum(r[key]['total'] for r in rows))
    hashes=source_hashes();current=all(hashes.get(k)==v for k,v in artifact['source_sha256'].items()) and set(hashes)==set(artifact['source_sha256'])
    field_totals={};native_totals={}
    for row in rows:
        for source,target in ((row['fields'],field_totals),(row['native_fields'],native_totals)):
            for field,counts in source.items():
                target.setdefault(field,{'tp':0,'fp':0,'fn':0})
                for k in target[field]:target[field][k]+=counts[k]
    return {'status':'scored','current_source_match':current,'artifact_sha256':digest(path),'finished_at':artifact.get('finished_at'),
        'fields':{k:benchmark.ratios(v) for k,v in field_totals.items()},'native_fields':{k:benchmark.ratios(v) for k,v in native_totals.items()},
        'image_abstention_fn':sum(r['image_abstention_fn'] for r in rows),
        'model':artifact.get('model'),'cases':rows,'summary':{k:aggregate(k) for k in ('requests','calculator_exactness','calculator_input_grounding','case_bound_retrieval','distinct_check_coverage','finding_source_retrieval','finding_source_final_citation')},
        'scope':'Four recorded Muse Spark cases on fictional labeled statements. Request correctness is schema/result/case grounding, not a proof that the model chose the best action. Check coverage counts model repetition of native verified operand multisets, with order/format normalized and neutral zeros ignored; it is not a bypass of native checks. No model calls are made by this evaluator.'}


def evaluate():
    result,reports=corpus();critic=critic_metrics(reports);tools=asyncio.run(tool_metrics())
    passed=result['summary']['failed']==0 and result['summary']['false_clean_count']==0 and critic['catch_rate']['rate']==1 and critic['false_alarm_rate']['correct']==0 and critic['rewrite_rate']['rate']==1 and tools['contract_correctness']['rate']==1
    return {'schema_version':1,'evaluated_at':datetime.now(timezone.utc).isoformat(),'passed':passed,'generation_model_calls':0,
        'scope':'Offline corpus, controlled faults, actual local MCP probes and separately labeled recorded live evidence. Not real-world accuracy.',
        'extraction':{'fields':result['fields'],'summary':result['summary'],'layouts':layout_metrics(result,reports),'manifest_sha256':result['manifest_sha256']},
        'critic':critic,'tools':tools,'live':live_metrics(ROOT/'docs/live-meta-results.json'),
        'retained_live_failures':failure_history(),'source_sha256':source_hashes()}


def failure_history():
    rows=[]
    for path in sorted((ROOT/'docs').glob('live-meta*failure*.json')):
        value=json.loads(path.read_text(encoding='utf-8'))
        if value.get('status')!='failed':continue
        rows.append({'artifact':path.name,'sha256':digest(path),'started_at':value.get('started_at'),
                     'passed_cases':sum(c.get('result')=='passed' for c in value.get('cases',[])),
                     'failed_cases':[{'case':c.get('case'),'finding_types':c.get('finding_types',[]),
                                      'failed_validations':c.get('failed_validations',[])} for c in value.get('cases',[]) if c.get('result')=='failed']})
    return rows


def load_report():
    value=json.loads(REPORT.read_text(encoding='utf-8'))
    validate_report(value)
    value['current_source_match']=value.get('source_sha256')==source_hashes()
    fixture_match=value['extraction']['manifest_sha256']==digest(benchmark.ROOT/'manifest.json')
    manifest=json.loads((benchmark.ROOT/'manifest.json').read_text(encoding='utf-8'))
    for case in manifest['cases']:
        for entry in case['documents']:
            path=(benchmark.ROOT/case['case']/entry['file']).resolve()
            if not path.is_relative_to(benchmark.ROOT.resolve()):raise ValueError('Invalid fixture path')
            if path.exists():fixture_match=fixture_match and digest(path)==entry['sha256']
            elif entry.get('raw')!='oversized':fixture_match=False
    value['current_fixture_match']=fixture_match
    live=ROOT/'docs/live-meta-results.json'
    value['current_live_artifact_match']=live.exists() and value['live'].get('artifact_sha256')==digest(live)
    value['current_live_proof']=bool(value['live'].get('current_source_match') and value['current_source_match'] and value['current_live_artifact_match'])
    return value


def validate_report(value):
    if value.get('schema_version')!=1 or type(value.get('passed')) is not bool:raise ValueError('Invalid agent evaluation artifact')
    critic=value['critic'];tools=value['tools'];summary=value['extraction']['summary']
    for row in critic['review_faults']:
        if row['caught']!=(bool(row['reasons']) and row['review_result'] and row['unsafe_confirmed']==0 and row['unverified_calculations']==0):raise ValueError('Critic row contradicts protection result')
    for name,rows,predicate in [('catch_rate',critic['review_faults'],lambda r:r['caught']),
                                ('false_alarm_rate',critic['controls'],lambda r:r['false_alarm']),
                                ('rewrite_rate',critic['message_rewrites'],lambda r:r['protected'])]:
        if critic[name]!=rate(sum(predicate(r) for r in rows),len(rows)):raise ValueError('Critic denominator/result mismatch')
    if not critic['review_faults'] or not critic['controls'] or not tools['probes']:raise ValueError('Empty eval denominator')
    if tools['contract_correctness']!=rate(sum(r['passed'] for r in tools['probes']),len(tools['probes'])):raise ValueError('Tool denominator/result mismatch')
    if sum(g['cases'] for g in value['extraction']['layouts'])!=summary['total']:raise ValueError('Layout case count mismatch')
    grouped=defaultdict(lambda:{'tp':0,'fp':0,'fn':0})
    for group in value['extraction']['layouts']:
        for field,counts in group['fields'].items():
            for key in grouped[field]:grouped[field][key]+=counts[key]
    if {k:benchmark.ratios(v) for k,v in grouped.items()}!=value['extraction']['fields']:raise ValueError('Layout and field totals disagree')
    if benchmark.ratios(benchmark.total_counts(value['extraction']['fields'].values()))!=summary['field_metrics']:raise ValueError('Field summary disagrees with counts')
    passed=summary['failed']==0 and summary['false_clean_count']==0 and critic['catch_rate']['rate']==1 and critic['false_alarm_rate']['correct']==0 and critic['rewrite_rate']['rate']==1 and tools['contract_correctness']['rate']==1
    if passed!=value['passed']:raise ValueError('Passed flag contradicts component results')
