"""PDF evidence extraction and deterministic reconciliation. No LLM math."""
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import combinations
import pdfplumber

def money(value):
    s = str(value).strip().replace(',', '').replace('$', '')
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    try:
        result = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError('Invalid monetary value') from exc
    if not result.is_finite() or abs(result) > Decimal('1000000000000000'):
        raise ValueError('Monetary value out of range')
    if result != result.quantize(Decimal('.01')):
        raise ValueError('Amounts require at most two decimal places')
    return result

def calculate(values):
    if not values or len(values) > 1000:
        raise ValueError('Supply 1 to 1000 monetary values')
    return format(sum((money(v) for v in values), Decimal('0')), '.2f')

def read_pdf(raw, name, doc_id):
    if not raw.startswith(b'%PDF-'):
        raise ValueError('File is not a PDF')
    lines, issues = [], []
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            if len(pdf.pages) > 50:
                raise ValueError('Maximum 50 pages per PDF')
            for page_num, page in enumerate(pdf.pages, 1):
                # Group words by baseline. Coordinates are native PDF top-origin points.
                words = page.extract_words()
                groups = []
                for word in sorted(words, key=lambda w: (round(w['top']/3), w['x0'])):
                    if groups and abs(groups[-1][0]['top'] - word['top']) <= 3:
                        groups[-1].append(word)
                    else:
                        groups.append([word])
                if not groups:
                    issues.append({'type':'ocr_required','page':page_num,
                                   'message':'Image-only or empty page: extraction requires review/OCR.'})
                for idx, group in enumerate(groups, 1):
                    group.sort(key=lambda w:w['x0'])
                    text = ' '.join(w['text'] for w in group)
                    lines.append({'id':f'{doc_id}:p{page_num}:l{idx}', 'page':page_num,
                        'line':idx, 'text':text,
                        'bbox':[min(w['x0'] for w in group),min(w['top'] for w in group),
                                max(w['x1'] for w in group),max(w['bottom'] for w in group)],
                        'page_width':page.width,'page_height':page.height})
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('PDF could not be read; encrypted or damaged file') from exc
    return {'id':doc_id,'name':name,'lines':lines,'issues':issues}

AMOUNT = r'([-+]?\$?[\d,]+\.\d{2}|\([\d,]+\.\d{2}\))'

def parse_statement(doc):
    """Conservative baseline for labeled statements; unknown layouts require Meta extraction."""
    result = {'loan_id':None,'currency':None,'period_end':None,'tranches':[],
              'stated_total':None,'total_source':None,'opening_balance':None,
              'opening_source':None,'closing_balance':None,'closing_source':None,'transactions':[]}
    for line in doc['lines']:
        text, source = re.sub(r'^L\d+\s+','',line['text']), line['id']
        m = re.search(r'^(?:Document:\s*[\w-]+\s*\|\s*)?(?:Loan|Account):\s*([\w-]+)', text, re.I)
        if m: result['loan_id'] = m[1]
        m = re.search(r'^(?:(?:Document:\s*[\w-]+\s*\|\s*)?(?:Loan|Account):\s*[\w-]+\s*(?:\|\s*)?)?Currency:\s*([A-Z]{3})', text)
        if m: result['currency'] = m[1]
        m = re.search(r'^(?:Statement\s+)?(?:period end|as of):\s*(\d{4}-\d{2}-\d{2})', text, re.I)
        if m:
            try: result['period_end'] = date.fromisoformat(m[1]).isoformat()
            except ValueError: pass
        m = re.search(r'^Tranche\s+([\w-]+)\s*\|\s*Principal:\s*'+AMOUNT+r'\s*\|\s*Interest:\s*'+AMOUNT, text, re.I)
        if m:
            result['tranches'].append({'id':m[1], 'principal':format(money(m[2]),'.2f'),
                'interest':format(money(m[3]),'.2f'),'source':source})
        elif re.search(r'^Tranche\s+[\w-]+\s*\|',text,re.I):
            doc.setdefault('issues',[]).append({'type':'partial_extraction','message':'A tranche row could not be fully extracted; review required.'})
        m = re.search(r'^Stated principal plus interest total:\s*'+AMOUNT,text,re.I)
        if m: result.update(stated_total=format(money(m[1]),'.2f'),total_source=source)
        for field in ('opening','closing'):
            m = re.search('^'+field+r' balance:\s*'+AMOUNT,text,re.I)
            if m:
                result[field+'_balance']=format(money(m[1]),'.2f')
                result[field+'_source']=source
        m = re.search(r'^Transaction\s+([\w-]+)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*Amount:\s*'+AMOUNT,text,re.I)
        if m:
            try: transaction_date=date.fromisoformat(m[2]).isoformat()
            except ValueError:
                doc.setdefault('issues',[]).append({'type':'partial_extraction','message':'Transaction date is invalid; review required.'})
                continue
            result['transactions'].append({'id':m[1],'date':transaction_date,
                'amount':format(money(m[3]),'.2f'),'source':source})
        elif re.search(r'^Transaction\s+[\w-]+\s*\|',text,re.I):
            doc.setdefault('issues',[]).append({'type':'partial_extraction','message':'A transaction row could not be fully extracted; review required.'})
    from .layouts import augment
    return augment(doc,result)

def reconcile(documents):
    findings, calculations,blocked = [], [],set()
    def tranche_source(row,field):return row.get(field+'_source') or row['source']
    def add(kind, message, sources, severity='confirmed', **extra):
        findings.append({'id':f'F{len(findings)+1}','type':kind,'message':message,
                         'sources':sources,'severity':severity,**extra})
    for doc in documents:
        s = doc['statement']
        for issue in doc['issues']:
            candidates=issue.get('sources') or ([issue['source']] if issue.get('source') else [])
            sources=[source for source in candidates if any(line['id']==source for line in doc['lines'])]
            add(issue['type'],f"{doc['name']}: {issue['message']}",sources, 'review',document=doc['id'])
        identity = all([s['loan_id'],s['currency'],s['period_end']])
        if len(s['tranches'])>500 or len(s.get('transactions',[]))>999:
            add('calculation_limit',f"{doc['name']}: supported calculation limit is 500 tranches or 999 transactions; review required.",[], 'review',document=doc['id'])
            blocked.add(doc['id'])
        complete = identity and bool(s['tranches']) and s['stated_total'] is not None
        bank_complete = identity and s.get('opening_balance') is not None and s.get('closing_balance') is not None and bool(s.get('transactions'))
        if not (complete or bank_complete) and not doc['issues']:
            add('incomplete_extraction',f"{doc['name']}: required fields could not be verified.",[], 'review',document=doc['id'])
        ids = [t['id'] for t in s['tranches']]
        duplicate = len(ids) != len(set(ids))
        if duplicate:
            add('duplicate_tranche',f"{doc['name']}: repeated tranche identifiers require review.",[t['source'] for t in s['tranches']],'review')
        if complete and not doc['issues'] and not duplicate and doc['id'] not in blocked:
            values = [t[k] for t in s['tranches'] for k in ('principal','interest')]
            total = calculate(values)
            sources=list(dict.fromkeys([tranche_source(t,field) for t in s['tranches'] for field in ('principal','interest')]+[s['total_source']]))
            calculations.append({'document':doc['id'],'operands':values,'computed':total,'stated':s['stated_total'],
                                 'sources':sources})
            if money(total) != money(s['stated_total']):
                delta = money(s['stated_total'])-money(total)
                add('incorrect_statement_total',f"{doc['name']}: stated total is {abs(delta):.2f} {s['currency']} too {'high' if delta>0 else 'low'}.",
                    calculations[-1]['sources'],difference=format(abs(delta),'.2f'),computed=total,stated=s['stated_total'])
        if bank_complete and not doc['issues'] and doc['id'] not in blocked:
            tx=s['transactions'];tx_ids=[t['id'] for t in tx]
            if len(tx_ids)!=len(set(tx_ids)):
                add('duplicate_transaction',f"{doc['name']}: duplicate transaction IDs require review.",[t['source'] for t in tx],'review')
            else:
                values=[s['opening_balance']]+[t['amount'] for t in tx]
                computed=calculate(values)
                sources=[s['opening_source']]+[t['source'] for t in tx]+[s['closing_source']]
                calculations.append({'document':doc['id'],'operands':values,'computed':computed,
                                     'stated':s['closing_balance'],'sources':sources,'kind':'closing_balance'})
                delta=money(s['closing_balance'])-money(computed)
                if delta:
                    add('incorrect_closing_balance',f"{doc['name']}: closing balance is {abs(delta):.2f} {s['currency']} too {'high' if delta>0 else 'low'}.",sources,
                        difference=format(abs(delta),'.2f'),computed=computed,stated=s['closing_balance'])
                for carry in s.get('carried_balances',[]):
                    count=carry['after_transaction_count']
                    if not isinstance(count,int) or not 0<=count<=len(tx):
                        add('partial_extraction',f"{doc['name']}: carried balance position could not be verified.",[], 'review');continue
                    operands=[s['opening_balance']]+[t['amount'] for t in tx[:count]]
                    computed=calculate(operands)
                    sources=list(dict.fromkeys([s['opening_source']]+[t['source'] for t in tx[:count]]+[carry['source']]))
                    calculations.append({'document':doc['id'],'kind':'carried_balance','operands':operands,'computed':computed,'stated':carry['amount'],'sources':sources})
                    delta=money(carry['amount'])-money(computed)
                    if delta:add('incorrect_carried_balance',f"{doc['name']}: carried balance differs by {abs(delta):.2f} {s['currency']} from verified preceding transactions.",sources,
                        difference=format(abs(delta),'.2f'),computed=computed,stated=carry['amount'])
    for a,b in combinations(documents,2):
        x,y = a['statement'],b['statement']
        if a['issues'] or b['issues'] or a['id'] in blocked or b['id'] in blocked:
            add('comparison_skipped',f"{a['name']} and {b['name']}: comparison blocked because a document requires review.",[], 'review')
            continue
        if not all([x['loan_id'],y['loan_id'],x['period_end'],y['period_end'],x['currency'],y['currency']]):
            add('identity_incomplete',f"{a['name']} and {b['name']}: account, currency or reporting-period identity could not be verified.",[], 'review')
            continue
        if x['loan_id'] != y['loan_id'] or x['currency'] != y['currency']:
            add('identity_mismatch',f"{a['name']} and {b['name']}: different account identifiers or currencies; comparison requires review.",[], 'review')
            continue
        if x['period_end'] != y['period_end']:
            add('period_mismatch',f"{a['name']} and {b['name']}: different reporting periods; do not compare balances as contradictions.",[], 'review')
            continue
        for field in ('opening_balance','closing_balance'):
            if x.get(field) is not None and y.get(field) is not None and money(x[field])!=money(y[field]):
                diff=format(abs(money(x[field])-money(y[field])),'.2f')
                source_field=field.replace('balance','source')
                add(f'cross_document_{field}_mismatch',f'{field.replace("_"," ").capitalize()} differs by {diff} {x["currency"]}.',
                    [x[source_field],y[source_field]],difference=diff,field=field)
        left,right = {t['id']:t for t in x['tranches']},{t['id']:t for t in y['tranches']}
        if len(left)!=len(x['tranches']) or len(right)!=len(y['tranches']): continue
        for tranche in sorted(left.keys() ^ right.keys()):
            t = left.get(tranche) or right[tranche]
            add('missing_tranche',f'Tranche {tranche} appears in only one statement; review completeness.',[t['source']],'review')
        for tranche in sorted(left.keys() & right.keys()):
            for field in ('principal','interest'):
                v,w = left[tranche],right[tranche]
                if money(v[field]) != money(w[field]):
                    diff = format(abs(money(v[field])-money(w[field])),'.2f')
                    add(f'cross_document_{field}_mismatch',f'{tranche} {field} differs by {diff} {x["currency"]}.',
                        [tranche_source(v,field),tranche_source(w,field)],field=field,tranche=tranche,difference=diff)
    return findings, calculations

def retrieve(documents, query, limit=8):
    terms = set(re.findall(r'\w+',query.lower()))
    ranked = [(len(terms & set(re.findall(r'\w+',line['text'].lower()))),line)
              for d in documents for line in d['lines']]
    return [line for score,line in sorted(ranked,key=lambda pair:pair[0],reverse=True)[:limit] if score]
