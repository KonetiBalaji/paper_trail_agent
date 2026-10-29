from pathlib import Path
import json
import os
import re
import uuid
import io
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from .core import read_pdf, parse_statement, reconcile, retrieve
from . import meta

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
STORE = Path(os.getenv('PAPER_TRAIL_STORAGE', str(ROOT/'storage')))
app = FastAPI(title='Paper Trail Agent')
app.mount('/static',StaticFiles(directory=ROOT/'app'/'static'),name='static')

@app.get('/')
def home(): return FileResponse(ROOT/'app'/'static'/'index.html')

@app.get('/api/health')
def health(): return {'status':'ok','meta_configured':meta.configured(),'model':os.getenv('META_MODEL','muse-spark-1.3')}

def case_path(case_id):
    if not re.fullmatch(r'[a-f0-9]{32}',case_id): raise HTTPException(404,'Case not found')
    path=STORE/case_id
    if not (path/'report.json').is_file(): raise HTTPException(404,'Case not found')
    return path

def load(case_id): return json.loads((case_path(case_id)/'report.json').read_text())

@app.post('/api/analyze')
def analyze(files: list[UploadFile] = File(...), mode: str = Form('local')):
    if mode not in ('local','meta'): raise HTTPException(422,'Choose local or meta mode')
    if not 1<=len(files)<=8: raise HTTPException(422,'Upload 1 to 8 PDFs')
    if mode=='meta' and not meta.configured(): raise HTTPException(503,'Set MODEL_API_KEY in .env and restart before using Meta mode.')
    docs, blobs = [], []
    for i,file in enumerate(files):
        raw=file.file.read(10*1024*1024+1)
        if len(raw)>10*1024*1024: raise HTTPException(413,'Maximum 10 MB per PDF')
        name=(file.filename or 'statement.pdf').replace('\\','/').split('/')[-1][:150]
        try: doc=read_pdf(raw,name,f'doc{i+1}')
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
        if sum(len(l['text']) for l in doc['lines'])>100000: raise HTTPException(413,'Document text exceeds 100,000 characters')
        if mode=='meta' and not doc['issues']:
            try: doc['statement']=meta.extract(doc)
            except meta.MetaError as exc:
                doc['statement']=parse_statement({'lines':[]})
                doc['issues'].append({'type':'model_extraction_failed','message':str(exc)})
        else: doc['statement']=parse_statement(doc)
        docs.append(doc); blobs.append(raw)
    findings, calculations = reconcile(docs)
    report={'id':uuid.uuid4().hex,'mode':mode,'documents':docs,'findings':findings,'calculations':calculations,
        'status':'review' if any(f['severity']=='review' for f in findings) else ('discrepancies' if findings else 'consistent'),
        'agent':None,'limitations':['No OCR: image-only pages require review.','Local mode supports labeled tranche statements only.']}
    if mode=='meta':
        try: report['agent']=meta.reason(docs,findings,calculations)
        except meta.MetaError as exc:
            report['agent_error']=str(exc)
            report['status']='review'
    path=STORE/report['id']; path.mkdir(parents=True)
    for doc,raw in zip(docs,blobs): (path/(doc['id']+'.pdf')).write_bytes(raw)
    (path/'report.json').write_text(json.dumps(report),encoding='utf-8')
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
    if not report['findings']: text+='No discrepancies in the supported checks.\n'
    text+='\n## Source index\n'
    for d in report['documents']:
        for l in d['lines']: text+=f"\n{l['id']} | {d['name']} page {l['page']}: {l['text']}\n"
    return Response(text,media_type='text/markdown',headers={'Content-Disposition':'attachment; filename=paper-trail-checklist.md'})

@app.delete('/api/cases/{case_id}')
def delete(case_id):
    path=case_path(case_id)
    # Only fixed files inside a validated case directory are removed.
    for file in path.iterdir():
        if file.is_file(): file.unlink()
    path.rmdir()
    return {'deleted':True}
