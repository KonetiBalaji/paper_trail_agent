"""Schema-gated internal extraction, verification and independent cents critic.

The critic does not call reconcile(), calculate(), a model, or a remote agent.
It derives expected checks from grounded statement fields, then challenges the
verifier's amounts, citations, identity guards and completeness.
"""
import copy
from collections import defaultdict,deque
from decimal import Decimal
from itertools import combinations
import time
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,ValidationError
from . import core,meta
from .trace import record


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',revalidate_instances='always')


class ExtractedDocument(Strict):
    document:str
    selected:str
    validation:Literal['passed','review']
    reason:Literal['grounded_schema','document_issues','schema_or_grounding','incomplete_fields']
    source_count:int=Field(ge=0)


class ExtractionResult(Strict):
    stage:Literal['Extractor']='Extractor'
    documents:list[ExtractedDocument]


class Finding(Strict):
    id:str=Field(pattern=r'^F[1-9][0-9]{0,5}$')
    type:str
    message:str
    sources:list[str]
    severity:Literal['confirmed','review']
    document:str|None=None
    field:str|None=None
    tranche:str|None=None
    difference:str|None=None
    computed:str|None=None
    stated:str|None=None


class Calculation(Strict):
    document:str
    operands:list[str]=Field(min_length=1,max_length=1000)
    computed:str
    stated:str
    sources:list[str]
    kind:Literal['closing_balance','carried_balance']|None=None


class VerificationResult(Strict):
    stage:Literal['Verifier']='Verifier'
    validation:Literal['passed','review']='passed'
    findings:list[Finding]=Field(max_length=2000)
    calculations:list[Calculation]


class Challenge(Strict):
    finding_id:str|None=None
    reason:Literal['unsupported_candidate','missing_finding','unverified_calculation','missing_calculation','extraction_review','verifier_schema','critic_limit']


class CriticResult(Strict):
    stage:Literal['Critic']='Critic'
    checked_candidates:int=Field(ge=0)
    approved:list[str]
    challenges:list[Challenge]
    expected_calculations:int=Field(ge=0)
    verified_calculations:int=Field(ge=0)
    validation:Literal['passed','review']


class VerifierSummary(Strict):
    stage:Literal['Verifier']='Verifier'
    validation:Literal['passed','review']
    candidate_findings:int=Field(ge=0,le=2000)
    calculations:int=Field(ge=0)


class OrchestrationResult(Strict):
    kind:Literal['internal_stages']='internal_stages'
    extractor:ExtractionResult
    verifier:VerifierSummary
    critic:CriticResult


def cents(value):
    if not isinstance(value,str):raise ValueError('Monetary strings required')
    amount=Decimal(value)
    if not amount.is_finite() or amount*100!=(amount*100).to_integral_value():raise ValueError('Exact cents required')
    return int(amount*100)


def amount(value):return format(Decimal(value)/100,'.2f')
def unique(values):return list(dict.fromkeys(values))
def row_source(row,field):return row.get(field+'_source') or row['source']


def extract_documents(files,mode,events):
    from fastapi import HTTPException
    docs=[];blobs=[]
    for i,file in enumerate(files):
        raw=file.file.read(10*1024*1024+1)
        if len(raw)>10*1024*1024:raise HTTPException(413,'Maximum 10 MB per PDF')
        name=(file.filename or 'statement.pdf').replace('\\','/').split('/')[-1][:150]
        started=time.perf_counter()
        try:doc=core.read_pdf(raw,name,f'doc{i+1}')
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        record(events,'extraction','pdf_text',{'document':doc['id'],'bytes':len(raw)},
               {'line_count':len(doc['lines']),'issues':[x['type'] for x in doc['issues']]},
               'review' if doc['issues'] else 'passed',(time.perf_counter()-started)*1000,document=doc['id'])
        if sum(len(l['text']) for l in doc['lines'])>100000:raise HTTPException(413,'Document text exceeds 100,000 characters')
        started=time.perf_counter();local=core.parse_statement(doc) if mode in ('local','auto') else None
        complete=local and all(local.get(k) for k in ('loan_id','currency','period_end')) and (
            bool(local['tranches']) and local['stated_total'] is not None or bool(local.get('transactions')) and local.get('opening_balance') is not None and local.get('closing_balance') is not None)
        use_model=mode=='meta' or mode=='auto' and not complete
        selected='blocked' if doc['issues'] else ('meta' if use_model else 'local')
        doc['routing']={'requested':mode,'selected':selected,'reason':'document_requires_review' if doc['issues'] else ('needs_model_extraction' if use_model else ('recognized_complete_fields' if complete else 'local_checks_only'))}
        if mode=='auto':record(events,'routing','extraction_choice',{'document':doc['id'],'mode':mode},doc['routing'],document=doc['id'])
        if use_model and not doc['issues']:
            try:doc['statement']=meta.extract(doc,trace=events)
            except meta.MetaError as exc:
                doc['statement']=core.parse_statement({'lines':[]});doc['issues'].append({'type':'model_extraction_failed','message':str(exc)})
        else:
            doc['statement']=local if local is not None else core.parse_statement(doc)
            record(events,'extraction','local_fields',{'document':doc['id']},
                   {'tranches':len(doc['statement']['tranches']),'transactions':len(doc['statement']['transactions'])},
                   'review' if doc['issues'] else 'passed',(time.perf_counter()-started)*1000,document=doc['id'])
        docs.append(doc);blobs.append(raw)
    return docs,blobs


def extract_stage(documents):
    rows=[];ids=[d['id'] for d in documents];all_sources=[l['id'] for d in documents for l in d['lines']]
    for doc in documents:
        lines=doc['lines'];line_ids=[l['id'] for l in lines]
        reason='grounded_schema';valid=True
        if doc['issues'] or doc.get('ocr',{}).get('performed'):valid=False;reason='document_issues'
        else:
            try:
                if len(ids)!=len(set(ids)) or len(all_sources)!=len(set(all_sources)) or len(line_ids)!=len(set(line_ids)):raise ValueError('Duplicate evidence IDs')
                if any(l.get('method')=='ocr' for l in lines):raise ValueError('OCR evidence requires review')
                for collection in ('tranches','transactions'):
                    row_ids=[r['id'] for r in doc['statement'].get(collection,[])]
                    if len(row_ids)!=len(set(row_ids)):raise ValueError('Duplicate row identifiers')
                meta.validate_statement(doc['statement'],doc)
            except (ValueError,TypeError,KeyError):valid=False;reason='schema_or_grounding'
            s=doc['statement']
            complete=all(s.get(k) for k in ('loan_id','currency','period_end')) and (
                bool(s.get('tranches')) and s.get('stated_total') is not None or
                bool(s.get('transactions')) and s.get('opening_balance') is not None and s.get('closing_balance') is not None)
            if valid and not complete:valid=False;reason='incomplete_fields'
        rows.append(ExtractedDocument(document=doc['id'],selected=doc.get('routing',{}).get('selected','local'),
                    validation='passed' if valid else 'review',reason=reason,source_count=len(lines)))
    return ExtractionResult(documents=rows)


def verify_stage(documents):
    findings,calculations=core.reconcile(documents)
    return VerificationResult(findings=findings,calculations=calculations)


def expected_checks(documents,extraction):
    """Derive checker obligations with integer cents, independently of verifier."""
    valid={d.document for d in extraction.documents if d.validation=='passed'}
    expected=[];claims=[];eligible=[];review_required=any(d.validation=='review' for d in extraction.documents)
    def total(doc,values,stated,sources,kind=None):
        computed=sum(cents(v) for v in values);delta=cents(stated)-computed
        calc={'document':doc['id'],'operands':values,'computed':amount(computed),'stated':stated,'sources':sources}
        if kind:calc['kind']=kind
        expected.append(calc)
        if delta:
            t={'closing_balance':'incorrect_closing_balance','carried_balance':'incorrect_carried_balance',None:'incorrect_statement_total'}[kind]
            label={'closing_balance':'closing balance',None:'stated total'}.get(kind)
            message=(f"{doc['name']}: carried balance differs by {amount(abs(delta))} {doc['statement']['currency']} from verified preceding transactions."
                     if kind=='carried_balance' else f"{doc['name']}: {label} is {amount(abs(delta))} {doc['statement']['currency']} too {'high' if delta>0 else 'low'}.")
            claims.append({'type':t,'difference':amount(abs(delta)),'computed':amount(computed),'stated':stated,'sources':sources,'message':message})
    for doc in documents:
        if doc['id'] not in valid:continue
        s=doc['statement'];tranches=s['tranches'];tx=s.get('transactions',[])
        if len(tranches)>500 or len(tx)>999:continue
        if len({r['id'] for r in tranches})!=len(tranches) or len({r['id'] for r in tx})!=len(tx):continue
        eligible.append(doc)
        if tranches and s.get('stated_total') is not None:
            total(doc,[r[k] for r in tranches for k in ('principal','interest')],s['stated_total'],
                  unique([row_source(r,k) for r in tranches for k in ('principal','interest')]+[s['total_source']]))
        if tx and s.get('opening_balance') is not None and s.get('closing_balance') is not None:
            total(doc,[s['opening_balance']]+[r['amount'] for r in tx],s['closing_balance'],
                  [s['opening_source']]+[r['source'] for r in tx]+[s['closing_source']],'closing_balance')
            for carry in s.get('carried_balances',[]):
                count=carry['after_transaction_count']
                if type(count) is not int or not 0<=count<=len(tx):continue
                total(doc,[s['opening_balance']]+[r['amount'] for r in tx[:count]],carry['amount'],
                      unique([s['opening_source']]+[r['source'] for r in tx[:count]]+[carry['source']]),'carried_balance')
    for a,b in combinations(eligible,2):
        x,y=a['statement'],b['statement']
        if any(x[k]!=y[k] for k in ('loan_id','currency','period_end')):
            review_required=True;continue
        if {r['id'] for r in x['tranches']} != {r['id'] for r in y['tranches']}:review_required=True
        for field in ('opening_balance','closing_balance','principal','interest'):
            pairs=[]
            if field in ('principal','interest'):
                left={r['id']:r for r in x['tranches']};right={r['id']:r for r in y['tranches']}
                for key in sorted(left.keys() & right.keys()):
                    v,w=left[key],right[key];pairs.append((v[field],w[field],[row_source(v,field),row_source(w,field)],key))
            elif x.get(field) is not None and y.get(field) is not None:
                source=field.replace('balance','source');pairs.append((x[field],y[field],[x[source],y[source]],None))
            for v,w,sources,tranche in pairs:
                diff=abs(cents(v)-cents(w))
                if not diff:continue
                message=(f'{tranche} {field} differs by {amount(diff)} {x["currency"]}.' if tranche else
                         f'{field.replace("_"," ").capitalize()} differs by {amount(diff)} {x["currency"]}.')
                claim={'type':f'cross_document_{field}_mismatch','field':field,'difference':amount(diff),'sources':sources,'message':message}
                if tranche:claim['tranche']=tranche
                claims.append(claim)
    return expected,claims,review_required


def claim_key(finding):
    return tuple(finding.get(k) for k in ('type','difference','computed','stated','field','tranche','document'))+(tuple(finding['sources']),)


def critique_stage(documents,extraction,verification):
    expected,claims,review_required=expected_checks(documents,extraction)
    findings=[f.model_dump(exclude_none=True) for f in verification.findings]
    calculations=[c.model_dump(exclude_none=True) for c in verification.calculations]
    if len(claims)>2000:
        finding={'id':'F1','type':'critic_limit','severity':'review','sources':[],
                 'message':'More than 2,000 discrepancy candidates require manual review; no candidates were confirmed.'}
        result=CriticResult(checked_candidates=sum(f.severity=='confirmed' for f in verification.findings),approved=[],
            challenges=[Challenge(reason='critic_limit')],expected_calculations=len(expected),verified_calculations=0,validation='review')
        return [finding],[],result
    challenges=[];approved=[];accepted_calcs=[];remaining=copy.deepcopy(expected)
    if verification.validation=='review':challenges.append(Challenge(reason='verifier_schema'))
    for c in calculations:
        if c in remaining:accepted_calcs.append(c);remaining.remove(c)
        else:challenges.append(Challenge(reason='unverified_calculation'))
    for _ in remaining:challenges.append(Challenge(reason='missing_calculation'))
    matched=set();claim_index=defaultdict(deque)
    for i,claim in enumerate(claims):claim_index[claim_key(claim)].append(i)
    for finding in findings:
        if finding['severity']!='confirmed':continue
        candidates=claim_index[claim_key(finding)];match=candidates.popleft() if candidates else None
        if match is not None:
            # Publish the critic's independently derived explanation, not an
            # unchecked verifier message that could contain unsupported advice.
            finding['message']=claims[match]['message'];matched.add(match);approved.append(finding['id'])
            finding['critic']={'decision':'passed','stage':'Critic'}
        else:
            finding['severity']='review';finding['message']='Critic withheld an unsupported discrepancy candidate. Inspect original evidence before acting.'
            valid_sources={l['id'] for d in documents for l in d['lines'] if l.get('usable',True) and l.get('method')!='ocr'}
            finding['sources']=[s for s in finding['sources'] if s in valid_sources]
            for key in ('computed','stated','difference','field','tranche'):finding.pop(key,None)
            finding['critic']={'decision':'withheld','stage':'Critic','original_severity':'confirmed'}
            challenges.append(Challenge(finding_id=finding['id'],reason='unsupported_candidate'))
    for i,claim in enumerate(claims):
        if i not in matched:challenges.append(Challenge(reason='missing_finding'))
    if review_required and not any(f['severity']=='review' for f in findings):
        challenges.append(Challenge(reason='extraction_review'))
    if challenges:
        ids={f['id'] for f in findings};number=len(findings)+1
        while f'F{number}' in ids:number+=1
        findings.append({'id':f'F{number}','type':'critic_review','severity':'review',
                         'message':'Independent critic checks did not all pass. Review extraction, calculation coverage and evidence before acting.',
                         'sources':[],'critic':{'decision':'review','stage':'Critic'}})
    result=CriticResult(checked_candidates=sum(f.severity=='confirmed' for f in verification.findings),approved=approved,
        challenges=challenges,expected_calculations=len(expected),verified_calculations=len(accepted_calcs),validation='review' if challenges else 'passed')
    return findings,accepted_calcs,result


def run(documents,events):
    # Neither verifier mutation nor its returned objects can change the evidence
    # snapshot inspected by the critic or the report's original extraction.
    snapshot=copy.deepcopy(documents)
    started=time.perf_counter();extraction=extract_stage(snapshot)
    record(events,'orchestration','Extractor',output=extraction.model_dump(),validation='review' if any(d.validation=='review' for d in extraction.documents) else 'passed',duration_ms=(time.perf_counter()-started)*1000)
    started=time.perf_counter()
    try:
        verification=VerificationResult.model_validate(verify_stage(copy.deepcopy(snapshot)))
        ids=[f.id for f in verification.findings]
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate finding IDs')
    except (ValidationError,ValueError,TypeError,KeyError):
        verification=VerificationResult(validation='review',findings=[Finding(id='F1',type='verifier_schema_review',message='Verifier output failed schema validation; review required.',sources=[],severity='review')],calculations=[])
    verifier_summary=VerifierSummary(validation=verification.validation,candidate_findings=len(verification.findings),calculations=len(verification.calculations))
    record(events,'orchestration','Verifier',output=verifier_summary.model_dump(),validation=verification.validation,duration_ms=(time.perf_counter()-started)*1000)
    started=time.perf_counter();findings,calculations,critic=critique_stage(snapshot,extraction,verification)
    record(events,'orchestration','Critic',output=critic.model_dump(),validation=critic.validation,duration_ms=(time.perf_counter()-started)*1000,finding_ids=[f['id'] for f in findings])
    return findings,calculations,OrchestrationResult(extractor=extraction,verifier=verifier_summary,critic=critic).model_dump()
