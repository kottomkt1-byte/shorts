"""Local-first API with durable ownership, immutable compositions and cancellable jobs."""
from __future__ import annotations
import asyncio, json, os, re, shutil, threading, uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from typing import Literal
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import Field
from . import store, providers, transfers
from .schema import Edit, Strict, SPECS, BY_ID, ROOT, SAFE_AREAS
from .compose import composition, checklist
from .media import inspect, run

MAX_FILE=int(os.environ.get('AUTO_SHORTS_MAX_UPLOAD_MB','500'))*1024*1024
MAX_REQUEST=1024*1024*1024
ALLOWED={'.mp4','.mov','.m4v','.webm'}

@asynccontextmanager
async def lifespan(app):
    store.init()
    sample=store.DATA/'sample.mp4'
    if not sample.exists():
        await asyncio.to_thread(run,['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=360x640:rate=30','-t','3','-c:v','libx264','-threads','2','-preset','ultrafast','-pix_fmt','yuv420p',sample])
    stop=threading.Event();thread=None
    if os.environ.get('AUTO_SHORTS_EMBEDDED_WORKER','1')=='1':
        from .worker import loop
        thread=threading.Thread(target=loop,args=(stop,),daemon=True);thread.start()
    yield
    stop.set()
    if thread:await asyncio.to_thread(thread.join,5)

app=FastAPI(title='Auto Shorts Studio',version='1.0.0',lifespan=lifespan)

class BodyLimit:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        count=0
        async def limited():
            nonlocal count
            message=await receive();count+=len(message.get('body',b''))
            if count>MAX_REQUEST:raise HTTPException(413,'요청당 최대 업로드는 1GB입니다. 파일을 나누어 올려주세요.')
            return message
        await self.app(scope,limited,send)
app.add_middleware(BodyLimit)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver',*filter(None,os.environ.get('AUTO_SHORTS_HOSTS','').split(','))])

@app.middleware('http')
async def identity(request,call_next):
    origin=request.headers.get('origin')
    transfer_request=request.url.path.startswith('/transfer/')
    transfer_origins=set(filter(None,os.environ.get('AUTO_SHORTS_ORIGINS','').split(',')))
    def transfer_error(detail,status):
        headers={'Cache-Control':'no-store'}
        if origin in transfer_origins:headers.update({'Access-Control-Allow-Origin':origin,'Vary':'Origin'})
        return JSONResponse({'detail':detail},status,headers=headers)
    if transfer_request:
        if origin and origin not in transfer_origins:
            return JSONResponse({'detail':'허용되지 않은 요청 출처입니다.'},403)
        if request.method=='OPTIONS':
            if not origin or request.headers.get('access-control-request-method') not in ('GET','POST','HEAD'):
                return JSONResponse({'detail':'허용되지 않은 파일 요청입니다.'},403)
            return JSONResponse({},headers={'Access-Control-Allow-Origin':origin,
                'Access-Control-Allow-Methods':'GET, HEAD, POST',
                'Access-Control-Allow-Headers':'Content-Type, Range',
                'Access-Control-Max-Age':'600','Vary':'Origin'})
        route=re.fullmatch(r'/transfer/(upload|media|job)/([a-zA-Z0-9-]+)',request.url.path)
        if not route:return transfer_error('파일 경로를 찾을 수 없습니다.',404)
        action,resource=route.groups()
        if request.method not in (('POST',) if action=='upload' else ('GET','HEAD')):
            return transfer_error('지원하지 않는 파일 요청입니다.',405)
        try:request.state.owner=transfers.verify(request.query_params.get('ticket',''),action,resource)
        except HTTPException as exc:return transfer_error(exc.detail,exc.status_code)
    if request.method not in ('GET','HEAD','OPTIONS'):
        allowed={f'http://{host}:{port}' for host in ('127.0.0.1','localhost') for port in ('5173','8787')}
        allowed.update(os.environ.get('AUTO_SHORTS_ORIGINS','').split(','))
        allowed.add(str(request.base_url).rstrip('/'))
        if origin and origin not in allowed:return JSONResponse({'detail':'허용되지 않은 요청 출처입니다.'},403)
        length=request.headers.get('content-length','0')
        if length.isdigit() and int(length)>MAX_REQUEST:return JSONResponse({'detail':'요청 크기 제한을 초과했습니다.'},413)
    if request.url.path.startswith('/api/'):
        # In authenticated deployments the administrator provisions account tokens.
        accounts=json.loads(os.environ.get('AUTO_SHORTS_ACCOUNTS','{}'))
        token=request.headers.get('authorization','').removeprefix('Bearer ') or request.cookies.get('shorts_account','')
        cookie=None
        if accounts:
            import secrets,hashlib
            matched=next((name for name,secret in accounts.items() if secrets.compare_digest(token,secret)),None)
            if not matched:return JSONResponse({'detail':'계정 인증이 필요합니다.'},401)
            owner=hashlib.sha256(matched.encode()).hexdigest()[:32]
            # Register configured accounts for TTL housekeeping.
            with store.transaction() as db:db.execute('INSERT OR IGNORE INTO users VALUES (?,?,?)',(owner,'configured:'+owner,__import__('time').time()))
        else:owner,cookie=store.account(request.cookies.get('shorts_session'))
        request.state.owner=owner
        response=await call_next(request)
        if accounts and request.headers.get('authorization'):
            response.set_cookie('shorts_account',token,httponly=True,samesite='strict',secure=os.environ.get('AUTO_SHORTS_SECURE_COOKIE')=='1',max_age=86400)
        if cookie:response.set_cookie('shorts_session',cookie,httponly=True,samesite='strict',secure=os.environ.get('AUTO_SHORTS_SECURE_COOKIE')=='1',max_age=365*86400)
        response.headers['Cache-Control']='no-store'
    else:response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    if transfer_request:
        response.headers['Cache-Control']='private, no-store'
        response.headers['Referrer-Policy']='no-referrer'
        if origin:
            response.headers['Access-Control-Allow-Origin']=origin
            response.headers['Access-Control-Expose-Headers']='Content-Disposition, Content-Length, Content-Range'
            response.headers['Vary']='Origin'
    return response

@app.exception_handler(ValueError)
async def bad_request(request,exc):return JSONResponse({'detail':str(exc)},400)

def owned_media(owner,ids,kind='video',ready=True):
    all_media={m['id']:m for m in store.media(owner)}
    selected=[]
    for mid in ids:
        m=all_media.get(mid)
        if not m or m['kind']!=kind:raise HTTPException(404,'파일을 찾을 수 없습니다.')
        if ready and not m.get('ready'):raise HTTPException(409,'파일 준비 작업이 완료되지 않았습니다.')
        selected.append(m)
    return selected

def owned_job(owner,jid):
    row=store.job(owner,jid)
    if not row:raise HTTPException(404,'작업을 찾을 수 없습니다.')
    return row

def public_job(row):
    result=json.loads(row['result']) if row.get('result') else None
    if result and 'plan' in result:
        result=json.loads(json.dumps(result));result['plan']['options'].pop('_music_path',None)
    if result and result.get('file') and transfers.origin():
        result['file']=transfers.file_url(row['owner'],'job',row['id'])
        result['download_url']=transfers.file_url(row['owner'],'job',row['id'],attachment=True)
    payload=json.loads(row['payload'])
    return {k:row[k] for k in ('id','kind','status','progress','message','created','attempts')} | {'result':result,'template_id':payload.get('plan',{}).get('spec',{}).get('id')}

def public_media(m,owner):
    url=None
    if m.get('ready'):
        url=transfers.file_url(owner,'media',m['id']) if transfers.origin() else f"/api/media/{m['id']}/file"
    return {k:v for k,v in m.items() if k not in ('path','proxy')} | {'url':url}

@app.get('/healthz')
def health():
    with store.connect() as db:db.execute('SELECT 1')
    return {'status':'ok'}

@app.get('/api/config')
def config(request:Request):
    return {'capabilities':providers.capabilities(),'safe_areas':SAFE_AREAS,'max_files':20,'max_file_bytes':MAX_FILE,
            'workspace':{'id':request.state.owner,'team_login':bool(json.loads(os.environ.get('AUTO_SHORTS_ACCOUNTS','{}')))},
            'storage':{'used':store.usage(request.state.owner),'limit':store.MAX_BYTES},
            'scan':'configured' if os.environ.get('AUTO_SHORTS_SCANNER') else 'not_configured',
            'retention_hours':store.TTL//3600}

@app.get('/api/checklist')
def platform_checklist(platform:str='youtube'):
    if platform not in SAFE_AREAS:raise HTTPException(400,'지원하지 않는 플랫폼입니다.')
    return checklist({'platform':platform})

@app.get('/api/templates')
def templates():return SPECS

@app.get('/api/media')
def list_media(request:Request):return [public_media(m,request.state.owner) for m in store.media(request.state.owner)]

class TransferRequest(Strict):
    kind:Literal['video','music']='video'

@app.post('/api/transfer')
def upload_url(payload:TransferRequest,request:Request):
    url=transfers.file_url(request.state.owner,'upload',payload.kind) if transfers.origin() else '/api/upload?kind='+payload.kind
    return {'url':url}

@app.post('/api/logout')
def logout():
    response=JSONResponse({'status':'logged_out'})
    for cookie in ('shorts_account','shorts_session'):
        response.delete_cookie(cookie,httponly=True,samesite='strict',secure=os.environ.get('AUTO_SHORTS_SECURE_COOKIE')=='1')
    return response

@app.post('/api/upload',status_code=201)
async def upload(request:Request,files:list[UploadFile]=File(...),kind:str='video'):
    if kind not in ('video','music'):raise HTTPException(400,'지원하지 않는 파일 종류입니다.')
    if not 1<=len(files)<=20:raise HTTPException(400,'파일은 1~20개 가능합니다.')
    owner=request.state.owner;folder=store.owner_dir(owner)/'media';folder.mkdir(exist_ok=True)
    created=[];added=[]
    try:
        for file in files:
            ext=Path(file.filename or '').suffix.lower()
            if ext not in (ALLOWED if kind=='video' else {'.wav','.mp3','.m4a','.aac','.ogg'}):raise HTTPException(400,'지원하지 않는 파일 형식입니다.')
            fid=uuid.uuid4().hex;dest=folder/(fid+ext);created.append(dest);size=0
            with dest.open('wb') as out:
                while chunk:=await file.read(1024*1024):
                    size+=len(chunk)
                    if size>MAX_FILE:raise HTTPException(413,'파일당 크기 제한을 초과했습니다.')
                    if store.usage(owner)+len(chunk)>store.MAX_BYTES:raise HTTPException(413,'계정 저장소 할당량을 초과했습니다.')
                    store.ensure_space(len(chunk))
                    out.write(chunk)
            try:metadata=await asyncio.to_thread(inspect,dest,kind)
            except Exception as exc:raise HTTPException(400,'읽을 수 없는 미디어입니다. 실제 영상/오디오 파일을 확인해주세요.') from exc
            info={'id':fid,'name':Path((file.filename or 'media').replace('\\','/')).name[:120],
                  'path':str(dest),'size':size,'ready':False,**metadata}
            added.append(info)
        # An invalid file rolls back the whole upload request before anything becomes visible.
        store.register_uploads(owner,kind,added)
        return {'files':[public_media(dict(m,kind=kind),owner) for m in added]}
    except BaseException:
        for path in created:path.unlink(missing_ok=True)
        with store.transaction() as db:
            for m in added:
                db.execute('DELETE FROM media WHERE id=? AND owner=?',(m['id'],owner))
                if m.get('job_id'):db.execute('DELETE FROM jobs WHERE id=? AND owner=?',(m['job_id'],owner))
        raise
    finally:
        for file in files:await file.close()

@app.get('/api/media/{mid}/file')
def media_file(mid:str,request:Request):
    matches=store.media(request.state.owner,mid)
    if not matches:raise HTTPException(404,'파일을 찾을 수 없습니다.')
    m=matches[0]
    if not m.get('ready'):raise HTTPException(409,'재생용 파일을 준비 중입니다.')
    p=Path(m.get('proxy') or m['path'])
    if not p.is_file():raise HTTPException(410,'파일이 만료되었습니다.')
    return FileResponse(p,media_type='video/mp4' if m['kind']=='video' else None)

@app.post('/transfer/upload/{kind}',status_code=201)
async def direct_upload(kind:str,request:Request,files:list[UploadFile]=File(...)):
    return await upload(request,files,kind)

@app.get('/transfer/media/{mid}')
def direct_media(mid:str,request:Request):
    return media_file(mid,request)

def prepare_plan(owner,payload,allow_sample=False):
    options=payload.model_dump()
    if options['template_id'] not in BY_ID:raise HTTPException(404,'템플릿을 찾을 수 없습니다.')
    media=owned_media(owner,options['clip_ids'])
    if not media:
        if not allow_sample:raise HTTPException(400,'영상 1개 이상을 선택해주세요.')
        media=[{'id':'sample','path':str(store.DATA/'sample.mp4'),'duration':3,'has_audio':False}]
    if options.get('music_id'):
        music=owned_media(owner,[options['music_id']],kind='music')[0];options['_music_path']=music['path']
    plan=composition(options,media)
    return plan,media

@app.post('/api/plan')
def plan(payload:Edit,request:Request):
    plan,_=prepare_plan(request.state.owner,payload,True)
    plan['options'].pop('_music_path',None)
    return {'plan':plan,'checklist':checklist(payload.model_dump())}

@app.post('/api/preview',status_code=202)
def preview(payload:Edit,request:Request):
    payload=payload.model_copy(update={'quality':'draft'})
    plan,media=prepare_plan(request.state.owner,payload,True)
    jid=store.enqueue(request.state.owner,'preview',{'plan':plan,'media':media})
    return {'id':jid,'status':'queued'}

@app.post('/api/render',status_code=202)
def render_one(payload:Edit,request:Request):
    plan,media=prepare_plan(request.state.owner,payload)
    jid=store.enqueue(request.state.owner,'render',{'plan':plan,'media':media})
    return {'id':jid,'status':'queued'}

@app.post('/api/batch',status_code=202)
def batch(payload:Edit,request:Request):
    # Preserve source/copy/brand choices; restore each template's own rhythm.
    plans=[]
    for spec in SPECS:
        options=payload.model_copy(update={'template_id':spec['id'],'scenes':[],'quality':'full','color':spec['color']})
        plan,media=prepare_plan(request.state.owner,options)
        plans.append({'plan':plan,'media':media})
    ids=store.enqueue_many(request.state.owner,[('render',p) for p in plans])
    return {'jobs':[{'id':jid} for jid in ids]}

@app.get('/api/jobs')
def jobs(request:Request):return [public_job(j) for j in store.jobs(request.state.owner)]

@app.get('/api/jobs/{jid}')
def job(jid:str,request:Request):return public_job(owned_job(request.state.owner,jid))

@app.post('/api/jobs/{jid}/cancel')
def cancel(jid:str,request:Request):
    row=owned_job(request.state.owner,jid)
    if row['status'] not in ('queued','running'):raise HTTPException(409,'이미 종료된 작업입니다.')
    with store.transaction() as db:db.execute('UPDATE jobs SET cancel=1 WHERE id=?',(jid,))
    return {'status':'cancellation_requested'}

@app.post('/api/jobs/{jid}/retry',status_code=202)
def retry(jid:str,request:Request):
    row=owned_job(request.state.owner,jid)
    if row['status'] not in ('failed','cancelled'):raise HTTPException(409,'실패/취소한 작업만 재시도할 수 있습니다.')
    new=store.enqueue(request.state.owner,row['kind'],json.loads(row['payload']))
    if row['kind']=='prepare':store.update_media(request.state.owner,json.loads(row['payload'])['media_id'],{'job_id':new})
    return {'id':new}

@app.get('/api/jobs/{jid}/file')
def download(jid:str,request:Request,attachment:bool=False):
    row=owned_job(request.state.owner,jid);result=json.loads(row['result'] or '{}')
    if row['status']!='done' or not result.get('validation',{}).get('passed'):raise HTTPException(409,'검증된 출력 파일이 없습니다.')
    path=store.owner_dir(request.state.owner)/'jobs'/jid/'output.mp4'
    if not path.is_file():raise HTTPException(410,'파일이 만료되었습니다.')
    return FileResponse(path,media_type='video/mp4',filename=f"{result['plan']['spec']['id']}-{jid[:8]}.mp4",content_disposition_type='attachment' if attachment else 'inline')

@app.get('/transfer/job/{jid}')
def direct_download(jid:str,request:Request,attachment:bool=False):
    return download(jid,request,attachment)

class Preset(Strict):
    name:str=Field(min_length=1,max_length=80)
    options:Edit

@app.post('/api/presets',status_code=201)
def save_preset(payload:Preset,request:Request):
    prepare_plan(request.state.owner,payload.options,True)
    pid=uuid.uuid4().hex
    with store.transaction() as db:db.execute('INSERT INTO presets VALUES (?,?,?,?,?)',(pid,request.state.owner,payload.name,payload.options.model_dump_json(),__import__('time').time()))
    return {'id':pid}

@app.get('/api/presets')
def presets(request:Request):
    with store.connect() as db:rows=db.execute('SELECT id,name,options FROM presets WHERE owner=? ORDER BY created DESC',(request.state.owner,)).fetchall()
    return [{'id':r['id'],'name':r['name'],'options':json.loads(r['options'])} for r in rows]

@app.post('/api/asr/{jid}',status_code=202)
def asr(jid:str,request:Request):
    if not providers.capabilities()['asr']:raise HTTPException(503,'ASR 미설정: 수동 자막을 사용하거나 로컬 모델을 설정하세요.')
    row=owned_job(request.state.owner,jid)
    if row['status']!='done' or row['kind'] not in ('preview','render'):raise HTTPException(409,'완성된 편집 영상을 먼저 선택해주세요.')
    # ASR uses the rendered audio, never guessed timing from original clips.
    new=store.enqueue(request.state.owner,'asr',{'render_job':jid});return {'id':new}

@app.post('/api/vision/{mid}',status_code=202)
def vision(mid:str,request:Request):
    if not providers.capabilities()['vision']:raise HTTPException(503,'Vision API 미설정: 규칙 기반 분석을 사용합니다.')
    owned_media(request.state.owner,[mid]);jid=store.enqueue(request.state.owner,'vision',{'media_id':mid});return {'id':jid}

app.mount('/covers',StaticFiles(directory=ROOT/'web/covers'),name='covers')
if (ROOT/'dist/assets').exists():app.mount('/assets',StaticFiles(directory=ROOT/'dist/assets'),name='assets')
@app.get('/')
def home():
    path=ROOT/'dist/index.html'
    if not path.exists():return JSONResponse({'message':'npm run dev를 실행하고 http://127.0.0.1:5173 에 접속하거나 npm run build 후 서버를 재시작하세요.'})
    return FileResponse(path)
