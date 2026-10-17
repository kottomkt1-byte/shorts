"""Run embedded (default) or separately: AUTO_SHORTS_EMBEDDED_WORKER=0 npm start; npm run worker."""
import json, os, shutil, subprocess, threading, time, uuid
from pathlib import Path
from . import store, providers
from .media import STATE, Cancelled, inspect, proxy, analyze, run
from .render import render


def process(row,stop=None):
    jid=row['id'];owner=row['owner'];wid=row['worker'];payload=json.loads(row['payload'])
    job_dir=store.owner_dir(owner)/'jobs'/jid;job_dir.mkdir(parents=True,exist_ok=True)
    work=job_dir/('attempt-'+uuid.uuid4().hex);work.mkdir()
    artifact=None;media_update=None
    last=[0,False]
    def cancelled():
        if stop and stop.is_set():return True
        if time.monotonic()-last[0]>.5:
            store.ensure_space()
            last[:]=[time.monotonic(),store.heartbeat(jid,wid)]
        return last[1]
    STATE.cancel=cancelled
    def progress(p,msg):
        if cancelled():raise Cancelled()
        if store.usage(owner)>store.MAX_BYTES:raise ValueError('저장소 할당량을 초과했습니다.')
        store.progress(jid,wid,p,msg)
    # Providers may be blocked in network/model work; keep the durable lease alive.
    heartbeat_stop=threading.Event()
    def keepalive():
        while not heartbeat_stop.wait(10):store.heartbeat(jid,wid)
    heartbeat=threading.Thread(target=keepalive,daemon=True);heartbeat.start()
    try:
        kind=row['kind']
        if kind=='prepare':
            m=store.media(owner,payload['media_id'])[0]
            src=Path(m['path'])
            scanner=os.environ.get('AUTO_SHORTS_SCANNER')
            if scanner:
                result=subprocess.run([scanner,str(src)],capture_output=True,timeout=120)
                if result.returncode:raise ValueError('파일 보안 검사에 실패했습니다.')
            elif os.environ.get('AUTO_SHORTS_REQUIRE_SCAN')=='1':raise ValueError('필수 바이러스 검사기가 설정되지 않았습니다.')
            progress(5,'파일 형식 검사 완료')
            if m['kind']=='music':result={'ready':True,'scan':'passed' if scanner else 'not_configured'}
            else:
                dest=work/'proxy.mp4'
                proxy(src,dest,m['duration'],lambda f:progress(round(5+65*f),'브라우저 재생용 프록시 변환'))
                progress(72,'프레임 품질 및 동작 후보 분석')
                analysis=analyze(src,m)
                artifact=(dest,src.with_suffix('.proxy.mp4'))
                result={'ready':True,'proxy':str(artifact[1]),'analysis':analysis,'scan':'passed' if scanner else 'not_configured'}
            media_update=(m['id'],result)
            result={'media_id':m['id']}
        elif kind in ('render','preview'):
            plan=payload['plan'];media=payload['media']
            result=render(plan['spec'],media,plan['options'],work/'output.mp4',progress,plan=plan)
            if store.usage(owner)>store.MAX_BYTES:raise ValueError('출력 저장소 할당량을 초과했습니다.')
            result['file']=f'/api/jobs/{jid}/file'
            artifact=(work/'output.mp4',job_dir/'output.mp4')
        elif kind=='asr':
            # Transcribe the actual edited audio so word times match the output timeline.
            m=store.job(owner,payload['render_job']);path=store.owner_dir(owner)/'jobs'/m['id']/'output.mp4'
            progress(10,'편집 영상의 음성 인식 실행 중')
            result=providers.transcribe(path)
            result['source_job']=payload['render_job']
        elif kind=='vision':
            m=store.media(owner,payload['media_id'])[0];progress(10,'3개 프레임 분석 중')
            result=providers.vision(Path(m['path']),m['duration']);media_update=(m['id'],{'vision':result})
        else:raise ValueError('지원하지 않는 작업입니다.')
        if cancelled():raise Cancelled()
        if not store.finish(jid,wid,'done','작업 완료',result,artifact,media_update):raise Cancelled()
    except Cancelled:
        (work/'output.mp4').unlink(missing_ok=True)
        store.finish(jid,wid,'cancelled','작업이 취소되었습니다.')
    except Exception as exc:
        (work/'output.mp4').unlink(missing_ok=True)
        # Full exception goes to local operator logs; avoid exposing paths/provider secrets in HTTP responses.
        import logging
        logging.exception('Job %s failed',jid)
        message=str(exc) if isinstance(exc,ValueError) else '처리에 실패했습니다. 파일 상태와 서버 로그를 확인한 후 재시도하세요.'
        store.finish(jid,wid,'failed',message[:300])
    finally:
        heartbeat_stop.set();heartbeat.join(timeout=1);STATE.cancel=None
        shutil.rmtree(work,ignore_errors=True)


def loop(stop=None):
    store.init();stop=stop or threading.Event();wid=uuid.uuid4().hex;last_cleanup=0
    while not stop.is_set():
        row=store.claim(wid)
        if row:process(row,stop)
        else:stop.wait(.3)
        if time.monotonic()-last_cleanup>60:store.cleanup();last_cleanup=time.monotonic()

if __name__=='__main__':
    import signal
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    loop(stop)
