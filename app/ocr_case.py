"""Build a review-only derived case from immutable originals, without model calls."""
import copy
import time
from .core import read_pdf,reconcile
from .ocr import extract,recognize,candidate_checks
from .privacy import private_report_view
from .telemetry import usage
from .trace import record


def build_report(repo,job):
    started=time.monotonic();deadline=started+90
    payload=job['payload'];case_id=payload['case_id'];expected=payload['expected_version']
    report=repo.get_case(job['workspace'],case_id)
    if report['report_version']!=expected:raise ValueError('Case changed before OCR')
    required=sum(len({i['page'] for i in doc['issues'] if i['type']=='ocr_required'}) for doc in report['documents'])
    if not 1<=required<=5:raise ValueError('OCR case page limit')
    report=copy.deepcopy(report);events=[];docs=[]
    record(events,'version','derived_report',{'previous_version':expected,'job_id':job['id']},
           {'model_calls':0,'originals_unchanged':True})
    for previous in report['documents']:
        if not any(i['type']=='ocr_required' for i in previous['issues']):
            docs.append(previous);continue
        raw=repo.get_document(job['workspace'],case_id,previous['id'])
        original=read_pdf(raw,previous['name'],previous['id'])
        def bounded(raw,doc_id,pages):
            remaining=deadline-time.monotonic()
            if remaining<.1:raise TimeoutError('OCR case deadline reached')
            return recognize(raw,doc_id,pages,timeout=min(90,remaining))
        doc=extract(raw,original,recognizer=bounded)
        doc['routing']={'requested':'ocr','selected':'ocr_candidate','reason':'image_only_pages_require_human_verification'}
        docs.append(doc)
        record(events,'extraction','offline_ocr',{'document':doc['id'],'pages':doc['ocr']['pages']},
               {'engine':doc['ocr']['engine'],'usable_lines':doc['ocr']['usable_lines'],
                'total_lines':doc['ocr']['total_lines'],'scores_calibrated':False},
               validation='review',duration_ms=doc['ocr']['duration_ms'],document=doc['id'])
    from .orchestration import run
    findings,calculations,orchestration=run(docs,events)
    for doc in docs:
        if not doc.get('ocr',{}).get('performed'):continue
        candidates,math=candidate_checks(doc)
        known={(f['type'],tuple(f['sources'])) for f in findings}
        for finding in candidates:
            if finding['type']=='ocr_review':
                existing=next((f for f in findings if f['type']=='ocr_review' and f.get('document')==doc['id']),None)
                if existing:existing['sources']=finding['sources']
                continue
            if (finding['type'],tuple(finding['sources'])) not in known:
                findings.append(finding)
        calculations.extend(math)
    for index,finding in enumerate(findings,1):
        finding['id']=f'F{index}'
        finding['human_review']={'decision':'pending','revision':0,'history':[]}
    for calculation in calculations:
        record(events,'calculator','ocr_candidate_total' if calculation.get('provisional') else 'deterministic_total',
               {'operands':calculation['operands']},{'computed':calculation['computed'],'stated':calculation['stated'],
                'provisional':bool(calculation.get('provisional'))},
               validation='review' if calculation.get('provisional') else 'passed',document=calculation['document'])
    record(events,'validation','ocr_review_gate',output={'status':'review','findings':len(findings),
           'prior_reviews':'Retained in the previous immutable report version; new findings start pending.'},validation='review')
    report.update(mode='ocr',previous_mode=report['mode'],documents=docs,findings=findings,calculations=calculations,orchestration=orchestration,status='review',trace=events,
                  agent=None,agent_status='OCR candidate pass: model investigation was not run. Prior analysis is retained in its report version.',
                  derived_from={'version':expected,'job_id':job['id'],'kind':'ocr'})
    report.pop('agent_error',None)
    report['limitations']=[line for line in report.get('limitations',[]) if not line.startswith('No OCR:')]
    report['limitations'].append('OCR candidates require human verification. Recognizer scores are uncalibrated; no automatic clean result or confirmed OCR discrepancy.')
    report['metrics']=usage(events,(time.monotonic()-started)*1000)
    return private_report_view(report)
