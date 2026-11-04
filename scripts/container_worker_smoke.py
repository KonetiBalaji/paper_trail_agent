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


def check_monitoring(repo, env, check):
    from fastapi import UploadFile
    from reportlab.pdfgen import canvas

    from app.ingestion import intake
    from app.main import analyze_files

    workspace = 'container-monitor'
    actor = 'container-test'
    cases = []
    for month, last_day, opening, closing in (
        ('09', 30, '1000.00', '900.00'), ('10', 31, '950.00', '850.00'),
    ):
        stream = io.BytesIO()
        pdf = canvas.Canvas(stream, invariant=True)
        end = f'2026-{month}-{last_day}'
        lines = [
            'Historical rules: PTA-BANK-PERIOD-V1',
            'Account: FICTIONAL-001',
            'Currency: USD',
            f'Period start: 2026-{month}-01',
            f'Period end: {end}',
            f'Opening balance: {opening}',
            'Transaction count: 1',
            f'Transaction PAYMENT-1 | {end} | Amount: -100.00',
            f'Closing balance: {closing}',
        ]
        for index, line in enumerate(lines):
            pdf.drawString(40, 750 - index * 20, line)
        pdf.save()
        stream.seek(0)
        report = intake(repo, workspace, actor, [UploadFile(stream, filename='statement.pdf')],
                        'local', 'upload', analyze_files)
        cases.append(report['id'])
        subprocess.run([sys.executable, 'scripts/worker_entrypoint.py', '--once'],
                       cwd=ROOT, env=env, check=True, timeout=120)
    earlier, latest = cases
    entry, = repo.monitor_timeline(workspace, latest)['entries']
    comparison = entry['comparison']
    check('monitor_earlier_case', comparison['prior']['case_id'] == earlier)
    check('monitor_exact_carry_difference', comparison['pair']['difference'] == '50.00')
    closing, opening = comparison['pair']['carry_sources']
    for case_id, source, label in (
        (earlier, closing.split('/', 1)[1], 'Closing balance: 900.00'),
        (latest, opening, 'Opening balance: 950.00'),
    ):
        lines = repo.get_case(workspace, case_id)['documents'][0]['lines']
        check('monitor_source_' + label.split()[0].lower(),
              any(line['id'] == source and line['text'] == label for line in lines))
    for revision, action in enumerate(('review', 'resolve')):
        saved = repo.review_monitor(workspace, actor, latest, entry['id'], action, revision)
    check('monitor_replay', saved['comparison'] == comparison and
          [event['action'] for event in saved['history']] == ['review', 'resolve'])
    check('monitor_audit_and_readiness', repo.audit(workspace)['verified'] and
          not any(repo.worker_status().values()))



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
            subprocess.run(
                [sys.executable, 'scripts/worker_entrypoint.py', '--once'],
                cwd=ROOT, env=env, check=True, timeout=120,
            )
            evaluation=repo.get_job('container-synthetic',untouched)
            check('queued_eval_completed',evaluation['state']=='completed' and evaluation['result']['summary']['failed']==0)
            check('one_shot_heartbeat_retired',not any(repo.worker_status().values()))

            derived=repo.get_case('container-synthetic',original['id'])
            check('versioned_review',derived['report_version']==2 and derived['status']=='review')
            check('fifty_candidate_difference',any(f.get('difference')=='50.00' and f['severity']=='review' for f in derived['findings']))
            check('zero_model_calls',derived['metrics']['attempted_model_calls']==0)
            check('original_pdf_unchanged',repo.get_document('container-synthetic',original['id'],'doc1')==raw)
            check('original_report_unchanged',repo.get_case('container-synthetic',original['id'],1)==original)
            check('audit_verified',repo.audit('container-synthetic')['verified'])
            check_monitoring(repo, env, check)
            scans=evaluate(ROOT/'data/ocr')
            check('four_actual_scan_cases',scans['passed'] and len(scans['cases'])==4)
        finally:
            if worker is not None and worker.poll() is None:
                worker.kill();worker.communicate(timeout=5)
            repo.close()
    report={'passed':True,'scope':'Offline Linux amd64 image, read-only root, non-root user, 1 CPU/1 GiB CI limit. Actual OCR, historical monitoring, encrypted SQLite versions and in-flight SIGTERM; not a hosted PostgreSQL or Vercel daemon proof.',
            'duration_seconds':round(time.monotonic()-started,2),'shutdown_seconds':shutdown_seconds,
            'cgroup_memory_peak_bytes':memory_peak(),'checks':checks,
            'ocr_cases':[{'case':row['case'],'checks':row['checks']} for row in scans['cases']],
            'model_sha256':scans['model_sha256']}
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
