"""Opaque sessions, scrypt passwords and workspace-scoped service identities."""
import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from cryptography.fernet import InvalidToken
from dataclasses import dataclass
from sqlalchemy import select,and_,update,delete
from .repository import users,sessions,Missing

class Unauthorized(Exception):pass

@dataclass(frozen=True)
class Principal:
    id:str
    workspace:str
    role:str
    csrf_hash:str=''

def password_hash(password):
    if not 12<=len(password)<=128:raise ValueError('Use a password of 12 to 128 characters')
    salt=secrets.token_bytes(16)
    result=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
    return 'scrypt$'+base64.urlsafe_b64encode(salt+result).decode()

def password_matches(password,encoded):
    if not isinstance(password,str) or len(password)>128:return False
    try:
        raw=base64.urlsafe_b64decode(encoded.split('$',1)[1]);salt,digest=raw[:16],raw[16:]
        candidate=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
        return hmac.compare_digest(candidate,digest)
    except (ValueError,IndexError):return False

class Security:
    def __init__(self,repo,key):
        self.repo=repo
        self.index_key=hashlib.sha256((key.encode() if isinstance(key,str) else key)+b'identity-index').digest()
        self.dummy=password_hash('synthetic-dummy-password-no-account')

    def digest(self,value):return hmac.new(self.index_key,value.encode(),hashlib.sha256).hexdigest()

    def create_user(self,email,password,workspace,role,actor='bootstrap'):
        email=email.strip().lower()
        if not 3<=len(email)<=254 or '@' not in email or any(c.isspace() for c in email):raise ValueError('Invalid email')
        if role not in ('admin','reviewer','viewer'):raise ValueError('Invalid role')
        if not 1<=len(workspace)<=80:raise ValueError('Invalid workspace')
        encoded=password_hash(password);user_id=uuid.uuid4().hex
        self.repo.provision_workspace(workspace)
        with self.repo.transaction() as conn:
            if conn.execute(select(users.c.id).where(users.c.email_hash==self.digest(email))).first():raise ValueError('Account already exists')
            conn.execute(users.insert().values(id=user_id,email_hash=self.digest(email),email=self.repo.seal({'email':email}),
                password=encoded,workspace=workspace,role=role,disabled=0))
            self.repo._audit(conn,workspace,actor,'user_created',None,{'user_id':user_id,'role':role})
        return {'id':user_id,'workspace':workspace,'role':role}

    def login(self,email,password):
        with self.repo.engine.connect() as conn:
            row=conn.execute(select(users).where(users.c.email_hash==self.digest(email.strip().lower()))).mappings().first()
        valid=password_matches(password,row['password'] if row else self.dummy)
        if not row or not valid or row['disabled']:raise Unauthorized('Invalid credentials')
        return self.session(row['id'])

    def session(self,user_id,seconds=8*3600):
        token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
        with self.repo.transaction() as conn:
            conn.execute(sessions.insert().values(token_hash=self.digest(token),user_id=user_id,
                csrf_hash=self.digest(csrf),expires_at=time.time()+seconds))
        return token,csrf

    def authenticate(self,token):
        if token and token.startswith('demo.'):
            try:
                data=json.loads(self.repo.cipher.decrypt(token[5:].encode(),ttl=3600))
                if set(data)!={'id','csrf_hash'} or len(data['id'])!=32:raise ValueError()
                with self.repo.engine.connect() as conn:
                    row=conn.execute(select(sessions).where(sessions.c.token_hash==self.digest(token))).mappings().first()
                if not row or row['expires_at']<time.time() or row['csrf_hash']!=data['csrf_hash']:raise ValueError()
                return Principal('demo-'+data['id'],'demo-'+data['id'],'demo',data['csrf_hash'])
            except (InvalidToken,ValueError,TypeError,KeyError):raise Unauthorized('Demo expired; start a new synthetic session') from None
        if not token or len(token)>200:raise Unauthorized('Sign in required')
        with self.repo.engine.connect() as conn:
            row=conn.execute(select(users.c.id,users.c.workspace,users.c.role,users.c.disabled,sessions.c.csrf_hash,sessions.c.expires_at)
                .join(sessions,users.c.id==sessions.c.user_id).where(sessions.c.token_hash==self.digest(token))).mappings().first()
        if not row or row['disabled'] or row['expires_at']<time.time():raise Unauthorized('Sign in required')
        return Principal(row['id'],row['workspace'],row['role'],row['csrf_hash'])

    def demo_session(self):
        csrf=secrets.token_urlsafe(32)
        identifier=uuid.uuid4().hex
        token='demo.'+self.repo.cipher.encrypt(json.dumps({'id':identifier,'csrf_hash':self.digest(csrf)}).encode()).decode()
        with self.repo.transaction() as conn:
            conn.execute(sessions.insert().values(token_hash=self.digest(token),user_id=identifier,
                csrf_hash=self.digest(csrf),expires_at=time.time()+3600))
        return token,csrf

    def validate_csrf(self,principal,header,cookie):
        if not header or not cookie or not hmac.compare_digest(header,cookie) or not hmac.compare_digest(self.digest(header),principal.csrf_hash):
            raise Unauthorized('CSRF validation failed')

    def logout(self,token):
        with self.repo.transaction() as conn:conn.execute(delete(sessions).where(sessions.c.token_hash==self.digest(token or '')))

    def disable(self,workspace,actor,user_id):
        with self.repo.transaction() as conn:
            row=conn.execute(select(users).where(and_(users.c.id==user_id,users.c.workspace==workspace))).mappings().first()
            if not row:raise Missing('User not found')
            conn.execute(update(users).where(users.c.id==user_id).values(disabled=1))
            conn.execute(delete(sessions).where(sessions.c.user_id==user_id))
            self.repo._audit(conn,workspace,actor,'user_disabled',None,{'user_id':user_id})
