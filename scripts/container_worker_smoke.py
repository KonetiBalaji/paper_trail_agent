"""Real offline image gate, including SIGTERM during an OCR job. Linux only."""
import io
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

ROOT=Path(__file__).resolve().parents[1]


def memory_peak():
    for name in ('/sys/fs/cgroup/memory.peak','/sys/fs/cgroup/memory/memory.max_usage_in_bytes'):
        try:return int(Path(name).read_text().strip())
        except (OSError,ValueError):pass
    return None


def main():
    from cryptography.fernet import Fernet
    from fastapi import UploadFile
    from app.repository import Repository
    checks=[];started=time.monotonic()
    def check(name,condition):
        checks.append({'check':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
    check('linux_amd64',platform.system()=='Linux' and platform.machine() in ('x86_64','amd64'))
    check('non_root',os.geteuid()!=0)
    check('application_read_only',not os.access(ROOT,os.W_OK))
    check('no_private_build_context',not any((ROOT/name).exists() for name in
          ('.env.worker-build-probe','app/.env.worker-build-probe','data/private','work','storage')))
    check('all_env_files_excluded',not list(ROOT.rglob('.env*')))
    with tempfile.TemporaryDirectory(prefix='worker-smoke-',dir='/tmp') as temporary:
        folder=Path(temporary).resolve()
        if folder.parent!=Path('/tmp').resolve():raise RuntimeError('Unexpected test directory')
        key=Fernet.generate_key().decode();url='sqlite:///'+(folder/'cases.db').as_posix()
        env={**os.environ,'PAPER_TRAIL_MODE':'local','DATABASE_URL':url,'DATA_ENCRYPTION_KEY':key,
             'MODEL_API_KEY':'synthetic-unused-model-marker'}
        env.pop('VERCEL',None)
        os.environ['MODEL_API_KEY']=''
        from app.main import analyze_files
        from scripts.evaluate_ocr import evaluate
        repo=Repository(url,key)
        worker=None
        try:
            raw=(ROOT/'data/ocr/labeled_error.pdf').read_bytes()
            original=analyze_files([UploadFile(filename='fictional-scan.pdf',file=io.BytesIO(raw))],persist=False)
            repo.create_case('container-synthetic','container-test',original,[raw])
            queued=repo.enqueue_ocr('container-synthetic','container-test',original['id'],1)
            worker=subprocess.Popen([sys.executable,'scripts/worker_entrypoint.py','--poll-seconds','15'],cwd=ROOT,env=env,
                                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            deadline=time.monotonic()+30
            while repo.get_job('container-synthetic',queued['job_id'])['state']!='running':
                if worker.poll() is not None:raise RuntimeError('Container worker exited before claiming OCR')
                if time.monotonic()>deadline:raise TimeoutError('Container worker did not claim OCR')
                time.sleep(.05)
            # A second job must remain queued after the stop request, while the
            # already-owned OCR finishes and commits its report atomically.
            untouched=repo.enqueue('container-synthetic','container-test','eval',{})
            stop_started=time.monotonic();worker.send_signal(signal.SIGTERM)
            out,err=worker.communicate(timeout=110)
            shutdown_seconds=round(time.monotonic()-stop_started,2)
            check('sigterm_exit_zero',worker.returncode==0)
            check('no_model_marker_in_logs','synthetic-unused-model-marker' not in out+err)
            check('active_ocr_completed',repo.get_job('container-synthetic',queued['job_id'])['state']=='completed')
            check('no_new_job_after_sigterm',repo.get_job('container-synthetic',untouched)['state']=='queued')
            check('heartbeat_retired',not any(repo.worker_status().values()))
            derived=repo.get_case('container-synthetic',original['id'])
            check('versioned_review',derived['report_version']==2 and derived['status']=='review')
            check('fifty_candidate_difference',any(f.get('difference')=='50.00' and f['severity']=='review' for f in derived['findings']))
            check('zero_model_calls',derived['metrics']['attempted_model_calls']==0)
            check('original_pdf_unchanged',repo.get_document('container-synthetic',original['id'],'doc1')==raw)
            check('original_report_unchanged',repo.get_case('container-synthetic',original['id'],1)==original)
            check('audit_verified',repo.audit('container-synthetic')['verified'])
            scans=evaluate(ROOT/'data/ocr')
            check('four_actual_scan_cases',scans['passed'] and len(scans['cases'])==4)
        finally:
            if worker is not None and worker.poll() is None:
                worker.kill();worker.communicate(timeout=5)
            repo.close()
    report={'passed':True,'scope':'Offline Linux amd64 image, read-only root, non-root user, 1 CPU/1 GiB CI limit. Actual OCR, encrypted SQLite versions and in-flight SIGTERM; not a hosted PostgreSQL or Vercel daemon proof.',
            'duration_seconds':round(time.monotonic()-started,2),'shutdown_seconds':shutdown_seconds,
            'cgroup_memory_peak_bytes':memory_peak(),'checks':checks,
            'ocr_cases':[{'case':row['case'],'checks':row['checks']} for row in scans['cases']],
            'model_sha256':scans['model_sha256']}
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
