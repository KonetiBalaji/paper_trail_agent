"""Encrypted transactional case repository for SQLite or PostgreSQL.

No filesystem case state is assumed. Explicit workspace scoping is required on
every read/write. Original documents can be inserted or deleted, never replaced.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import secrets
import time
import uuid
from cryptography.fernet import Fernet
from sqlalchemy import (create_engine,MetaData,Table,Column,String,Integer,LargeBinary,
                        Float,Text,select,update,delete,and_,text)

class Conflict(Exception):pass
class Missing(Exception):pass
class LimitExceeded(Exception):pass

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
def utc():return datetime.now(timezone.utc).isoformat()

schema=MetaData()
cases=Table('cases',schema,
    Column('id',String(32),primary_key=True),Column('workspace',String(80),nullable=False,index=True),
    Column('created_at',String(40),nullable=False),Column('updated_at',String(40),nullable=False),
    Column('status',String(32),nullable=False),Column('version',Integer,nullable=False),
    Column('summary',LargeBinary,nullable=False),
    Column('report',LargeBinary,nullable=False),Column('synthetic',Integer,nullable=False,default=0))
documents=Table('documents',schema,
    Column('case_id',String(32),primary_key=True),Column('id',String(32),primary_key=True),
    Column('sha256',String(64),nullable=False),Column('original',LargeBinary,nullable=False))
versions=Table('report_versions',schema,
    Column('case_id',String(32),primary_key=True),Column('version',Integer,primary_key=True),
    Column('report',LargeBinary,nullable=False),Column('created_at',String(40),nullable=False))
audits=Table('audit_events',schema,
    Column('id',String(32),primary_key=True),Column('workspace',String(80),nullable=False,index=True),
    Column('sequence',Integer,nullable=False),Column('case_id',String(32)),Column('actor',String(80),nullable=False),
    Column('action',String(80),nullable=False),Column('created_at',String(40),nullable=False),
    Column('previous_hash',String(64),nullable=False),Column('event_hash',String(64),nullable=False),
    Column('payload',LargeBinary,nullable=False))
audit_heads=Table('audit_heads',schema,Column('workspace',String(80),primary_key=True),
    Column('sequence',Integer,nullable=False),Column('event_hash',String(64),nullable=False))
limits=Table('usage_limits',schema,Column('bucket',String(180),primary_key=True),
    Column('window_start',Integer,nullable=False),Column('count',Integer,nullable=False))
users=Table('users',schema,Column('id',String(32),primary_key=True),Column('email_hash',String(64),unique=True,nullable=False),
    Column('email',LargeBinary,nullable=False),Column('password',Text,nullable=False),
    Column('workspace',String(80),nullable=False),Column('role',String(20),nullable=False),
    Column('disabled',Integer,nullable=False,default=0))
sessions=Table('sessions',schema,Column('token_hash',String(64),primary_key=True),
    Column('user_id',String(32),nullable=False),Column('csrf_hash',String(64),nullable=False),Column('expires_at',Float,nullable=False))
jobs=Table('jobs',schema,Column('id',String(32),primary_key=True),Column('workspace',String(80),nullable=False,index=True),
    Column('kind',String(40),nullable=False),Column('state',String(20),nullable=False),
    Column('payload',LargeBinary,nullable=False),Column('result',LargeBinary),
    Column('attempts',Integer,nullable=False,default=0),Column('lease_until',Float,nullable=False,default=0),
    Column('lease_token',String(64)),Column('created_at',Float,nullable=False))
workers=Table('worker_leases',schema,Column('id',String(32),primary_key=True),
    Column('capabilities',String(80),nullable=False),Column('expires_at',Float,nullable=False))

class Repository:
    def __init__(self,url,key):
        self.cipher=Fernet(key.encode() if isinstance(key,str) else key)
        if url.startswith('postgres://'):url=url.replace('postgres://','postgresql+psycopg://',1)
        if url.startswith('postgresql://'):url=url.replace('postgresql://','postgresql+psycopg://',1)
        options={'pool_pre_ping':True,'hide_parameters':True}
        if url.startswith('sqlite'):options['connect_args']={'check_same_thread':False,'timeout':30}
        else:options.update(pool_size=3,max_overflow=2,pool_recycle=300)
        self.engine=create_engine(url,**options)
        schema.create_all(self.engine)

    @contextmanager
    def transaction(self):
        with self.engine.connect() as conn:
            try:
                if self.engine.dialect.name=='sqlite':conn.exec_driver_sql('BEGIN IMMEDIATE')
                else:conn.begin()
                yield conn
                conn.commit()
            except Exception:
                conn.rollback();raise

    def seal(self,value):return self.cipher.encrypt(canonical(value))
    def unseal(self,value):return json.loads(self.cipher.decrypt(value))
    def close(self):self.engine.dispose()

    def expire_demo_data(self,now=None):
        """Bounded maintenance: purge only expired synthetic guest workspaces."""
        now=time.time() if now is None else now
        cutoff=datetime.fromtimestamp(now-86400,timezone.utc).isoformat()
        with self.transaction() as conn:
            workspaces=conn.execute(select(cases.c.workspace).where(and_(cases.c.synthetic==1,
                cases.c.workspace.like('demo-%'),cases.c.created_at<cutoff)).distinct().limit(25)).scalars().all()
            for workspace in workspaces:
                ids=select(cases.c.id).where(and_(cases.c.workspace==workspace,cases.c.synthetic==1))
                conn.execute(delete(documents).where(documents.c.case_id.in_(ids)))
                conn.execute(delete(versions).where(versions.c.case_id.in_(ids)))
                conn.execute(delete(cases).where(and_(cases.c.workspace==workspace,cases.c.synthetic==1)))
                conn.execute(delete(audits).where(audits.c.workspace==workspace))
                conn.execute(delete(audit_heads).where(audit_heads.c.workspace==workspace))
            conn.execute(delete(sessions).where(sessions.c.expires_at<now))
            conn.execute(delete(limits).where(limits.c.window_start<int(now)-172800))
        return len(workspaces)

    def backup_sqlite(self,destination):
        if self.engine.dialect.name!='sqlite':raise ValueError('Use provider-managed PostgreSQL backups and test restoration separately')
        import sqlite3
        from pathlib import Path
        destination=Path(destination)
        if destination.exists():raise ValueError('Backup destination already exists')
        destination.parent.mkdir(parents=True,exist_ok=True)
        # SQLite's online backup API gives a consistent snapshot during writes.
        source=self.engine.raw_connection()
        try:
            with sqlite3.connect(str(destination)) as target:source.driver_connection.backup(target)
        finally:source.close()
        try:destination.chmod(0o600)
        except OSError:pass
        return destination

    def summary(self,report):
        statements=[d['statement'] for d in report['documents']]
        return {'identifiers':sorted({s['loan_id'] for s in statements if s.get('loan_id')}),
                'periods':sorted({s['period_end'] for s in statements if s.get('period_end')}),
                'review_decisions':sorted({f.get('human_review',{}).get('decision','pending') for f in report['findings']})}

    def _insert_once(self,conn,table,values):
        if self.engine.dialect.name=='postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        conn.execute(insert(table).values(**values).on_conflict_do_nothing())

    def _case(self,conn,workspace,case_id):
        row=conn.execute(select(cases).where(and_(cases.c.id==case_id,cases.c.workspace==workspace)).with_for_update()).mappings().first()
        if row is None:raise Missing('Case not found')
        return row

    def _audit(self,conn,workspace,actor,action,case_id,payload):
        # A unique workspace head serializes audit append operations across workers.
        # Workspaces are provisioned at account creation/case creation, before writes.
        head=conn.execute(select(audit_heads).where(audit_heads.c.workspace==workspace).with_for_update()).mappings().first()
        if head is None:
            conn.execute(audit_heads.insert().values(workspace=workspace,sequence=0,event_hash='0'*64))
            head={'sequence':0,'event_hash':'0'*64}
        event={'id':uuid.uuid4().hex,'workspace':workspace,'sequence':head['sequence']+1,
               'case_id':case_id,'actor':actor,'action':action,'created_at':utc(),
               'previous_hash':head['event_hash'],'payload':payload}
        digest=sha256(canonical(event)).hexdigest()
        conn.execute(audits.insert().values(**{k:v for k,v in event.items() if k!='payload'},
                                           payload=self.seal(payload),event_hash=digest))
        conn.execute(update(audit_heads).where(audit_heads.c.workspace==workspace).values(sequence=event['sequence'],event_hash=digest))

    def provision_workspace(self,workspace):
        # Called before accepting traffic for a workspace. Idempotent locally;
        # account provisioning on PostgreSQL must serialize workspace creation.
        with self.transaction() as conn:
            self._insert_once(conn,audit_heads,{'workspace':workspace,'sequence':0,'event_hash':'0'*64})

    def create_case(self,workspace,actor,report,blobs,synthetic=False):
        self.provision_workspace(workspace)
        if len(report['documents'])!=len(blobs):raise ValueError('Document count differs from original files')
        case_id=report['id'];now=utc();report['report_version']=1
        with self.transaction() as conn:
            if conn.execute(select(cases.c.id).where(cases.c.id==case_id)).first():raise Conflict('Case already exists')
            conn.execute(cases.insert().values(id=case_id,workspace=workspace,created_at=now,updated_at=now,
                status=report['status'],version=1,report=self.seal(report),summary=self.seal(self.summary(report)),synthetic=int(synthetic)))
            for doc,raw in zip(report['documents'],blobs):
                conn.execute(documents.insert().values(case_id=case_id,id=doc['id'],sha256=sha256(raw).hexdigest(),original=self.cipher.encrypt(raw)))
            conn.execute(versions.insert().values(case_id=case_id,version=1,report=self.seal(report),created_at=now))
            self._audit(conn,workspace,actor,'case_created',case_id,{'version':1,'documents':len(blobs),'synthetic':synthetic})
        return report

    def get_case(self,workspace,case_id,version=None):
        with self.engine.connect() as conn:
            row=self._case(conn,workspace,case_id)
            if version is not None:
                value=conn.execute(select(versions.c.report).where(and_(versions.c.case_id==case_id,versions.c.version==version))).scalar_one_or_none()
                if value is None:raise Missing('Report version not found')
            else:value=row['report']
            report=self.unseal(value)
            report['report_version']=row['version'] if version is None else version
            return report

    def get_document(self,workspace,case_id,doc_id):
        with self.engine.connect() as conn:
            self._case(conn,workspace,case_id)
            row=conn.execute(select(documents).where(and_(documents.c.case_id==case_id,documents.c.id==doc_id))).mappings().first()
            if row is None:raise Missing('Document not found')
            raw=self.cipher.decrypt(row['original'])
            if sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Original document integrity check failed')
            return raw

    def case_info(self,workspace,case_id):
        with self.engine.connect() as conn:
            row=self._case(conn,workspace,case_id)
            return {'version':row['version'],'synthetic':bool(row['synthetic']),'created_at':row['created_at']}

    def list_cases(self,workspace,query='',status=None,decision=None,limit=50,offset=0):
        if status and status not in ('consistent','discrepancies','review'):raise ValueError('Invalid case status')
        if decision and decision not in ('pending','confirmed','rejected'):raise ValueError('Invalid review decision')
        if not 1<=limit<=100 or not 0<=offset<=10000:raise ValueError('Invalid page bounds')
        with self.engine.connect() as conn:
            stmt=select(cases.c.id,cases.c.created_at,cases.c.updated_at,cases.c.version,cases.c.status,cases.c.synthetic,cases.c.summary)
            stmt=stmt.where(cases.c.workspace==workspace).order_by(cases.c.created_at.desc(),cases.c.id.desc())
            if status:stmt=stmt.where(cases.c.status==status)
            # Fetch a bounded workspace window; encrypted identifiers are never
            # indexed as plaintext. Report this bound to the UI, not exhaustive search.
            rows=conn.execute(stmt.limit(10001)).mappings().all()
            matches=[]
            for row in rows:
                summary=self.unseal(row['summary'])
                identifiers=summary['identifiers'];periods=summary['periods'];decisions=summary['review_decisions']
                if decision and decision not in decisions:continue
                if query.lower() not in (' '.join(identifiers+periods+[row['id']])).lower():continue
                matches.append({'id':row['id'],'created_at':row['created_at'],'updated_at':row['updated_at'],
                    'version':row['version'],'status':row['status'],'identifiers':identifiers,'periods':periods,
                    'review_decisions':sorted(decisions),'synthetic':bool(row['synthetic'])})
            return {'cases':matches[offset:offset+limit],'total_in_window':len(matches),'window_limit':10000,'truncated':len(rows)>10000}

    def review(self,workspace,actor,case_id,finding_id,action,note,expected_revision,expected_case_version=None):
        if action not in ('confirm','reject','note') or len(note)>2000 or (action=='note' and not note.strip()):raise ValueError('Invalid review')
        with self.transaction() as conn:
            row=self._case(conn,workspace,case_id);report=self.unseal(row['report'])
            if expected_case_version is not None and row['version']!=expected_case_version:
                raise Conflict('Report changed; reopen the latest case before reviewing')
            if report.get('derived_from') and expected_case_version is None:
                raise Conflict('Report version is required for derived findings; reopen the case')
            finding=next((f for f in report['findings'] if f['id']==finding_id),None)
            if finding is None:raise Missing('Finding not found')
            review=finding.setdefault('human_review',{'decision':'pending','revision':0,'history':[]})
            if review['revision']!=expected_revision:raise Conflict('Review changed; reload before saving')
            event={'action':action,'note':note.strip(),'timestamp':utc(),'revision':review['revision']+1,'actor':actor}
            if action!='note':review['decision']={'confirm':'confirmed','reject':'rejected'}[action]
            review['revision']+=1;review['history'].append(event)
            from .trace import record
            record(report.setdefault('trace',[]),'human_review',action,
                {'finding_id':finding_id,'note':note.strip()},{'decision':review['decision'],'revision':review['revision']},finding_ids=[finding_id],actor=actor)
            version=row['version']+1;now=utc();report['report_version']=version
            conn.execute(update(cases).where(cases.c.id==case_id).values(report=self.seal(report),summary=self.seal(self.summary(report)),version=version,updated_at=now))
            conn.execute(versions.insert().values(case_id=case_id,version=version,created_at=now,report=self.seal(report)))
            self._audit(conn,workspace,actor,'finding_reviewed',case_id,{'finding_id':finding_id,'action':action,'version':version,'revision':review['revision']})
            return report

    def audit(self,workspace,case_id=None):
        with self.transaction() as conn:
            head=conn.execute(select(audit_heads).where(audit_heads.c.workspace==workspace).with_for_update()).mappings().first()
            rows=conn.execute(select(audits).where(audits.c.workspace==workspace).order_by(audits.c.sequence)).mappings().all()
            previous='0'*64;sequence=0;events=[]
            for row in rows:
                event={k:row[k] for k in ('id','workspace','sequence','case_id','actor','action','created_at','previous_hash')}
                event['payload']=self.unseal(row['payload'])
                if event['sequence']!=sequence+1 or event['previous_hash']!=previous or sha256(canonical(event)).hexdigest()!=row['event_hash']:
                    raise ValueError('Audit integrity check failed')
                sequence+=1;previous=row['event_hash']
                if case_id is None or event['case_id']==case_id:events.append({**event,'event_hash':previous})
            if head and (head['sequence']!=sequence or head['event_hash']!=previous):raise ValueError('Audit head mismatch')
            return {'verified':True,'events':events}

    def delete_case(self,workspace,actor,case_id):
        with self.transaction() as conn:
            self._case(conn,workspace,case_id)
            conn.execute(delete(documents).where(documents.c.case_id==case_id))
            conn.execute(delete(versions).where(versions.c.case_id==case_id))
            conn.execute(delete(cases).where(cases.c.id==case_id))
            self._audit(conn,workspace,actor,'case_deleted',case_id,{'originals_and_versions_deleted':True})

    def consume(self,bucket,limit,seconds,now=None):
        if not 1<=limit<=100000 or seconds<1:raise ValueError('Invalid usage policy')
        now=int(time.time() if now is None else now);window=now//seconds*seconds
        with self.transaction() as conn:
            self._insert_once(conn,limits,{'bucket':bucket,'window_start':window,'count':0})
            row=conn.execute(select(limits).where(limits.c.bucket==bucket).with_for_update()).mappings().first()
            count=row['count'] if row['window_start']==window else 0
            if count>=limit:raise LimitExceeded('Usage limit reached')
            conn.execute(update(limits).where(limits.c.bucket==bucket).values(window_start=window,count=count+1))
            return count+1

    def enqueue(self,workspace,actor,kind,payload):
        if kind not in ('ocr','eval','ingest','monitor'):raise ValueError('Unsupported job kind')
        self.provision_workspace(workspace);job_id=uuid.uuid4().hex
        with self.transaction() as conn:
            conn.execute(jobs.insert().values(id=job_id,workspace=workspace,kind=kind,state='queued',payload=self.seal(payload),
                attempts=0,lease_until=0,created_at=time.time()))
            self._audit(conn,workspace,actor,'job_queued',None,{'job_id':job_id,'kind':kind})
        return job_id

    def claim_job(self,lease_seconds=60,now=None,kinds=None):
        now=time.time() if now is None else now
        with self.transaction() as conn:
            query=select(jobs).where((jobs.c.state=='queued')|((jobs.c.state=='running')&(jobs.c.lease_until<now)))
            if kinds is not None:
                if not kinds:return None
                if any(kind not in ('eval','ocr','ingest','monitor') for kind in kinds):raise ValueError('Invalid worker capability')
                query=query.where(jobs.c.kind.in_(kinds))
            query=query.order_by(jobs.c.created_at).limit(1).with_for_update(skip_locked=True)
            row=conn.execute(query).mappings().first()
            if not row:return None
            token=secrets.token_hex(32)
            conn.execute(update(jobs).where(jobs.c.id==row['id']).values(state='running',lease_until=now+lease_seconds,lease_token=token,attempts=row['attempts']+1))
            return {'id':row['id'],'workspace':row['workspace'],'kind':row['kind'],'payload':self.unseal(row['payload']),
                    'lease_token':token,'attempt':row['attempts']+1}

    def complete_job(self,job_id,lease_token,result,failed=False):
        with self.transaction() as conn:
            row=conn.execute(select(jobs).where(jobs.c.id==job_id).with_for_update()).mappings().first()
            if not row or row['state']!='running' or row['lease_token']!=lease_token or row['lease_until']<time.time():
                raise Conflict('Job lease lost')
            conn.execute(update(jobs).where(jobs.c.id==job_id).values(state='failed' if failed else 'completed',result=self.seal(result),lease_until=0,lease_token=None))

    def get_job(self,workspace,job_id):
        with self.engine.connect() as conn:
            row=conn.execute(select(jobs).where(and_(jobs.c.id==job_id,jobs.c.workspace==workspace))).mappings().first()
            if not row:raise Missing('Job not found')
            return {'id':row['id'],'kind':row['kind'],'state':row['state'],'attempts':row['attempts'],
                    'result':self.unseal(row['result']) if row['result'] else None}

    def touch_worker(self,worker_id,capabilities,ttl=90,now=None):
        if len(worker_id)!=32 or not 1<=ttl<=120 or not capabilities or set(capabilities)-{'eval','ocr'}:
            raise ValueError('Invalid worker heartbeat')
        expires=(time.time() if now is None else now)+ttl
        with self.transaction() as conn:
            self._insert_once(conn,workers,{'id':worker_id,'capabilities':','.join(sorted(set(capabilities))),'expires_at':expires})
            conn.execute(update(workers).where(workers.c.id==worker_id).values(capabilities=','.join(sorted(set(capabilities))),expires_at=expires))
            conn.execute(delete(workers).where(workers.c.expires_at<expires-86400))

    def worker_status(self,now=None):
        with self.engine.connect() as conn:
            active=conn.execute(select(workers.c.capabilities).where(workers.c.expires_at>(time.time() if now is None else now))).scalars().all()
        return {kind:any(kind in value.split(',') for value in active) for kind in ('eval','ocr')}

    def retire_worker(self,worker_id):
        with self.transaction() as conn:conn.execute(delete(workers).where(workers.c.id==worker_id))

    def _ocr_jobs(self,conn,workspace,case_id):
        # Payloads remain encrypted. Workspace job quotas bound the active queue;
        # historical discovery is explicitly limited to the newest 100 jobs.
        rows=conn.execute(select(jobs).where(and_(jobs.c.workspace==workspace,jobs.c.kind=='ocr'))
                          .order_by(jobs.c.created_at.desc()).limit(100)).mappings().all()
        return [row for row in rows if self.unseal(row['payload']).get('case_id')==case_id]

    def ocr_info(self,workspace,case_id):
        with self.engine.connect() as conn:
            row=self._case(conn,workspace,case_id)
            related=self._ocr_jobs(conn,workspace,case_id)
            job=related[0] if related else None
            return {'version':row['version'],'latest_job':None if not job else {
                'id':job['id'],'kind':'ocr','state':job['state'],'attempts':job['attempts'],
                'result':self.unseal(job['result']) if job['result'] else None},'job_history_window':100}

    def enqueue_ocr(self,workspace,actor,case_id,expected_version):
        with self.transaction() as conn:
            row=self._case(conn,workspace,case_id)
            if row['version']!=expected_version:raise Conflict('Report changed; reopen before requesting OCR')
            report=self.unseal(row['report'])
            pages=sum(len({i['page'] for i in d.get('issues',[]) if i['type']=='ocr_required'}) for d in report['documents'])
            if not 1<=pages<=5:raise ValueError('OCR requires 1 to 5 image-only pages across the case')
            for job in self._ocr_jobs(conn,workspace,case_id):
                if job['state'] in ('queued','running'):
                    return {'job_id':job['id'],'state':job['state'],'reused':True}
            job_id=uuid.uuid4().hex
            payload={'case_id':case_id,'expected_version':expected_version,'requested_by':actor}
            conn.execute(jobs.insert().values(id=job_id,workspace=workspace,kind='ocr',state='queued',
                payload=self.seal(payload),attempts=0,lease_until=0,created_at=time.time()))
            self._audit(conn,workspace,actor,'ocr_queued',case_id,{'job_id':job_id,'version':expected_version,'pages':pages})
            return {'job_id':job_id,'state':'queued','reused':False}

    def complete_ocr(self,job_id,lease_token,report):
        """Commit a derived report and job outcome together; never overwrite reviews."""
        with self.transaction() as conn:
            job=conn.execute(select(jobs).where(jobs.c.id==job_id).with_for_update()).mappings().first()
            if not job or job['kind']!='ocr' or job['state']!='running' or job['lease_token']!=lease_token or job['lease_until']<time.time():
                raise Conflict('Job lease lost')
            payload=self.unseal(job['payload']);workspace=job['workspace'];case_id=payload['case_id']
            try:row=self._case(conn,workspace,case_id)
            except Missing:row=None
            if row is None or row['version']!=payload['expected_version']:
                result={'case_id':case_id,'error':'Case deleted or changed during OCR; no derived report saved. Reopen before requesting again.'}
                conn.execute(update(jobs).where(jobs.c.id==job_id).values(state='failed',result=self.seal(result),lease_until=0,lease_token=None))
                self._audit(conn,workspace,payload['requested_by'],'ocr_discarded',case_id,{'job_id':job_id,'reason':'case_changed'})
                return result
            original=self.unseal(row['report'])
            if (report['id']!=case_id or report['status']!='review'
                    or [(d['id'],d['name']) for d in report['documents']]!=[(d['id'],d['name']) for d in original['documents']]
                    or report.get('derived_from')!={'version':row['version'],'job_id':job_id,'kind':'ocr'}):
                raise ValueError('Invalid OCR report identity or lineage')
            ocr_sources={line['id'] for d in report['documents'] for line in d['lines'] if line.get('method')=='ocr'}
            if not any(d.get('ocr',{}).get('performed') for d in report['documents']):raise ValueError('No OCR evidence')
            if any(f['severity']=='confirmed' and ocr_sources.intersection(f['sources']) for f in report['findings']):
                raise ValueError('OCR candidates cannot be machine-confirmed')
            version=row['version']+1;now=utc();report['report_version']=version
            conn.execute(update(cases).where(cases.c.id==case_id).values(status='review',report=self.seal(report),
                summary=self.seal(self.summary(report)),version=version,updated_at=now))
            conn.execute(versions.insert().values(case_id=case_id,version=version,report=self.seal(report),created_at=now))
            result={'case_id':case_id,'report_version':version,'review_required':True}
            self._audit(conn,workspace,payload['requested_by'],'ocr_completed',case_id,{'job_id':job_id,'version':version})
            conn.execute(update(jobs).where(jobs.c.id==job_id).values(state='completed',result=self.seal(result),lease_until=0,lease_token=None))
            return result
