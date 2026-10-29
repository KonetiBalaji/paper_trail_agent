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

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
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

def load(case_id): return json.loads((case_path(case_id)/'report.json').read_text())

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
    if mode not in ('local','meta'): raise HTTPException(422,'Choose local or meta mode')
    if not 1<=len(files)<=8: raise HTTPException(422,'Upload 1 to 8 PDFs')
    if mode=='meta' and not meta.configured(): raise HTTPException(503,'Set MODEL_API_KEY in .env and restart before using Meta mode.')
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
        if mode=='meta' and not doc['issues']:
            try: doc['statement']=meta.extract(doc,trace=events)
            except meta.MetaError as exc:
                doc['statement']=parse_statement({'lines':[]})
                doc['issues'].append({'type':'model_extraction_failed','message':str(exc)})
        else:
            started=time.perf_counter();doc['statement']=parse_statement(doc)
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
        'agent':None,'limitations':['No OCR: image-only pages require review.','Local mode supports labeled statements only.']}
    if mode=='meta':
        try: report['agent']=meta.reason(docs,findings,calculations,trace=events)
        except meta.MetaError as exc:
            report['agent_error']=str(exc)
            report['status']='review'
    path=STORE/report['id']; path.mkdir(parents=True)
    for doc,raw in zip(docs,blobs): (path/(doc['id']+'.pdf')).write_bytes(raw)
    save_report(path,report)
    return report

@app.get('/api/cases/{case_id}')
def get_case(case_id): return load(case_id)

@app.get('/api/cases/{case_id}/documents/{doc_id}')
def document(case_id,doc_id):
    report=load(case_id)
    if doc_id not in {d['id'] for d in report['documents']}: raise HTTPException(404,'Document not found')
    return FileResponse(case_path(case_id)/(doc_id+'.pdf'),media_type='application/pdf')

@app.get('/api/cases/{case_id}/documents/{doc_id}/page/{page}')
def page_image(case_id,doc_id,page:int,source:str=''):
    import pypdfium2 as pdfium
    from PIL import ImageDraw
    report=load(case_id)
    doc=next((d for d in report['documents'] if d['id']==doc_id),None)
    if not doc:raise HTTPException(404,'Document not found')
    with pdfium.PdfDocument(str(case_path(case_id)/(doc_id+'.pdf'))) as pdf:
        if not 1<=page<=len(pdf):raise HTTPException(404,'Page not found')
        image=pdf[page-1].render(scale=1.5).to_pil().convert('RGB')
        line=next((l for l in doc['lines'] if l['id']==source and l['page']==page),None)
        if line:
            draw=ImageDraw.Draw(image,'RGBA')
            draw.rectangle([v*1.5 for v in line['bbox']],fill=(255,208,50,65),outline=(202,135,0,255),width=2)
        output=io.BytesIO();image.save(output,format='PNG')
    return Response(output.getvalue(),media_type='image/png',headers={'Cache-Control':'no-store'})

@app.get('/api/cases/{case_id}/search')
def search(case_id,q:str): return retrieve(load(case_id)['documents'],q[:500])

@app.get('/api/cases/{case_id}/export')
def export(case_id,format:str='json'):
    report=load(case_id)
    if format=='json': return Response(json.dumps(report,indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename=paper-trail-report.json'})
    if format!='md': raise HTTPException(422,'Choose json or md')
    text='# Paper Trail Agent\n\nStatus: '+report['status']+'\n\n'
    for finding in report['findings']:
        text+=f"- [ ] [{finding['severity']}] {finding['message']} Sources: {', '.join(finding['sources']) or 'manual review'}\n"
        review=finding.get('human_review',{'decision':'pending','revision':0,'history':[]})
        text+=f"  Human review: {review['decision']} (revision {review['revision']}); original machine finding retained.\n"
        for entry in review['history']:
            text+=f"  - {entry['timestamp']} {entry['action']}: {entry['note']}\n"
    if not report['findings']: text+='No discrepancies in the supported checks.\n'
    text+='\n## Source index\n'
    for d in report['documents']:
        for l in d['lines']: text+=f"\n{l['id']} | {d['name']} page {l['page']}: {l['text']}\n"
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
