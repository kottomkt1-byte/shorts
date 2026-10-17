"""Local-first web app for reusable 9:16 templates.

Run: python -m uvicorn app.server:app --host 127.0.0.1 --port 8787
For internet deployment, add auth, rate limits, malware scanning, worker queue,
object storage, and per-account media permissions first.
"""
from __future__ import annotations
import json
from pathlib import Path
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .render import ROOT, duration, render
from .graphics import cover

ROOT=Path(__file__).resolve().parents[1]
MEDIA=ROOT/'uploads';OUT=ROOT/'outputs';WEB=ROOT/'web'
MEDIA.mkdir(exist_ok=True);OUT.mkdir(exist_ok=True)
SPECS=json.loads((ROOT/'templates.json').read_text(encoding='utf-8'))
BY_ID={t['id']:t for t in SPECS}
ALLOWED_EXT={'.mp4','.mov','.m4v','.webm','.mkv'}
MAX_UPLOAD=500*1024*1024
app=FastAPI(title='Auto Shorts Studio', version='0.1.0')
app.mount('/outputs',StaticFiles(directory=OUT),name='outputs')
app.mount('/covers',StaticFiles(directory=WEB/'covers'),name='covers')
jobs={};uploads={}; lock=Lock()
worker=ThreadPoolExecutor(max_workers=1)

class RenderRequest(BaseModel):
    template_id:str
    clip_ids:list[str] = Field(min_length=1,max_length=20)
    brand:str = Field(default='',max_length=80)
    hook:str = Field(default='',max_length=100)
    cta:str = Field(default='',max_length=100)
    captions:list[str] = Field(default_factory=list,max_length=12)
    quality:str = Field(default='draft',pattern='^(draft|full)$')
    music:bool = True

@app.get('/api/templates')
def templates():
    return SPECS

@app.post('/api/upload')
async def upload(files:list[UploadFile]=File(...)):
    if not 1<=len(files)<=20:raise HTTPException(400,'파일은 1~20개 가능합니다.')
    added=[]
    for file in files:
        ext=Path(file.filename or '').suffix.lower()
        if ext not in ALLOWED_EXT:raise HTTPException(400,f'지원하지 않는 형식입니다: {ext}')
        fid=uuid.uuid4().hex
        dest=MEDIA/f'{fid}{ext}'
        count=0
        try:
            with dest.open('wb') as out:
                while True:
                    chunk=await file.read(1024*1024)
                    if not chunk:break
                    count+=len(chunk)
                    if count>MAX_UPLOAD:raise HTTPException(413,'파일 하나당 최대 500MB입니다.')
                    out.write(chunk)
            sec=duration(dest)
        except Exception as exc:
            dest.unlink(missing_ok=True)
            if isinstance(exc,HTTPException):raise
            raise HTTPException(400,f'{file.filename}: 영상 파일을 읽지 못했습니다.') from exc
        finally:
            await file.close()
        info={'id':fid,'name':Path(file.filename or 'video').name[:120], 'size':count,'duration':round(sec,2),'path':str(dest)}
        with lock:uploads[fid]=info
        added.append({k:v for k,v in info.items() if k!='path'})
    return {'files':added}

def do_render(jid:str, spec:dict, media:list[dict], opts:dict):
    dest=OUT/f'{jid}.mp4'
    def progress(p:int,msg:str):
        with lock:jobs[jid].update(progress=p,message=msg)
    try:
        data=render(spec,media,opts,dest,progress)
        with lock:jobs[jid].update(status='done',file=f'/outputs/{jid}.mp4',**data)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        with lock:jobs[jid].update(status='failed',message=str(exc)[-500:])

@app.post('/api/render')
def start_render(payload:RenderRequest):
    spec=BY_ID.get(payload.template_id)
    if spec is None:raise HTTPException(404,'알 수 없는 템플릿입니다.')
    with lock:
        media=[uploads.get(clip_id) for clip_id in payload.clip_ids]
    if any(x is None for x in media):raise HTTPException(400,'영상 업로드부터 완료해주세요.')
    jid=uuid.uuid4().hex
    with lock:
        jobs[jid]={'id':jid,'status':'queued','progress':0,'message':'렌더링 대기 중','template_id':payload.template_id}
    worker.submit(do_render,jid,spec,media,payload.model_dump())
    return {'id':jid,'status':'queued'}

@app.get('/api/jobs/{job_id}')
def get_job(job_id:str):
    with lock:data=jobs.get(job_id)
    if not data:raise HTTPException(404,'작업을 찾을 수 없습니다.')
    return data

@app.get('/')
def home():
    return FileResponse(WEB/'index.html')

app.mount('/web',StaticFiles(directory=WEB),name='web')

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8787)
