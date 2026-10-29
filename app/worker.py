"""Durable leased worker. Run separately from the request process."""
import argparse
import time
from pathlib import Path
from .platform import runtime
from .evals import evaluate_suite

def run_once(repo):
    job=repo.claim_job(lease_seconds=120)
    if job is None:return False
    try:
        if job['kind']=='eval':
            result=evaluate_suite()
            failed=bool(result['summary']['failed'])
        else:
            # Pending handlers never masquerade as a completed OCR/ingest job.
            result={'error':'Handler not implemented; manual action required.'};failed=True
    except Exception:
        result={'error':'Job failed; inspect sanitized service diagnostics.'};failed=True
    # Never retry a completion whose database outcome could be unknown.
    repo.complete_job(job['id'],job['lease_token'],result,failed=failed)
    return True

def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--once',action='store_true')
    args=parser.parse_args();repo,_=runtime(Path(__file__).resolve().parents[1]/'storage')
    if args.once:run_once(repo);return
    while True:
        if not run_once(repo):time.sleep(1)

if __name__=='__main__':main()
