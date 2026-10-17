"""SQLite durable queue and per-session/account storage; no public upload paths."""
import contextlib, hashlib, json, os, secrets, shutil, sqlite3, time, uuid
from pathlib import Path

DATA=Path(os.environ.get('AUTO_SHORTS_DATA',Path(__file__).resolve().parents[1]/'data')).resolve()
MAX_BYTES=int(os.environ.get('AUTO_SHORTS_QUOTA_MB','10240'))*1024*1024
TTL=int(os.environ.get('AUTO_SHORTS_TTL_HOURS','72'))*3600
LEASE=90

def connect():
    DATA.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA/'studio.sqlite',timeout=30);db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA busy_timeout=30000')
    return db

@contextlib.contextmanager
def transaction():
    db=connect()
    try:
        db.execute('BEGIN IMMEDIATE');yield db;db.commit()
    except BaseException:db.rollback();raise
    finally:db.close()

def init():
    with transaction() as d:
        d.executescript('''CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, token TEXT UNIQUE, created REAL);
CREATE TABLE IF NOT EXISTS media (id TEXT PRIMARY KEY, owner TEXT, kind TEXT, info TEXT, created REAL);
CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT, kind TEXT, payload TEXT, status TEXT, progress INTEGER DEFAULT 0, message TEXT, result TEXT, created REAL, updated REAL, lease REAL DEFAULT 0, worker TEXT, cancel INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS presets (id TEXT PRIMARY KEY, owner TEXT, name TEXT, options TEXT, created REAL);
CREATE INDEX IF NOT EXISTS job_status ON jobs(status,created);
CREATE INDEX IF NOT EXISTS media_owner ON media(owner);''')

def account(token=None):
    digest=hashlib.sha256(token.encode()).hexdigest() if token else ''
    with transaction() as d:
        u=d.execute('SELECT id FROM users WHERE token=?',(digest,)).fetchone()
        if u:return u['id'],None
        token=secrets.token_urlsafe(32);uid=uuid.uuid4().hex
        d.execute('INSERT INTO users VALUES (?,?,?)',(uid,hashlib.sha256(token.encode()).hexdigest(),time.time()))
        return uid,token

def owner_dir(owner):
    if not owner.isalnum():raise ValueError('invalid owner')
    p=DATA/'accounts'/owner;p.mkdir(parents=True,exist_ok=True);return p

def usage(owner):return sum(p.stat().st_size for p in owner_dir(owner).rglob('*') if p.is_file())

def ensure_space(additional=0):
    reserve=int(os.environ.get('AUTO_SHORTS_MIN_FREE_MB','0'))*1024*1024
    if reserve and shutil.disk_usage(DATA).free < reserve+additional:
        raise ValueError('서버 저장 공간이 부족합니다. 보관 기간이 지난 파일이 정리된 후 다시 시도해주세요.')

def add_media(owner,kind,info):
    with transaction() as d:d.execute('INSERT INTO media VALUES (?,?,?,?,?)',(info['id'],owner,kind,json.dumps(info),time.time()))

def media(owner,mid=None):
    with connect() as d:
        rows=d.execute('SELECT * FROM media WHERE owner=?'+(' AND id=?' if mid else ''),(owner,mid) if mid else (owner,)).fetchall()
    return [dict(json.loads(r['info']),kind=r['kind']) for r in rows]

def update_media(owner,mid,changes):
    with transaction() as d:
        r=d.execute('SELECT info FROM media WHERE id=? AND owner=?',(mid,owner)).fetchone()
        if not r:raise ValueError('원본 파일이 만료되었습니다.')
        info=json.loads(r['info']);info.update(changes)
        d.execute('UPDATE media SET info=? WHERE id=?',(json.dumps(info),mid))

def _insert_jobs(db,owner,items):
    ensure_space(len(items)*40*1024*1024)
    queued=db.execute("SELECT count(*) FROM jobs WHERE owner=? AND status IN ('queued','running')",(owner,)).fetchone()[0]
    if queued+len(items)>32:raise ValueError('계정당 동시 대기 작업은 32개까지입니다.')
    if usage(owner)+(queued+len(items))*40*1024*1024>MAX_BYTES:raise ValueError('저장소 할당량을 초과했습니다.')
    ids=[];now=time.time()
    for kind,payload in items:
        jid=uuid.uuid4().hex;ids.append(jid)
        db.execute('INSERT INTO jobs (id,owner,kind,payload,status,message,created,updated) VALUES (?,?,?,?,?,?,?,?)',
                   (jid,owner,kind,json.dumps(payload),'queued','작업 대기 중',now,now))
    return ids

def enqueue_many(owner,items):
    with transaction() as db:return _insert_jobs(db,owner,items)

def enqueue(owner,kind,payload):return enqueue_many(owner,[(kind,payload)])[0]

def register_uploads(owner,kind,items):
    with transaction() as db:
        ids=_insert_jobs(db,owner,[('prepare',{'media_id':m['id']}) for m in items])
        for info,jid in zip(items,ids):
            info['job_id']=jid
            db.execute('INSERT INTO media VALUES (?,?,?,?,?)',(info['id'],owner,kind,json.dumps(info),time.time()))
    return ids

def job(owner,jid):
    with connect() as d:r=d.execute('SELECT * FROM jobs WHERE id=? AND owner=?',(jid,owner)).fetchone()
    return dict(r) if r else None

def jobs(owner):
    with connect() as d:return [dict(r) for r in d.execute('SELECT * FROM jobs WHERE owner=? ORDER BY created DESC LIMIT 60',(owner,))]

def claim(worker):
    with transaction() as d:
        now=time.time()
        d.execute("UPDATE jobs SET status='cancelled', message='취소됨', updated=? WHERE status='queued' AND cancel=1",(now,))
        d.execute("UPDATE jobs SET status=CASE WHEN cancel=1 THEN 'cancelled' WHEN attempts>=3 THEN 'failed' ELSE 'queued' END, message='중단된 작업 복구', worker=NULL, updated=? WHERE status='running' AND lease<?",(now,now))
        running=d.execute("SELECT count(*) FROM jobs WHERE status='running'").fetchone()[0]
        if running>=int(os.environ.get('AUTO_SHORTS_CONCURRENCY','1')):return None
        row=d.execute("SELECT * FROM jobs WHERE status='queued'  AND cancel=0 ORDER BY created LIMIT 1").fetchone()
        if not row:return None
        d.execute("UPDATE jobs SET status='running',worker=?,lease=?,attempts=attempts+1,updated=? WHERE id=?",(worker,now+LEASE,now,row['id']))
        return dict(row,worker=worker)

def heartbeat(jid,worker):
    with transaction() as d:
        row=d.execute('SELECT cancel,status,worker FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row or row['worker']!=worker:return True
        d.execute('UPDATE jobs SET lease=? WHERE id=?',(time.time()+LEASE,jid))
        return bool(row['cancel'])

def progress(jid,worker,p,msg):
    with transaction() as d:d.execute('UPDATE jobs SET progress=?,message=?,updated=? WHERE id=? AND worker=?',(p,msg,time.time(),jid,worker))

def finish(jid,worker,status,message,result=None,artifact=None,media_update=None):
    with transaction() as d:
        row=d.execute('SELECT worker,cancel,owner FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row or row['worker']!=worker or (status=='done' and row['cancel']):return False
        if artifact:
            source,target=artifact
            os.replace(source,target)
        if media_update:
            mid,changes=media_update
            r=d.execute('SELECT info FROM media WHERE id=? AND owner=?',(mid,row['owner'])).fetchone()
            if not r:raise ValueError('원본이 만료되었습니다.')
            info=json.loads(r['info']);info.update(changes)
            d.execute('UPDATE media SET info=? WHERE id=?',(json.dumps(info),mid))
        d.execute("UPDATE jobs SET status=?,message=?,result=?,updated=?,progress=CASE WHEN ?='done' THEN 100 ELSE progress END WHERE id=? AND worker=?",
                  (status,message,json.dumps(result) if result is not None else None,time.time(),status,jid,worker))
        return True

def cleanup():
    now=time.time()
    with transaction() as d:
        active={r[0] for r in d.execute("SELECT DISTINCT owner FROM jobs WHERE status IN ('queued','running')")}
        owners=[r[0] for r in d.execute('SELECT id FROM users')]
        for owner in owners:
            if owner in active:continue
            for row in d.execute('SELECT id FROM jobs WHERE owner=? AND updated<?',(owner,now-TTL)).fetchall():
                path=owner_dir(owner)/'jobs'/row['id'];shutil.rmtree(path,ignore_errors=True)
                d.execute('DELETE FROM jobs WHERE id=?',(row['id'],))
            for row in d.execute('SELECT id,info FROM media WHERE owner=? AND created<?',(owner,now-TTL)).fetchall():
                info=json.loads(row['info']);Path(info['path']).unlink(missing_ok=True)
                if info.get('proxy'):Path(info['proxy']).unlink(missing_ok=True)
                d.execute('DELETE FROM media WHERE id=?',(row['id'],))

            # Remove abandoned temporary artifacts only when this account has no active jobs.
            known={r[0] for r in d.execute('SELECT id FROM jobs WHERE owner=?',(owner,))}
            for path in (owner_dir(owner)/'jobs').glob('*'):
                if path.is_dir() and path.name not in known and path.stat().st_mtime<now-TTL:shutil.rmtree(path,ignore_errors=True)
                elif path.is_dir():
                    for attempt in path.glob('attempt-*'):shutil.rmtree(attempt,ignore_errors=True)
            known_files={json.loads(r[0])['path'] for r in d.execute('SELECT info FROM media WHERE owner=?',(owner,))}
            known_files.update(json.loads(r[0]).get('proxy','') for r in d.execute('SELECT info FROM media WHERE owner=?',(owner,)))
            for path in (owner_dir(owner)/'media').glob('*'):
                if path.is_file() and str(path) not in known_files and path.stat().st_mtime<now-TTL:path.unlink(missing_ok=True)
