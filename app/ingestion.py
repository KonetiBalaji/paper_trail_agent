"""Common bounded intake for authenticated uploads and scoped API submissions."""
import hashlib
import os
from fastapi import HTTPException
from . import layout_registry
from .repository import canonical
from .privacy import private_report_view


def engine_fingerprint(mode):
    state=layout_registry.load()
    return hashlib.sha256(canonical({'source':layout_registry.runtime_sources(),
        'dependencies':layout_registry.runtime_dependencies(),'registry':state['status'],
        'receipt':state.get('receipt_sha256'),'mode':mode,
        'model':os.getenv('META_MODEL','muse-spark-1.3') if mode!='local' else None})).hexdigest()


def intake(repo,workspace,actor,files,mode,origin,analyzer,synthetic=False):
    if mode not in ('local','meta','auto'):raise HTTPException(422,'Unsupported analysis mode')
    if not 1<=len(files)<=8:raise HTTPException(422,'Upload 1 to 8 PDFs')
    blobs=[]
    for file in files:
        raw=file.file.read(10*1024*1024+1)
        if len(raw)>10*1024*1024:raise HTTPException(413,'Maximum 10 MB per PDF')
        blobs.append(raw);file.file.seek(0)
    # A multiset, not a set: one PDF and two copies of it are different requests.
    engine=engine_fingerprint(mode)
    fingerprint=hashlib.sha256(canonical([engine,
        sorted(hashlib.sha256(raw).hexdigest() for raw in blobs)])).hexdigest()
    cached=repo.find_intake(workspace,fingerprint,actor,origin)
    if cached is not None:
        result=private_report_view(cached)
        result['intake_receipt']={'created':False,'reused_analysis':True,'model_calls_this_request':0}
        return result
    report=analyzer(files,mode,persist=False)
    report['intake_engine_sha256']=engine
    attempted=report.get('metrics',{}).get('attempted_model_calls',0)
    cacheable=not report.get('agent_error') and not any(i.get('type')=='model_extraction_failed'
        for d in report['documents'] for i in d.get('issues',[]))
    report,created=repo.ingest_case(workspace,actor,fingerprint,report,blobs,origin,cacheable=cacheable,synthetic=synthetic)
    result=private_report_view(report)
    result['intake_receipt']={'created':created,'reused_analysis':not created,
        'model_calls_this_request':attempted}
    return result
