from pathlib import Path
import json
import os
import re
import uuid
import io
import time
import threading
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from .core import read_pdf, parse_statement, reconcile, retrieve
from . import meta
from .trace import record
from .evals import evaluate_suite
from .privacy import report_for_export,private_report_view,install_log_redaction,markdown_text
from .platform import HistoryQuery
from .telemetry import usage

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
install_log_redaction()
STORE = Path(os.getenv('PAPER_TRAIL_STORAGE', str(ROOT/'storage')))
CASE_LOCK=threading.RLock()
app = FastAPI(title='Paper Trail Agent')
app.mount('/static',StaticFiles(directory=ROOT/'app'/'static'),name='static')

@app.get('/')
def home(): return FileResponse(ROOT/'app'/'static'/'index.html')

@app.get('/api/health')
def health(): return {'status':'ok','meta_configured':meta.configured(),'model':os.getenv('META_MODEL','muse-spark-1.3')}

@app.get('/api/evals')
def evals():return evaluate_suite()

@app.get('/api/benchmark')
def benchmark():
    from .benchmark import evaluate_suite as extended_suite
    try:return extended_suite()
    except (OSError,ValueError):raise HTTPException(503,'Benchmark fixtures or manifest unavailable.') from None

def save_report(path,report):
    temporary=path/('report-'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(report),encoding='utf-8')
        os.replace(temporary,path/'report.json')
    finally:
        if temporary.exists():temporary.unlink()

class ReviewUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    action: Literal['confirm','reject','note']
    note: str = Field(default='',max_length=2000)
    expected_revision: int = Field(ge=0,strict=True)

    @model_validator(mode='after')
    def note_required(self):
        if self.action=='note' and not self.note:raise ValueError('A note cannot be empty')
        return self

def case_path(case_id):
    if not re.fullmatch(r'[a-f0-9]{32}',case_id): raise HTTPException(404,'Case not found')
    path=STORE/case_id
    if not (path/'report.json').is_file(): raise HTTPException(404,'Case not found')
    return path

def load(case_id): return private_report_view(json.loads((case_path(case_id)/'report.json').read_text()))

@app.get('/api/cases/{case_id}/findings/{finding_id}/draft')
def lender_draft(case_id, finding_id, version:int, revision:int, kind:Literal['lender_enquiry','statement_dispute']='lender_enquiry'):
    from .drafts import build_draft, DraftUnavailable
    with CASE_LOCK:
        try:return build_draft(load(case_id),finding_id,version,revision,kind)
        except DraftUnavailable as exc:raise HTTPException(409,str(exc)) from None

@app.patch('/api/cases/{case_id}/findings/{finding_id}')
def review_finding(case_id,finding_id,update:ReviewUpdate):
    with CASE_LOCK:
        path=case_path(case_id);report=load(case_id)
        finding=next((f for f in report['findings'] if f['id']==finding_id),None)
        if finding is None:raise HTTPException(404,'Finding not found')
        review=finding.setdefault('human_review',{'decision':'pending','revision':0,'history':[]})
        if update.expected_revision!=review['revision']:raise HTTPException(409,'Review changed. Reopen the case before saving again.')
        event={'action':update.action,'note':update.note,'timestamp':datetime.now(timezone.utc).isoformat(),
               'revision':review['revision']+1}
        if update.action in ('confirm','reject'):review['decision']={'confirm':'confirmed','reject':'rejected'}[update.action]
        review['revision']+=1;review['history'].append(event)
        record(report.setdefault('trace',[]),'human_review',update.action,
               {'finding_id':finding_id,'note':update.note,'expected_revision':update.expected_revision},
               {'decision':review['decision'],'revision':review['revision']},finding_ids=[finding_id])
        save_report(path,report)
        return report

@app.post('/api/analyze')
def analyze(files: list[UploadFile] = File(...), mode: str = Form('local')):
    return analyze_files(files,mode)

def analyze_files(files,mode='local',persist=True):
    analysis_started=time.perf_counter()
    if mode not in ('local','meta','auto'): raise HTTPException(422,'Choose local, meta or auto mode')
    if not 1<=len(files)<=8: raise HTTPException(422,'Upload 1 to 8 PDFs')
    if mode in ('meta','auto') and not meta.configured(): raise HTTPException(503,'Set MODEL_API_KEY in .env and restart before using Meta or auto mode.')
    docs, blobs,events = [], [],[]
    for i,file in enumerate(files):
        raw=file.file.read(10*1024*1024+1)
        if len(raw)>10*1024*1024: raise HTTPException(413,'Maximum 10 MB per PDF')
        name=(file.filename or 'statement.pdf').replace('\\','/').split('/')[-1][:150]
        started=time.perf_counter()
        try: doc=read_pdf(raw,name,f'doc{i+1}')
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
        record(events,'extraction','pdf_text',{'document':doc['id'],'bytes':len(raw)},
               {'line_count':len(doc['lines']),'issues':[x['type'] for x in doc['issues']]},
               'review' if doc['issues'] else 'passed',(time.perf_counter()-started)*1000,document=doc['id'])
        if sum(len(l['text']) for l in doc['lines'])>100000: raise HTTPException(413,'Document text exceeds 100,000 characters')
        started=time.perf_counter();local=parse_statement(doc) if mode in ('local','auto') else None
        complete=local and all(local.get(field) for field in ('loan_id','currency','period_end')) and (
            bool(local['tranches']) and local['stated_total'] is not None or bool(local.get('transactions')) and local.get('opening_balance') is not None and local.get('closing_balance') is not None)
        use_model=mode=='meta' or mode=='auto' and not complete
        selected='blocked' if doc['issues'] else ('meta' if use_model else 'local')
        doc['routing']={'requested':mode,'selected':selected,'reason':'document_requires_review' if doc['issues'] else ('needs_model_extraction' if use_model else ('recognized_complete_fields' if complete else 'local_checks_only'))}
        if mode=='auto':record(events,'routing','extraction_choice',{'document':doc['id'],'mode':mode},doc['routing'],document=doc['id'])
        if use_model and not doc['issues']:
            try: doc['statement']=meta.extract(doc,trace=events)
            except meta.MetaError as exc:
                doc['statement']=parse_statement({'lines':[]})
                doc['issues'].append({'type':'model_extraction_failed','message':str(exc)})
        else:
            doc['statement']=local if local is not None else parse_statement(doc)
            record(events,'extraction','local_fields',{'document':doc['id']},
                   {'tranches':len(doc['statement']['tranches']),'transactions':len(doc['statement']['transactions'])},
                   'review' if doc['issues'] else 'passed',(time.perf_counter()-started)*1000,document=doc['id'])
        docs.append(doc); blobs.append(raw)
    started=time.perf_counter()
    findings, calculations = reconcile(docs)
    reconcile_duration=(time.perf_counter()-started)*1000
    for finding in findings:finding['human_review']={'decision':'pending','revision':0,'history':[]}
    for calculation in calculations:
        ids=[f['id'] for f in findings if set(f['sources']) & set(calculation['sources'])]
        record(events,'calculator','deterministic_total',{'operands':calculation['operands']},
               {'computed':calculation['computed'],'stated':calculation['stated']},document=calculation['document'],finding_ids=ids)
    record(events,'validation','reconciliation',{'documents':len(docs)},
           {'findings':len(findings),'types':[f['type'] for f in findings]},
           'review' if any(f['severity']=='review' for f in findings) else 'passed',reconcile_duration,finding_ids=[f['id'] for f in findings])
    report={'id':uuid.uuid4().hex,'mode':mode,'documents':docs,'findings':findings,'calculations':calculations,
        'status':'review' if any(f['severity']=='review' for f in findings) else ('discrepancies' if findings else 'consistent'),
        'trace':events,'harness':{'max_model_turns':meta.MAX_TURNS,'max_tool_calls_total':meta.MAX_TOOL_CALLS,
                                'request_timeout_seconds':60,'cost':None},
        'agent':None,'limitations':['No OCR: image-only pages require review.','Local mode supports labeled statements and documented strict table layouts; unsupported or ambiguous rows require review.']}
    if mode in ('meta','auto'):
        try: report['agent']=meta.reason(docs,findings,calculations,trace=events)
        except meta.MetaError as exc:
            report['agent_error']=str(exc)
            report['status']='review'
    report['metrics']=usage(events,(time.perf_counter()-analysis_started)*1000)
    report=private_report_view(report)
    if persist:
        path=STORE/report['id']; path.mkdir(parents=True)
        for doc,raw in zip(docs,blobs): (path/(doc['id']+'.pdf')).write_bytes(raw)
        save_report(path,report)
    return report

@app.get('/api/cases/{case_id}')
def get_case(case_id): return load(case_id)

@app.get('/api/cases')
def local_history(q:str='',status:str|None=None,decision:str|None=None,limit:int=50,offset:int=0):
    if status and status not in ('consistent','discrepancies','review'):raise HTTPException(422,'Invalid status')
    if decision and decision not in ('pending','confirmed','rejected'):raise HTTPException(422,'Invalid decision')
    if not 1<=limit<=100 or not 0<=offset<=10000:raise HTTPException(422,'Invalid page bounds')
    result=[]
    paths=sorted(STORE.glob('*/report.json'),key=lambda p:p.stat().st_mtime,reverse=True) if STORE.exists() else []
    for path in paths[:10000]:
        try:report=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        identifiers=sorted({d['statement']['loan_id'] for d in report['documents'] if d['statement'].get('loan_id')})
        periods=sorted({d['statement']['period_end'] for d in report['documents'] if d['statement'].get('period_end')})
        decisions=sorted({f.get('human_review',{}).get('decision','pending') for f in report['findings']})
        if status and report['status']!=status:continue
        if decision and decision not in decisions:continue
        if q.lower() not in ' '.join(identifiers+periods+[report['id']]).lower():continue
        result.append({'id':report['id'],'status':report['status'],'identifiers':identifiers,'periods':periods,
                       'review_decisions':decisions,'updated_at':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()})
    return {'cases':result[offset:offset+limit],'total_in_window':len(result),'window_limit':10000,'truncated':len(paths)>10000}

@app.post('/api/cases/search')
def local_history_search(data:HistoryQuery):
    return local_history(data.q,data.status,data.decision,data.limit,data.offset)

@app.get('/api/cases/{case_id}/documents/{doc_id}')
def document(case_id,doc_id):
    report=load(case_id)
    if doc_id not in {d['id'] for d in report['documents']}: raise HTTPException(404,'Document not found')
    return FileResponse(case_path(case_id)/(doc_id+'.pdf'),media_type='application/pdf')

@app.get('/api/cases/{case_id}/documents/{doc_id}/page/{page}')
def page_image(case_id,doc_id,page:int,source:str=''):
    report=load(case_id)
    doc=next((d for d in report['documents'] if d['id']==doc_id),None)
    if not doc:raise HTTPException(404,'Document not found')
    raw=(case_path(case_id)/(doc_id+'.pdf')).read_bytes()
    return Response(platform.render_page(raw,doc,page,source),media_type='image/png',headers={'Cache-Control':'no-store'})

@app.get('/api/cases/{case_id}/search')
def search(case_id,q:str): return retrieve(load(case_id)['documents'],q[:500])

@app.get('/api/cases/{case_id}/export')
def export(case_id,format:str='json'):
    report=report_for_export(load(case_id))
    if format=='json': return Response(json.dumps(report,indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename=paper-trail-report.json'})
    if format!='md': raise HTTPException(422,'Choose json or md')
    text='# Paper Trail Agent\n\nStatus: '+report['status']+'\n\nPattern-redacted export. Original PDFs are excluded. Review unlabeled personal details before sharing.\n\n'
    for finding in report['findings']:
        text+=f"- [ ] [{finding['severity']}] {markdown_text(finding['message'])} Sources: {', '.join(finding['sources']) or 'manual review'}\n"
        review=finding.get('human_review',{'decision':'pending','revision':0,'history':[]})
        text+=f"  Human review: {review['decision']} (revision {review['revision']}); original machine finding retained.\n"
        for entry in review['history']:
            text+=f"  - {entry['timestamp']} {entry['action']}: {markdown_text(entry['note'])}\n"
    if not report['findings']: text+='No discrepancies in the supported checks.\n'
    text+='\n## Source index\n'
    for d in report['documents']:
        for l in d['lines']: text+=f"\n{l['id']} | {d['name']} page {l['page']}: {markdown_text(l['text'])}\n"
    return Response(text,media_type='text/markdown',headers={'Content-Disposition':'attachment; filename=paper-trail-checklist.md'})

@app.delete('/api/cases/{case_id}')
def delete(case_id):
    with CASE_LOCK:
        path=case_path(case_id)
        # Only files inside a validated case directory are removed.
        for file in path.iterdir():
            if file.is_file(): file.unlink()
        path.rmdir()
    return {'deleted':True}

# Service mode rewires the existing frontend URLs to workspace-scoped encrypted
# database endpoints. Local mode preserves the established file-backed workflow.
from . import platform
from .repository import Missing,Conflict,LimitExceeded
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import JSONResponse
app.include_router(platform.create_router(lambda:STORE,analyze_files))

@app.exception_handler(Missing)
async def missing_handler(request,exc):return JSONResponse({'detail':'Not found'},status_code=404)

@app.exception_handler(Conflict)
async def conflict_handler(request,exc):return JSONResponse({'detail':str(exc)},status_code=409)

@app.exception_handler(LimitExceeded)
async def usage_handler(request,exc):return JSONResponse({'detail':'Usage limit reached; try later.'},status_code=429,headers={'Retry-After':'60'})

@app.exception_handler(SQLAlchemyError)
async def database_handler(request,exc):return JSONResponse({'detail':'Database unavailable; no successful result was recorded.'},status_code=503)

@app.middleware('http')
async def service_boundary(request,call_next):
    if platform.service_mode() and request.url.path.startswith('/api/'):
        if request.url.path in ('/api/evals','/api/benchmark'):
            extended=request.url.path=='/api/benchmark'
            try:platform.runtime(STORE)[0].consume('public-benchmark' if extended else 'public-evaluation',60 if extended else 120,3600)
            except HTTPException as exc:return JSONResponse({'detail':exc.detail},status_code=exc.status_code)
            except LimitExceeded:return JSONResponse({'detail':'Evaluation usage limit reached'},status_code=429,headers={'Retry-After':'60'})
            except SQLAlchemyError:return JSONResponse({'detail':'Database unavailable'},status_code=503)
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
                return JSONResponse({'detail':'Cross-origin write rejected'},status_code=403)
            cap=4_000_000 if os.getenv('VERCEL')=='1' else 16*1024*1024
            chunks=[];size=0
            async for chunk in request.stream():
                size+=len(chunk)
                if size>cap:return JSONResponse({'detail':f'Maximum total service request is {cap} bytes.'},status_code=413)
                chunks.append(chunk)
            # Starlette's cached request replays this bounded body to the router.
            request._body=b''.join(chunks)
        if request.url.path=='/api/analyze':target='/api/platform/analyze'
        elif request.url.path=='/api/cases' or request.url.path.startswith('/api/cases/'):
            target='/api/platform'+request.url.path[4:]
        else:target=None
        if target:
            request.scope['path']=target;request.scope['raw_path']=target.encode()
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['X-Frame-Options']='DENY'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    return response
