"""Explicit native-text period rules; never infer payment allocation or FX.

These checks are separate from same-period contradiction findings. A check's
pass applies only to its named equation, never to an entire account history.
"""
import re
import hashlib
from pathlib import Path
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations
from .core import money, calculate


YEAR_FIRST_DATE = r'\d{4}(?:-\d{2}-\d{2}|/\d{2}/\d{2})'


class ReviewRequired(ValueError):
    pass


def _one(lines, label, pattern):
    matches=[]
    for line in lines:
        text=re.sub(r'^L\d+\s+','',line['text']).strip()
        if re.match(re.escape(label)+r'\s*:',text,re.I):
            match=re.fullmatch(re.escape(label)+r':\s*('+pattern+r')',text,re.I)
            if not match:raise ReviewRequired('invalid_'+label.lower().replace(' ','_'))
            matches.append((match[1],line['id']))
    if len(matches)!=1:raise ReviewRequired('missing_or_repeated_'+label.lower().replace(' ','_'))
    return matches[0]


def _amount(lines,label,negative=False):
    value,source=_one(lines,label,r'[-+]?\d{1,16}\.\d{2}')
    try:result=money(value)
    except ValueError as exc:raise ReviewRequired('invalid_amount') from exc
    if not negative and result<0:raise ReviewRequired('negative_'+label.lower().replace(' ','_'))
    return format(result,'.2f'),source


def _snapshot(doc):
    if doc.get('issues') or doc.get('duplicate_of') or doc.get('ocr',{}).get('performed'):
        raise ReviewRequired('document_requires_review')
    lines=doc.get('lines',[])
    if not lines or any(l.get('method')=='ocr' or not l.get('usable',True) for l in lines):
        raise ReviewRequired('native_evidence_required')
    ids=[l['id'] for l in lines]
    if len(ids)!=len(set(ids)):raise ReviewRequired('duplicate_evidence_ids')
    rule,rule_source=_one(lines,'Historical rules',r'PTA-(?:BANK-PERIOD|LOAN-PRINCIPAL)-V1')
    rule=rule.upper()
    identity,identity_source=_one(lines,'Account',r'[A-Za-z0-9_-]{1,80}')
    currency,currency_source=_one(lines,'Currency',r'[A-Z]{3}')
    currency=currency.upper()
    # The application's exact two-decimal arithmetic does not represent JPY,
    # KWD or arbitrary currencies with a different minor-unit convention.
    if currency not in ('USD','EUR','GBP','INR'):raise ReviewRequired('unsupported_currency')
    start,start_source=_one(lines,'Period start',YEAR_FIRST_DATE)
    end,end_source=_one(lines,'Period end',YEAR_FIRST_DATE)
    try:start=date.fromisoformat(start.replace("/", "-"));end=date.fromisoformat(end.replace("/", "-"))
    except ValueError as exc:raise ReviewRequired('invalid_period') from exc
    if start>end:raise ReviewRequired('reversed_period')
    sources=[rule_source,identity_source,currency_source,start_source,end_source]
    if rule=='PTA-LOAN-PRINCIPAL-V1':
        fields=[_amount(lines,label,negative=label=='Principal adjustments') for label in
            ('Historical principal opening','Principal disbursed','Principal repaid',
             'Principal adjustments','Historical principal closing')]
        opening,disbursed,repaid,adjustments,closing=[f[0] for f in fields]
        opening_source, closing_source = fields[0][1], fields[-1][1]
        operands=[opening,disbursed,format(-money(repaid),'.2f'),adjustments]
        sources.extend(f[1] for f in fields)
    else:
        opening,opening_source=_amount(lines,'Opening balance',negative=True)
        closing,closing_source=_amount(lines,'Closing balance',negative=True)
        count,_=_one(lines,'Transaction count',r'\d{1,3}')
        entries=[]
        for line in lines:
            text=re.sub(r'^L\d+\s+','',line['text']).strip()
            if not re.match(r'^Transaction\s+',text,re.I) or re.match(r'^Transaction count:',text,re.I):continue
            m=re.fullmatch(rf'Transaction\s+([A-Za-z0-9_-]{{1,80}})\s*\|\s*({YEAR_FIRST_DATE})\s*\|\s*Amount:\s*([-+]?\d{{1,16}}\.\d{{2}})',text,re.I)
            if not m:raise ReviewRequired('unparsed_transaction')
            try:posted=date.fromisoformat(m[2].replace("/", "-"));value=money(m[3])
            except ValueError as exc:raise ReviewRequired('invalid_transaction') from exc
            if not start<=posted<=end:raise ReviewRequired('transaction_outside_period')
            entries.append((m[1],format(value,'.2f'),line['id']))
        if len(entries)!=int(count) or len({r[0] for r in entries})!=len(entries):
            raise ReviewRequired('transaction_count_or_identity')
        operands=[opening]+[r[1] for r in entries]
        sources.extend([opening_source]+[r[2] for r in entries]+[closing_source])
    try:
        computed=calculate(operands)
        money(computed)
    except ValueError as exc:raise ReviewRequired('calculation_out_of_range') from exc
    # Independent integer-cents replay challenges the Decimal result.
    cents=sum(int(Decimal(value)*100) for value in operands)
    if cents!=int(Decimal(computed)*100):raise ReviewRequired('calculator_replay_failed')
    return {'document':doc['id'],'account':identity,'currency':currency,'rule':rule,
        'start':start,'end':end,'opening':opening,'closing':closing,
        'opening_source':opening_source,'closing_source':closing_source,
        'operands':operands,'computed':computed,'sources':list(dict.fromkeys(sources))}


def evaluate_history(documents):
    """Evaluate every input pair with evidence and explicit inclusive periods.

    A matching account/currency and adjacent periods permit carry comparison.
    Identical periods permit matching balance comparisons. Gaps, partial
    overlap, changed rule or incomplete evidence require
    review. End balances changing across periods are never contradictions alone.
    """
    snapshots={};reviews=[];checks=[];pairs=[]
    if len(documents)>8:raise ValueError('Historical comparison accepts at most eight documents')
    ids=[d['id'] for d in documents]
    if len(ids)!=len(set(ids)):raise ValueError('Unique document IDs required')
    for doc in documents:
        try:snapshots[doc['id']]=_snapshot(doc)
        except ReviewRequired as exc:reviews.append({'document':doc['id'],'reason':str(exc)})
    for item in snapshots.values():
        delta=money(item['closing'])-money(item['computed'])
        checks.append({'type':'period_movements','documents':[item['document']],
            'result':'discrepancy' if delta else 'passed','currency':item['currency'],
            'operands':item['operands'],'computed':item['computed'],'stated':item['closing'],
            'difference':format(abs(delta),'.2f'),'sources':item['sources']})
    for left,right in combinations(documents,2):
        pair={'documents':[left['id'],right['id']],'result':'review'}
        x=snapshots.get(left['id']);y=snapshots.get(right['id'])
        if not x or not y:pair['reason']='incomplete_native_history'
        elif left.get('sha256') and left.get('sha256')==right.get('sha256'):
            pair['reason']='duplicate_document'
        elif (x['account'],x['currency'],x['rule'])!=(y['account'],y['currency'],y['rule']):
            pair['reason']='account_currency_or_rule_mismatch'
        else:
            x,y=sorted([x,y],key=lambda v:v['start'])
            if (x['start'],x['end'])==(y['start'],y['end']):
                differences = []
                for field in ('opening', 'closing'):
                    delta = money(y[field]) - money(x[field])
                    if delta:
                        differences.append(dict(
                            balance_field=field, computed=x[field], stated=y[field],
                            difference=format(abs(delta), '.2f'),
                            balance_sources=[x[field+'_source'], y[field+'_source']],
                        ))
                pair.update(result='discrepancy' if differences else 'passed',
                    reason='same_period_balances', currency=x['currency'],
                    sources=list(dict.fromkeys(x['sources']+y['sources'])),
                    balance_differences=differences)
                if differences:
                    pair.update(differences[0])
            elif x['end']>=y['start']:pair['reason']='overlapping_or_same_period'
            elif x['end']==date.max or x['end']+timedelta(days=1)!=y['start']:
                pair['reason']='period_gap'
            else:
                delta=money(y['opening'])-money(x['closing'])
                pair.update(result='discrepancy' if delta else 'passed',reason='adjacent_period_carry',
                    carry_sources=[x['closing_source'], y['opening_source']],
                    documents=[x['document'],y['document']],currency=x['currency'],
                    computed=x['closing'],stated=y['opening'],difference=format(abs(delta),'.2f'),
                    sources=list(dict.fromkeys(x['sources']+y['sources'])))
        pairs.append(pair)
    return {'rules_version':'native-period-v1','checks':checks,'pairs':pairs,'review':reviews,
        'scope':'Explicit native-text bank signed movements or allocated loan principal only; inclusive adjacent dates; no inferred FX, amortization, interest allocation or whole-history clean verdict.'}


def prior_case_history(repo, workspace, case_id, document_id, *, limit=20, offset=0):
    """Evaluate a page of prior statements against a single immutable source."""
    from copy import deepcopy
    from .repository import Missing

    current = repo.get_case(workspace, case_id, version=1)
    document = next((doc for doc in current['documents'] if doc['id'] == document_id), None)
    if document is None:
        raise Missing('Document not found')
    page = repo.prior_statement_sources(workspace, case_id, document_id, limit=limit, offset=offset)
    comparisons = []
    for reference in page['sources']:
        previous = repo.get_case(workspace, reference['case_id'], version=1)
        prior_document = next(doc for doc in previous['documents'] if doc['id'] == reference['document_id'])
        prior_document = deepcopy(prior_document)
        prior_document['id'] = f"{reference['case_id']}/{reference['document_id']}"
        for line in prior_document['lines']:
            line['id'] = f"{reference['case_id']}/{line['id']}"
        evaluation = evaluate_history([prior_document, document])
        comparisons.append({'prior': reference, 'pair': evaluation['pairs'][0],
                            'checks': evaluation['checks'], 'review': evaluation['review']})
    return {'case_id': case_id, 'document_id': document_id, 'report_version': 1,
            'identity_verified': page['identity_verified'], 'next_offset': page['next_offset'],
            'comparisons': comparisons}


def case_history(report):
    result=evaluate_history(report['documents'])
    result.update(case_id=report['id'],report_version=report.get('report_version',0),
        policy_sha256=hashlib.sha256(Path(__file__).read_text(encoding='utf-8').encode()).hexdigest())
    return result
