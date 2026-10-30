"""Known-answer PDF benchmark: field P/R, grounded references and false-clean gate."""
import hashlib
import io
import json
import re
import time
from datetime import datetime,timezone
from collections import Counter,defaultdict
from pathlib import Path
from fastapi import HTTPException,UploadFile
from .core import AMOUNT,money

ROOT=Path(__file__).resolve().parents[1]/'data'/'benchmark'
FIELDS=('loan_id','currency','period_end','stated_total','opening_balance','closing_balance')

def field_values(statement):
    values={field:statement[field] for field in FIELDS if statement.get(field) is not None}
    for collection,fields in (('tranches',('id','principal','interest')),('transactions',('id','date','amount'))):
        occurrence=Counter()
        for row in statement.get(collection,[]):
            prefix=f'{collection}:{row["id"]}#{occurrence[row["id"]]}';occurrence[row['id']]+=1
            for field in fields:
                if row.get(field) is not None:values[prefix+':'+field]=row[field]
    for index,carry in enumerate(statement.get('carried_balances',[])):
        for field in ('amount','after_transaction_count'):values[f'carried_balances:{index}:{field}']=carry[field]
    return values

def scores(expected,actual):
    counts=defaultdict(lambda:{'tp':0,'fp':0,'fn':0})
    for key in expected.keys()|actual.keys():
        row=counts[key.split(':')[-1]]
        if key in expected and key in actual and expected[key]==actual[key]:row['tp']+=1
        else:
            if key in actual:row['fp']+=1
            if key in expected:row['fn']+=1
    return dict(counts)

def ratios(counts):
    result=dict(counts);tp,fp,fn=(result.get(key,0) for key in ('tp','fp','fn'))
    result.update(precision=tp/(tp+fp) if tp+fp else None,recall=tp/(tp+fn) if tp+fn else None)
    return result

def total_counts(rows):
    return {key:sum(row.get(key,0) for row in rows) for key in ('tp','fp','fn')}

def amount_sources(doc):
    statement=doc['statement'];values=[]
    for field,source in (('stated_total','total_source'),('opening_balance','opening_source'),('closing_balance','closing_source')):
        if statement.get(field) is not None:values.append((field,statement[field],statement.get(source),False))
    for row in statement['tranches']:
        for field in ('principal','interest'):values.append((f'tranches:{row["id"]}:{field}',row[field],row.get(field+'_source') or row['source'],False))
    for row in statement.get('transactions',[]):
        values.append((f'transactions:{row["id"]}:amount',row['amount'],row['source'],'bank_debit_credit_v1' in doc.get('layouts',[])))
    for index,carry in enumerate(statement.get('carried_balances',[])):values.append((f'carried_balances:{index}:amount',carry['amount'],carry['source'],False))
    return values

def evaluate_case(case,root=ROOT,analyzer=None):
    if analyzer is None:
        from .main import analyze_files
        analyzer=analyze_files
    started=time.perf_counter();uploads=[];errors=[]
    for entry in case['documents']:
        if Path(entry['file']).name!=entry['file'] or not re.fullmatch(r'[a-z_]+',case['case']):raise ValueError('Invalid fixture path')
        path=Path(root)/case['case']/entry['file']
        # The deliberately oversized negative fixture is regenerated in memory
        # on a clean clone; it is excluded from Git to avoid a 10 MB padding blob.
        raw=path.read_bytes() if path.exists() else (b'%PDF-1.7\n'+b'0'*(10*1024*1024) if entry.get('raw')=='oversized' else b'')
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Fixture hash mismatch')
        uploads.append(UploadFile(filename=entry['file'],file=io.BytesIO(raw)))
    report=None;http_status=200
    try:report=analyzer(uploads,'local',persist=False)
    except HTTPException as exc:http_status=exc.status_code
    expected_http=case.get('expected_http',200)
    if http_status!=expected_http:errors.append('HTTP result differs from ground truth')
    result={'case':case['case'],'passed':False,'status':'rejected' if report is None else report['status'],'http_status':http_status,
        'at_risk':case.get('expected_status')!='consistent','false_clean':False,'errors':errors,'fields':{},
        'citation_count':0,'resolved_citations':0,'grounded_citations':0,'model_calls':0}
    if report is not None:
        if report['status']!=case.get('expected_status'):errors.append('Machine status differs from ground truth')
        confirmed=[finding for finding in report['findings'] if finding['severity']=='confirmed']
        observed=Counter((item['type'],item.get('difference'),item.get('computed')) for item in confirmed)
        expected=Counter((item['type'],item.get('difference'),item.get('computed')) for item in case.get('confirmed',[]))
        if observed!=expected:errors.append('Confirmed findings differ from ground truth')
        if not set(case.get('review_types',[]))<={finding['type'] for finding in report['findings'] if finding['severity']=='review'}:errors.append('Expected review finding missing')
        counters=defaultdict(lambda:{'tp':0,'fp':0,'fn':0});pages={}
        for expected_doc,doc in zip(case['documents'],report['documents']):
            gold_values=field_values(expected_doc['truth']);actual_values=field_values(doc['statement'])
            for field,row in scores(gold_values,actual_values).items():
                for key in row:counters[field][key]+=row[key]
            allowed=set(case.get('allowed_abstentions',{}).get(doc['id'],[])) if report['status']=='review' else set()
            bad=(gold_values.keys()-actual_values.keys())-allowed
            if bad or any(key not in gold_values or value!=gold_values[key] for key,value in actual_values.items()):
                errors.append('Extracted fields differ from ground truth outside expected review abstentions')
            index={line['id']:line for line in doc['lines']}
            for field,value,source,signed_columns in amount_sources(doc):
                result['citation_count']+=1;line=index.get(source)
                if line:
                    result['resolved_citations']+=1;pages[doc['id']+':'+field]=line['page']
                    tokens=[money(match[0]) for match in re.finditer(AMOUNT,line['text'])]
                    if money(value) in tokens or (signed_columns and abs(money(value)) in tokens):result['grounded_citations']+=1
        result['fields']={field:ratios(row) for field,row in sorted(counters.items())}
        if any(pages.get(key)!=page for key,page in case.get('source_pages',{}).items()):errors.append('Wrong page for a cross-page figure')
        if result['resolved_citations']!=result['citation_count'] or result['grounded_citations']!=result['citation_count']:errors.append('Amount citation does not resolve to grounded evidence')
        index={line['id'] for doc in report['documents'] for line in doc['lines']}
        if any(not finding['sources'] or any(source not in index for source in finding['sources']) for finding in confirmed):errors.append('Confirmed finding lacks source evidence')
        result['false_clean']=result['at_risk'] and report['status']=='consistent'
        if result['false_clean']:errors.append('Unsafe false clean')
        result['layouts']=sorted({layout for doc in report['documents'] for layout in doc.get('layouts',[])})
    result['field_summary']=ratios(total_counts(result['fields'].values()))
    result['passed']=not errors;result['elapsed_ms']=round((time.perf_counter()-started)*1000,2)
    return result

def evaluate_suite(root=ROOT,analyzer=None):
    manifest=json.loads((Path(root)/'manifest.json').read_text(encoding='utf-8'));rows=[]
    if manifest.get('schema_version')!=1 or not manifest.get('fictional') or not isinstance(manifest.get('cases'),list) or not manifest['cases']:
        raise ValueError('Invalid or empty benchmark manifest')
    if len({case['case'] for case in manifest['cases']})!=len(manifest['cases']):raise ValueError('Duplicate benchmark case')
    for case in manifest['cases']:
        try:rows.append(evaluate_case(case,root,analyzer))
        except Exception:rows.append({'case':case['case'],'passed':False,'status':'error','at_risk':case.get('expected_status')!='consistent',
            'false_clean':False,'errors':['Benchmark could not execute; inspect fixtures and regression tests.'],'fields':{},'citation_count':0,'resolved_citations':0,'grounded_citations':0})
    fields=defaultdict(lambda:{'tp':0,'fp':0,'fn':0})
    for row in rows:
        for field,counts in row['fields'].items():
            for key in ('tp','fp','fn'):fields[field][key]+=counts[key]
    refs=sum(row['citation_count'] for row in rows);risk=sum(row['at_risk'] for row in rows);false_clean=sum(row['false_clean'] for row in rows)
    accepted=[row for row in rows if row['status'] not in ('rejected','error')]
    return {'mode':'offline','model_calls':0,'evaluated_at':datetime.now(timezone.utc).isoformat(),
        'manifest_sha256':hashlib.sha256((Path(root)/'manifest.json').read_bytes()).hexdigest(),
        'cases':rows,'fields':{field:ratios(counts) for field,counts in sorted(fields.items())},
        'summary':{'total':len(rows),'passed':sum(row['passed'] for row in rows),'failed':sum(not row['passed'] for row in rows),
            'field_metrics':ratios(total_counts(fields.values())),'citation_count':refs,
            'citation_accuracy':sum(row['resolved_citations'] for row in rows)/refs if refs else None,
            'grounded_reference_accuracy':sum(row['grounded_citations'] for row in rows)/refs if refs else None,
            'at_risk_count':risk,'false_clean_count':false_clean,'false_clean_rate':false_clean/risk if risk else None,
            'review_rate':sum(row['status']=='review' for row in accepted)/len(accepted) if accepted else None},
        'definitions':{'fields':'Exact value micro precision/recall across known-answer identity, dates, totals, rows and carried balances. Wrong values count as both FP and FN. Expected review abstentions still count as FN, including visible fields in incomplete rows.',
            'citations':'Resolved amount-source references / all extracted amount-source references. Grounded references also contain the amount; debit/credit sign semantics are checked against independent truth.',
            'review_rate':'Review results / successfully analyzed PDF cases; rejected corrupt/oversized inputs are excluded.',
            'false_clean':'At-risk cases incorrectly marked consistent / at-risk cases, including expected rejections.',
            'scope':'Fictional, strict supported layouts and representative rejection cases. Not live-model, OCR or real-world accuracy.'}}
