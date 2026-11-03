"""Durable leased worker. Run separately from the request process."""
import argparse
import time
import uuid
import importlib.util
import signal
import threading
from pathlib import Path
from .platform import runtime
from .evals import evaluate_suite
from .repository import Conflict, Missing

def capabilities():
    return ['eval','monitor','ocr'] if importlib.util.find_spec('rapidocr_onnxruntime') is not None else ['eval','monitor']

def run_once(repo,kinds=None):
    job=repo.claim_job(lease_seconds=120,kinds=kinds)
    if job is None:return False
    detections = []
    try:
        if job['kind']=='eval':
            result=evaluate_suite()
            failed=bool(result['summary']['failed'])
        elif job['kind']=='monitor':
            from .historical import prior_case_history
            counts = {'passed': 0, 'discrepancy': 0, 'review': 0}
            deadline = time.monotonic() + 90
            for document_id in job['payload']['documents']:
                offset = 0
                while offset is not None:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Monitor lease budget exceeded')
                    page = prior_case_history(repo, job['workspace'], job['payload']['case_id'], document_id, offset=offset)
                    for comparison in page['comparisons']:
                        counts[comparison['pair']['result']] += 1
                        if comparison['pair']['result'] == 'discrepancy':
                            detections.append({'document_id': document_id, 'comparison': comparison})
                    offset = page['next_offset']
            result = {'comparison_counts': counts}
            failed = False
        elif job['kind']=='ocr':
            from .ocr_case import build_report
            derived=build_report(repo,job)
            result=None;failed=False
        else:
            # Pending handlers never masquerade as a completed OCR/ingest job.
            result={'error':'Handler not implemented; manual action required.'};failed=True
    except Exception as exc:
        from .ocr import OCRUnavailable
        if isinstance(exc,OCRUnavailable):
            result={'error':'OCR dependencies unavailable on this worker; manual review required.'};failed=True
        elif isinstance(exc,TimeoutError):
            result={'error':'OCR exceeded its time limit; manual review required.'};failed=True
        else:
            result={'error':'Job failed; reopen the case and inspect sanitized service diagnostics.'};failed=True
    # Never retry a completion whose database outcome could be unknown.
    try:
        if job['kind']=='ocr' and not failed:
            repo.complete_ocr(job['id'],job['lease_token'],derived)
        else:
            try:
                repo.complete_job(job['id'],job['lease_token'],result,failed=failed,
                                  detections=detections if not failed else ())
            except Missing:
                if job['kind'] != 'monitor':
                    raise
                # A source was deleted before the evidence transaction committed.
                repo.complete_job(job['id'], job['lease_token'],
                                  {'error': 'A source case was removed during monitoring.'}, failed=True)
    except Conflict:
        # An expired lease belongs to another worker. Its result wins.
        pass
    return True

def serve(repo,kinds,stop,once=False,poll_seconds=1):
    """Finish an owned job on shutdown, retire readiness, and claim no new work."""
    worker_id=uuid.uuid4().hex;last_heartbeat=float('-inf');last_retention=float('-inf')
    try:
        while not stop.is_set():
            if time.monotonic()-last_retention>=300:
                repo.purge_retained_cases();last_retention=time.monotonic()
            if time.monotonic()-last_heartbeat>=30:
                repo.touch_worker(worker_id,kinds);last_heartbeat=time.monotonic()
            if stop.is_set():break
            worked=run_once(repo,kinds=kinds)
            if once:return
            if not worked:stop.wait(poll_seconds)
    finally:repo.retire_worker(worker_id)


def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    from .privacy import install_log_redaction
    install_log_redaction()
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--once',action='store_true')
    parser.add_argument('--poll-seconds',type=int,default=1,choices=range(1,61))
    args=parser.parse_args();repo,_=runtime(Path(__file__).resolve().parents[1]/'storage')
    stop=threading.Event();previous={}
    for sig in (signal.SIGTERM,signal.SIGINT):
        previous[sig]=signal.signal(sig,lambda *_:stop.set())
    try:
        serve(repo,capabilities(),stop,args.once,args.poll_seconds)
    finally:
        # An expired heartbeat is sufficient on crashes; no case/job is retried
        # merely because shutdown could not update operational metadata.
        for sig,handler in previous.items():signal.signal(sig,handler)
        repo.close()

if __name__=='__main__':main()
