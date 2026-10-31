import threading
from app import worker


class RepositoryProbe:
    def __init__(self):self.events=[]
    def touch_worker(self,worker_id,kinds):self.events.append(('ready',worker_id,kinds))
    def retire_worker(self,worker_id):self.events.append(('retired',worker_id))


def test_stop_after_owned_job_never_claims_another(monkeypatch):
    repo=RepositoryProbe();stop=threading.Event();claims=[]
    def owned(*args,**kwargs):
        claims.append('completed-owned-job');stop.set();return True
    monkeypatch.setattr(worker,'run_once',owned)
    worker.serve(repo,['eval','ocr'],stop,poll_seconds=15)
    assert claims==['completed-owned-job']
    assert repo.events[0][0]=='ready' and repo.events[-1][0]=='retired'
    assert repo.events[0][1]==repo.events[-1][1]


def test_idle_wait_is_interruptible_and_not_a_busy_loop(monkeypatch):
    repo=RepositoryProbe();waits=[]
    class Stop:
        stopped=False
        def is_set(self):return self.stopped
        def wait(self,seconds):waits.append(seconds);self.stopped=True
    monkeypatch.setattr(worker,'run_once',lambda *args,**kwargs:False)
    worker.serve(repo,['ocr'],Stop(),poll_seconds=15)
    assert waits==[15] and len(repo.events)==2


def test_container_entrypoint_removes_model_access(monkeypatch):
    from scripts.worker_entrypoint import main
    import os
    monkeypatch.setenv('MODEL_API_KEY','synthetic-unused-key')
    monkeypatch.setenv('PAPER_TRAIL_MODE','local')
    observed=[]
    monkeypatch.setattr(worker,'main',lambda:observed.append((os.getenv('MODEL_API_KEY'),os.getenv('PAPER_TRAIL_MODE'))))
    main()
    assert observed==[('','service')]
