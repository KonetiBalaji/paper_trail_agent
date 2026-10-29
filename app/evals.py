"""Offline six-case evaluation; never calls a model or reads credentials."""
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from .core import read_pdf,parse_statement,reconcile
from scripts.generate_bank_fixtures import generate,ROOT

CASES=('clean','contradiction','math_error','messy','bank_clean','bank_error')

def evaluate_case(case,paths):
    truth=json.loads((ROOT/case/'ground_truth.json').read_text(encoding='utf-8'))
    docs=[]
    if len(paths)!=(1 if case.startswith('bank_') else 2):raise ValueError('Missing fixture PDFs')
    for i,path in enumerate(paths,1):
        doc=read_pdf(path.read_bytes(),path.name,f'doc{i}')
        doc['statement']=parse_statement(doc);docs.append(doc)
    findings,calculations=reconcile(docs)
    confirmed=[f for f in findings if f['severity']=='confirmed']
    expected=truth['expected_confirmed_contradictions'];errors=[]
    def check(condition,message):
        if not condition:errors.append(message)
    check(len(confirmed)==expected,'Confirmed count differs from ground truth')
    index={line['id']:line for doc in docs for line in doc['lines']}
    refs=[source for f in confirmed for source in f['sources']]
    resolved=sum(source in index and bool(index[source]['text']) for source in refs)
    check(all(f['sources'] for f in confirmed),'Confirmed finding has no sources')
    check(resolved==len(refs),'Unresolved citation')
    if case in ('clean','bank_clean'):check(not findings,'Clean control has unexpected findings')
    if case in ('contradiction','math_error','bank_error'):
        kind,diff,computed={'contradiction':('cross_document_interest_mismatch','25.00',None),
            'math_error':('incorrect_statement_total','50.00','3300.00'),
            'bank_error':('incorrect_closing_balance','25.00','975.00')}[case]
        check(len(confirmed)==1 and confirmed[0]['type']==kind and confirmed[0].get('difference')==diff,'Wrong finding type or amount')
        if computed:check(bool(confirmed) and confirmed[0].get('computed')==computed,'Wrong calculated total')
        if case=='contradiction':check(bool(confirmed) and len(confirmed[0]['sources'])==2,'Expected both interest sources')
    if case=='messy':
        check({f['type'] for f in findings}=={'ocr_required','comparison_skipped'},'Expected OCR and blocked-comparison review')
        check(not docs[1]['lines'] and not docs[1]['statement']['tranches'],'Invented image-only extraction')
    if case.startswith('bank_'):
        statement=docs[0]['statement']
        for field,value in [('loan_id',truth['account_id']),('currency',truth['currency']),('period_end',truth['period_end']),
                            ('opening_balance',truth['opening_balance']),('closing_balance',truth['closing_balance'])]:
            check(statement[field]==value,f'Wrong bank field: {field}')
        check([{k:t[k] for k in ('id','date','amount')} for t in statement['transactions']]==truth['transactions'],'Wrong transactions')
        check(bool(calculations) and calculations[0]['computed']==truth['computed_closing_balance'],'Wrong bank balance')
    status='review' if any(f['severity']=='review' for f in findings) else ('discrepancies' if findings else 'consistent')
    at_risk=expected>0 or case=='messy';false_clean=at_risk and status=='consistent'
    check(not false_clean,'Unsafe false clean result')
    return {'case':case,'passed':not errors,'status':status,'confirmed_count':len(confirmed),'expected_confirmed_count':expected,
        'review_count':sum(f['severity']=='review' for f in findings),'citation_count':len(refs),'resolved_citations':resolved,
        'citation_accuracy':resolved/len(refs) if refs else None,'false_clean':false_clean,'at_risk':at_risk,
        'differences':[f['difference'] for f in confirmed if 'difference' in f],'errors':errors}

def evaluate_suite():
    rows=[]
    with tempfile.TemporaryDirectory(prefix='paper-trail-eval-') as temporary:
        banks=generate(Path(temporary))
        for case in CASES:
            try:rows.append(evaluate_case(case,[banks[case]] if case in banks else sorted((ROOT/case).glob('*.pdf'))))
            except Exception:
                rows.append({'case':case,'passed':False,'status':'error','confirmed_count':None,'expected_confirmed_count':None,
                    'review_count':None,'citation_count':0,'resolved_citations':0,'citation_accuracy':None,'false_clean':False,
                    'at_risk':case not in ('clean','bank_clean'),'differences':[],'errors':['Evaluation could not run; inspect fixtures and server tests.']})
    total=sum(r['citation_count'] for r in rows);resolved=sum(r['resolved_citations'] for r in rows)
    risk=sum(r['at_risk'] for r in rows);false_clean=sum(r['false_clean'] for r in rows)
    return {'evaluated_at':datetime.now(timezone.utc).isoformat(),'mode':'offline','model_calls':0,'cases':rows,
        'summary':{'total':len(rows),'passed':sum(r['passed'] for r in rows),'failed':sum(not r['passed'] for r in rows),
            'citation_accuracy':resolved/total if total else None,'citation_count':total,
            'false_clean_count':false_clean,'at_risk_count':risk,'false_clean_rate':false_clean/risk if risk else None},
        'definitions':{'citation_accuracy':'Resolved confirmed-source references / all confirmed-source references; null when none.',
            'false_clean_rate':'At-risk cases incorrectly marked consistent / four at-risk cases (three errors and one OCR case).',
            'scope':'Six labeled synthetic cases; local deterministic checks, not live-model or universal PDF accuracy.'}}
