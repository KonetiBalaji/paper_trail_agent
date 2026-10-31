"""Run real DOM handlers against owned disposable HTTP service and OCR worker.

No user browser, production database, private documents or provider key is used.
Requires Node 26, npm ci in tests/frontend, and requirements-ocr.txt.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import argparse
from datetime import datetime,timezone
import hashlib
import httpx
from cryptography.fernet import Fernet
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.repository import Repository
from app.security import Security

ROOT=Path(__file__).resolve().parents[1]


def stop(process):
    if process.poll() is None:
        if os.name=='nt':
            # A Windows virtualenv launcher can own a real Python child. Kill
            # only the tree rooted at this still-live Popen handle, never a
            # process selected by name, so test databases are released too.
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
        else:process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',default='work/frontend-ocr-results.json')
    args=parser.parse_args()
    if importlib.util.find_spec('rapidocr_onnxruntime') is None:raise SystemExit('Use the optional OCR Python environment.')
    node=shutil.which('node')
    if not node:raise SystemExit('Node 26 is required.')
    if not (ROOT/'tests/frontend/node_modules/jsdom').exists():raise SystemExit('Run npm ci --ignore-scripts in tests/frontend.')
    started=time.monotonic()
    test_root=(ROOT/'work/frontend-runs').resolve();test_root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='isolated-',dir=test_root) as temporary:
        folder=Path(temporary).resolve()
        if folder.parent!=test_root:raise RuntimeError('Test cleanup path is outside the owned workspace')
        key=Fernet.generate_key().decode();url='sqlite:///'+(folder/'cases.db').as_posix()
        repo=Repository(url,key);security=Security(repo,key)
        security.create_user('reviewer@example.invalid','synthetic-frontend-password-123','frontend-synthetic','reviewer')
        security.create_user('admin@example.invalid','synthetic-frontend-password-123','frontend-synthetic','admin')
        # An owned fictional old case makes real retention deletion testable
        # without exposing a test-only age-changing endpoint in the service.
        import io
        from fastapi import UploadFile
        from app.main import analyze_files
        from app.repository import cases
        from sqlalchemy import update
        old=analyze_files([UploadFile(filename=p.name,file=io.BytesIO(p.read_bytes())) for p in sorted((ROOT/'data/synthetic/math_error').glob('*.pdf'))],persist=False)
        repo.create_case('frontend-synthetic','fixture-seeder',old,[p.read_bytes() for p in sorted((ROOT/'data/synthetic/math_error').glob('*.pdf'))])
        with repo.transaction() as conn:conn.execute(update(cases).where(cases.c.id==old['id']).values(created_at='2000-01-01T00:00:00+00:00'))
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        env={**os.environ,'DATABASE_URL':url,'DATA_ENCRYPTION_KEY':key,'PAPER_TRAIL_MODE':'service',
             'MODEL_API_KEY':'','PAPER_TRAIL_UI_BASE':base,'PAPER_TRAIL_STORAGE':str(folder),'PAPER_TRAIL_UI_RETENTION_CASE':old['id']}
        env.pop('VERCEL',None);env.pop('TEST_DATABASE_URL',None)
        creation={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        with (folder/'server.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log,**creation)
            worker=None
            try:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    if server.poll() is not None:raise RuntimeError('Owned frontend test server failed to start')
                    try:
                        if httpx.get(base+'/api/health',timeout=1).status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                else:raise TimeoutError('Owned frontend test server was not ready')
                worker=subprocess.Popen([sys.executable,'-m','app.worker'],cwd=ROOT,env=env,stdout=log,stderr=log,**creation)
                deadline=time.monotonic()+20
                while not repo.worker_status()['ocr']:
                    if worker.poll() is not None:raise RuntimeError('Owned OCR worker exited before readiness')
                    if time.monotonic()>deadline:raise TimeoutError('Owned OCR worker was not ready')
                    time.sleep(.1)
                command=[node,'--test','tests/frontend/ocr-http.test.mjs']
                subprocess.run(command,cwd=ROOT,env={**env,'PAPER_TRAIL_UI_OFFLINE':'0'},check=True,timeout=150)
                stop(worker)
                # Process termination cannot retire its heartbeat; expire only
                # this disposable test database's leases, never production state.
                from app.repository import workers
                with repo.transaction() as conn:conn.execute(workers.delete())
                subprocess.run(command,cwd=ROOT,env={**env,'PAPER_TRAIL_UI_OFFLINE':'1'},check=True,timeout=45)
            finally:
                if worker is not None:stop(worker)
                stop(server);repo.close()
    source=['app/platform.py','app/main.py','app/policies.py','app/drafts.py','app/integrations.py','app/exports.py','app/security.py','app/repository.py','app/ocr_case.py','app/worker.py','app/static/app.js',
            'app/static/index.html','tests/frontend/ocr-http.test.mjs','scripts/test_frontend.py']
    report={'passed':True,'checked_at':datetime.now(timezone.utc).isoformat(),'duration_seconds':round(time.monotonic()-started,2),
            'scope':'Actual application DOM handlers and real loopback HTTP API with disposable SQLite, signed sessions and real CPU OCR. No browser layout/visual proof, hosted worker or paid model calls.',
            'scenarios':['reviewer login and upload','OCR queue and status','real OCR derived version','candidate amount/score display',
                         'provisional calculator label','source selection and highlighted PNG','version-guarded saved review',
                         'prior version export','audit verification','logout revocation','offline worker disables request',
                         'approved lender draft with exact calculator evidence','draft text selection','rejection removes draft',
                         'admin API key issue and revoke','bearer PDF submission and redacted read','CSV export','shown key cleared on logout',
                         'data notice','retention enable acknowledgement','expired case deletion and source removal','retention disable'],
            'source_sha256':{name:hashlib.sha256((ROOT/name).read_text(encoding='utf-8').encode()).hexdigest() for name in source}}
    output=Path(args.report);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
    print('Frontend-to-HTTP OCR scenarios passed; evidence saved to',output)


if __name__=='__main__':main()
