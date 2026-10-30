"""Authenticated service API. The legacy local workflow remains opt-in local mode."""
import hashlib
import io
import json
import os
import tempfile
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit,parse_qs
from cryptography.fernet import Fernet
from fastapi import APIRouter,Depends,File,Form,HTTPException,Request,Response,UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,Field
from .repository import Repository,Missing,Conflict,LimitExceeded
from .security import Security,Principal,Unauthorized
from .privacy import report_for_export,private_report_view,markdown_text

def service_mode():return os.getenv('PAPER_TRAIL_MODE','local')=='service' or os.getenv('VERCEL')=='1'

@lru_cache(maxsize=8)
def _runtime(url,key):
    repo=Repository(url,key)
    return repo,Security(repo,key)

def runtime(root):
    url=os.getenv('DATABASE_URL','').strip();key=os.getenv('DATA_ENCRYPTION_KEY','').strip()
    if service_mode():
        if not url or not key:raise HTTPException(503,'Service requires DATABASE_URL and DATA_ENCRYPTION_KEY in server secret settings.')
        if os.getenv('VERCEL')=='1':
            sslmode=parse_qs(urlsplit(url).query).get('sslmode',[''])[0]
            if not url.startswith(('postgres://','postgresql://','postgresql+psycopg://')) or sslmode not in ('require','verify-ca','verify-full'):
                raise HTTPException(503,'Vercel service requires PostgreSQL with TLS required.')
    else:
        root=Path(root);root.mkdir(parents=True,exist_ok=True)
        url=url or 'sqlite:///'+(root/'platform.sqlite3').as_posix()
        if not key:
            path=root/'platform.key'
            try:
                with path.open('xb') as stream:stream.write(Fernet.generate_key())
                try:path.chmod(0o600)
                except OSError:pass
            except FileExistsError:pass
            key=path.read_text().strip()
    try:Fernet(key.encode())
    except (ValueError,TypeError):raise HTTPException(503,'DATA_ENCRYPTION_KEY must be a valid Fernet key.') from None
    return _runtime(url,key)

class Login(BaseModel):
    model_config=ConfigDict(extra='forbid')
    email:str=Field(min_length=3,max_length=254)
    password:str=Field(min_length=1,max_length=128)

class UserCreate(Login):
    workspace:str=Field(min_length=1,max_length=80)
    role:Literal['admin','reviewer','viewer']

class Review(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    action:Literal['confirm','reject','note']
    note:str=Field(default='',max_length=2000)
    expected_revision:int=Field(ge=0,strict=True)
    expected_case_version:int|None=Field(default=None,ge=1,strict=True)

class OCRRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_version:int=Field(ge=1,strict=True)

class HistoryQuery(BaseModel):
    model_config=ConfigDict(extra='forbid')
    q:str=Field(default='',max_length=200)
    status:Literal['consistent','discrepancies','review']|None=None
    decision:Literal['pending','confirmed','rejected']|None=None
    limit:int=Field(default=50,ge=1,le=100)
    offset:int=Field(default=0,ge=0,le=10000)

def render_page(raw,doc,page,source):
    import pypdfium2 as pdfium
    from PIL import ImageDraw
    with pdfium.PdfDocument(raw) as pdf:
        if not 1<=page<=len(pdf):raise HTTPException(404,'Page not found')
        width,height=pdf[page-1].get_size()
        if width<=0 or height<=0:raise HTTPException(422,'Invalid PDF page dimensions')
        scale=min(1.5,1000/width,1400/height)
        image=pdf[page-1].render(scale=scale).to_pil().convert('RGB')
        line=next((l for l in doc['lines'] if l['id']==source and l['page']==page),None)
        if line:ImageDraw.Draw(image,'RGBA').rectangle([v*scale for v in line['bbox']],fill=(255,208,50,65),outline=(202,135,0,255),width=2)
        output=io.BytesIO();image.save(output,format='PNG');return output.getvalue()

def markdown_report(report):
    text=f"# Paper Trail Agent\n\nMachine status: {report['status']}\n\nPattern-redacted export. Original PDFs are excluded. Review unlabeled personal details before sharing.\n\n"
    if report.get('report_version'):text+=f"Report version: {report['report_version']}\n\n"
    if report.get('derived_from',{}).get('kind')=='ocr':
        text+=f"Derived from report version {report['derived_from']['version']}. Previous reviews remain in that immutable version.\n\nOCR values and calculations are unverified candidates. Recognizer scores are uncalibrated and do not prove financial correctness. Human approval of a finding does not verify all OCR fields.\n\n"
    for f in report['findings']:
        text+=f"- [ ] [{f['severity']}] {markdown_text(f['message'])} Sources: {', '.join(f['sources']) or 'manual review'}\n"
        review=f.get('human_review',{'decision':'pending','revision':0,'history':[]})
        text+=f"  Human review: {review['decision']} (revision {review['revision']}); original machine result retained.\n"
        for event in review['history']:text+=f"  - {event['timestamp']} {event['action']}: {markdown_text(event['note'])}\n"
    if not report['findings']:text+='No discrepancies in supported checks.\n'
    if any(calculation.get('provisional') for calculation in report['calculations']):
        text+='\n## Provisional OCR arithmetic\n'
        for calculation in report['calculations']:
            if calculation.get('provisional'):
                text+=f"\nIf the recognized values are correct: {' + '.join(calculation['operands'])} = {calculation['computed']}; recognized stated amount {calculation['stated']}. Verify the original PDF.\n"
    text+='\n## Source index\n'
    for doc in report['documents']:
        for line in doc['lines']:
            qualifier=f" [OCR score {line['confidence']:.3f}; uncalibrated; {'unverified candidate' if line['usable'] else 'excluded from checks'}]" if line.get('method')=='ocr' else ''
            text+=f"\n{line['id']} | {doc['name']} page {line['page']}{qualifier}: {markdown_text(line['text'])}\n"
    return text

def create_router(root_provider,analyze_files):
    router=APIRouter(prefix='/api/platform')
    def resources():return runtime(root_provider())

    def principal(request:Request):
        if not service_mode():return Principal('local-operator','local','admin')
        repo,security=resources()
        try:return security.authenticate(request.cookies.get('pta_session'))
        except Unauthorized as exc:raise HTTPException(401,str(exc)) from None

    def write_principal(request:Request,actor=Depends(principal)):
        if actor.role not in ('admin','reviewer','demo'):raise HTTPException(403,'Reviewer permission required')
        if service_mode():
            try:resources()[1].validate_csrf(actor,request.headers.get('X-CSRF-Token'),request.cookies.get('pta_csrf'))
            except Unauthorized:raise HTTPException(403,'CSRF validation failed') from None
        return actor

    @router.get('/config')
    def config():return {'mode':'service' if service_mode() else 'local','authentication_required':service_mode(),
                        'storage':'encrypted_database' if service_mode() else 'local_files',
                        'public_demo_live_meta':False,'public_demo':service_mode(),
                        'ocr':{'supported':service_mode(),'available':resources()[0].worker_status()['ocr'] if service_mode() else False,
                               'max_pages_per_case':5,'timeout_seconds':90}}

    @router.post('/demo/start')
    def demo_start(request:Request,response:Response):
        repo,security=resources()
        repo.consume('demo-start-global',60,3600)
        repo.consume('demo-start:'+security.digest(request.client.host if request.client else 'unknown'),6,3600)
        repo.expire_demo_data()
        token,csrf=security.demo_session()
        response.set_cookie('pta_session',token,httponly=True,secure=service_mode(),samesite='strict',max_age=3600,path='/')
        response.set_cookie('pta_csrf',csrf,secure=service_mode(),samesite='strict',max_age=3600,path='/')
        actor=security.authenticate(token)
        return {'id':actor.id,'workspace':actor.workspace,'role':actor.role,'expires_in_seconds':3600}

    @router.post('/demo/cases/{fixture}')
    def demo_case(fixture:str,actor=Depends(write_principal)):
        if actor.role!='demo':raise HTTPException(403,'Start a synthetic demo session first')
        if fixture not in ('clean','contradiction','math_error','messy'):raise HTTPException(404,'Unknown synthetic case')
        repo,_=resources();repo.consume('demo-analysis-global',240,3600);repo.consume('demo-analysis:'+actor.workspace,12,3600)
        # Fixed allowlisted repository fixtures only. No paths, uploads or model mode
        # are accepted from a visitor, and each session owns a separate workspace.
        paths=sorted((Path(__file__).resolve().parents[1]/'data'/'synthetic'/fixture).glob('*.pdf'))
        if len(paths)!=2:raise HTTPException(503,'Demo fixtures unavailable')
        blobs=[path.read_bytes() for path in paths]
        uploads=[UploadFile(filename=path.name,file=io.BytesIO(raw)) for path,raw in zip(paths,blobs)]
        report=analyze_files(uploads,'local',persist=False)
        report['demo']={'synthetic':True,'mode':'local','model_calls':0,'session_seconds':3600}
        repo.create_case(actor.workspace,actor.id,report,blobs,synthetic=True)
        return report

    @router.post('/auth/login')
    def login(data:Login,request:Request,response:Response):
        repo,security=resources()
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
            raise HTTPException(403,'Cross-origin login rejected')
        repo.consume('login:'+security.digest(request.client.host if request.client else 'unknown'),10,900)
        try:token,csrf=security.login(data.email,data.password)
        except Unauthorized:raise HTTPException(401,'Invalid credentials') from None
        response.set_cookie('pta_session',token,httponly=True,secure=service_mode(),samesite='strict',max_age=28800,path='/')
        response.set_cookie('pta_csrf',csrf,httponly=False,secure=service_mode(),samesite='strict',max_age=28800,path='/')
        actor=security.authenticate(token)
        return {'id':actor.id,'workspace':actor.workspace,'role':actor.role}

    @router.get('/auth/me')
    def me(actor=Depends(principal)):return {'id':actor.id,'workspace':actor.workspace,'role':actor.role}

    @router.post('/auth/logout')
    def logout(request:Request,response:Response,actor=Depends(principal)):
        if service_mode():
            try:resources()[1].validate_csrf(actor,request.headers.get('X-CSRF-Token'),request.cookies.get('pta_csrf'))
            except Unauthorized:raise HTTPException(403,'CSRF validation failed') from None
        resources()[1].logout(request.cookies.get('pta_session'))
        response.delete_cookie('pta_session',path='/');response.delete_cookie('pta_csrf',path='/')
        return {'signed_out':True}

    @router.post('/users')
    def add_user(data:UserCreate,actor=Depends(write_principal)):
        if actor.role!='admin' or data.workspace!=actor.workspace:raise HTTPException(403,'Workspace administrator required')
        try:return resources()[1].create_user(data.email,data.password,data.workspace,data.role,actor.id)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None

    @router.delete('/users/{user_id}')
    def disable_user(user_id,actor=Depends(write_principal)):
        if actor.role!='admin' or user_id==actor.id:raise HTTPException(403,'Another workspace account must be selected by an administrator')
        resources()[1].disable(actor.workspace,actor.id,user_id);return {'disabled':True}

    @router.post('/analyze')
    def analyze(files:list[UploadFile]=File(...),mode:str=Form('local'),actor=Depends(write_principal)):
        if actor.role=='demo':raise HTTPException(403,'Public demo accepts fixed synthetic cases only; no uploads or model calls')
        repo,_=resources();repo.consume('analysis:'+actor.workspace,20,3600)
        if mode in ('meta','auto'):repo.consume('meta:'+actor.workspace,10,3600)
        # The pipeline still enforces byte/page/text limits before model use.
        blobs=[]
        if not 1<=len(files)<=8:raise HTTPException(422,'Upload 1 to 8 PDFs')
        for file in files:
            raw=file.file.read(10*1024*1024+1)
            if len(raw)>10*1024*1024:raise HTTPException(413,'Maximum 10 MB per PDF')
            blobs.append(raw);file.file.seek(0)
        report=analyze_files(files,mode,persist=False)
        repo.create_case(actor.workspace,actor.id,report,blobs)
        return report

    @router.get('/cases')
    def history(q:str='',status:str|None=None,decision:str|None=None,limit:int=50,offset:int=0,actor=Depends(principal)):
        try:return resources()[0].list_cases(actor.workspace,q[:200],status,decision,limit,offset)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None

    @router.post('/cases/search')
    def history_search(data:HistoryQuery,request:Request,actor=Depends(principal)):
        # Searches are read-only for viewers; the body avoids exposing loan IDs
        # in browser history, referrers and ordinary host request-URL logs.
        if service_mode():
            try:resources()[1].validate_csrf(actor,request.headers.get('X-CSRF-Token'),request.cookies.get('pta_csrf'))
            except Unauthorized:raise HTTPException(403,'CSRF validation failed') from None
        return history(data.q,data.status,data.decision,data.limit,data.offset,actor)

    @router.get('/cases/{case_id}')
    def case(case_id,version:int|None=None,actor=Depends(principal)):
        return private_report_view(resources()[0].get_case(actor.workspace,case_id,version))

    @router.patch('/cases/{case_id}/findings/{finding_id}')
    def review(case_id,finding_id,data:Review,actor=Depends(write_principal)):
        try:return private_report_view(resources()[0].review(actor.workspace,actor.id,case_id,finding_id,data.action,data.note,data.expected_revision,data.expected_case_version))
        except ValueError as exc:raise HTTPException(422,str(exc)) from None

    @router.get('/cases/{case_id}/audit')
    def audit(case_id,actor=Depends(principal)):
        repo,_=resources();repo.get_case(actor.workspace,case_id)
        return repo.audit(actor.workspace,case_id)

    @router.get('/cases/{case_id}/ocr')
    def ocr_status(case_id,actor=Depends(principal)):
        repo,_=resources()
        info=repo.ocr_info(actor.workspace,case_id)
        return {**info,'worker_available':repo.worker_status()['ocr']}

    @router.post('/cases/{case_id}/ocr')
    def queue_ocr(case_id,data:OCRRequest,actor=Depends(write_principal)):
        if not service_mode():raise HTTPException(409,'OCR jobs require authenticated database service mode')
        if actor.role=='demo':raise HTTPException(403,'Public synthetic guests cannot queue OCR jobs')
        repo,_=resources();repo.get_case(actor.workspace,case_id)
        if not repo.worker_status()['ocr']:raise HTTPException(503,'No OCR worker is available. Start the separate OCR worker before requesting a job.')
        repo.consume('ocr-jobs:'+actor.workspace,10,3600)
        try:result=repo.enqueue_ocr(actor.workspace,actor.id,case_id,data.expected_version)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        return JSONResponse(result,status_code=202)

    @router.get('/cases/{case_id}/documents/{doc_id}')
    def original(case_id,doc_id,actor=Depends(principal)):
        from fastapi.responses import StreamingResponse
        raw=resources()[0].get_document(actor.workspace,case_id,doc_id)
        chunks=(raw[offset:offset+65536] for offset in range(0,len(raw),65536))
        return StreamingResponse(chunks,media_type='application/pdf',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

    @router.get('/cases/{case_id}/documents/{doc_id}/page/{page}')
    def page(case_id,doc_id,page:int,source:str='',actor=Depends(principal)):
        repo,_=resources();report=repo.get_case(actor.workspace,case_id)
        doc=next((d for d in report['documents'] if d['id']==doc_id),None)
        if doc is None:raise HTTPException(404,'Document not found')
        return Response(render_page(repo.get_document(actor.workspace,case_id,doc_id),doc,page,source),
                        media_type='image/png',headers={'Cache-Control':'no-store'})

    @router.get('/cases/{case_id}/search')
    def search(case_id,q:str,actor=Depends(principal)):
        from .core import retrieve
        return retrieve(resources()[0].get_case(actor.workspace,case_id)['documents'],q[:500])

    @router.get('/cases/{case_id}/export')
    def export(case_id,format:str='json',version:int|None=None,actor=Depends(principal)):
        report=report_for_export(resources()[0].get_case(actor.workspace,case_id,version))
        if format=='json':body=json.dumps(report,indent=2);media='application/json'
        elif format=='md':body=markdown_report(report);media='text/markdown'
        else:raise HTTPException(422,'Choose json or md')
        return Response(body,media_type=media,headers={'Cache-Control':'no-store',
                        'Content-Disposition':f'attachment; filename=paper-trail-report.{format}'})

    @router.delete('/cases/{case_id}')
    def remove(case_id,actor=Depends(write_principal)):
        resources()[0].delete_case(actor.workspace,actor.id,case_id);return {'deleted':True}

    @router.post('/jobs/eval')
    def enqueue_eval(actor=Depends(write_principal)):
        if actor.role=='demo':raise HTTPException(403,'Public demo cannot queue jobs; use offline evals')
        repo,_=resources();repo.consume('jobs:'+actor.workspace,10,3600)
        job_id=repo.enqueue(actor.workspace,actor.id,'eval',{})
        return JSONResponse({'job_id':job_id,'state':'queued'},status_code=202)

    @router.get('/jobs/{job_id}')
    def get_job(job_id,actor=Depends(principal)):return resources()[0].get_job(actor.workspace,job_id)

    return router
