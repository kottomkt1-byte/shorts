"""Bounded local media inspection, quality heuristics, proxies and export validation."""
from __future__ import annotations
import json, subprocess, tempfile, time, os, threading, sys
from pathlib import Path
import numpy as np

STATE=threading.local()
class Cancelled(Exception): pass

def run(args, seconds=None, progress=None, timeout=900, cwd=None):
    """Read real FFmpeg progress and terminate subprocesses on cancellation/timeouts."""
    command=list(map(str,args))
    if Path(command[0]).name=='ffprobe':
        command[1:1]=['-protocol_whitelist','file,pipe','-format_whitelist','mov,matroska,webm,wav,mp3,aac,ogg,flac']
    if Path(command[0]).name=='ffmpeg':
        command[1:1]=['-nostdin','-threads','2','-filter_threads','1','-filter_complex_threads','1']
        if progress and seconds:command[1:1]=['-progress','pipe:1','-stats_period','0.2']
        for index in reversed([i for i,arg in enumerate(command) if arg=='-i']):
            command[index:index]=['-protocol_whitelist','file,pipe']
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        launch=[sys.executable,str(Path(__file__).with_name('process_exec.py')),*command] if sys.platform=='linux' else command
        p=subprocess.Popen(launch,stdout=out,stderr=err,cwd=cwd)
        start=time.monotonic();pos=0
        try:
            while p.poll() is None:
                check=getattr(STATE,'cancel',None)
                if check and check():raise Cancelled('작업이 취소되었습니다.')
                if time.monotonic()-start>timeout:raise RuntimeError('미디어 처리 시간 제한을 초과했습니다.')
                if progress and seconds:
                    out.seek(pos);lines=out.read().decode(errors='replace');pos=out.tell()
                    for line in lines.splitlines():
                        if line.startswith('out_time_us='):
                            try:progress(min(.999,max(0,int(line.split('=')[1])/1e6/seconds)))
                            except ValueError:pass
                time.sleep(.08)
            out.seek(0);stdout=out.read()
            if p.returncode:
                err.seek(0);message=err.read().decode(errors='replace')
                raise RuntimeError('미디어 처리 실패: '+message[-1800:])
            if progress:progress(1)
            return stdout
        finally:
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=3)
                except subprocess.TimeoutExpired:p.kill();p.wait()

def probe(path):
    return json.loads(run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',path],timeout=30))

def inspect(path,kind='video'):
    data=probe(path);streams=data['streams']
    sec=float(data['format'].get('duration',0))
    if not 0<sec<=3600:raise ValueError('입력은 1시간 이하의 유효한 미디어여야 합니다.')
    vs=[s for s in streams if s['codec_type']=='video' and not s.get('disposition',{}).get('attached_pic')]
    audio=any(s['codec_type']=='audio' for s in streams)
    if kind=='video' and not vs:raise ValueError('동영상 스트림이 없습니다.')
    if kind=='music' and not audio:raise ValueError('오디오 스트림이 없습니다.')
    v=vs[0] if vs else {}
    if int(v.get('width',0))*int(v.get('height',0))>3840*2160*2:raise ValueError('최대 8K 미만 해상도만 지원합니다.')
    return {'duration':sec,'width':v.get('width',0),'height':v.get('height',0),'has_audio':audio,'codec':v.get('codec_name')}

def proxy(src,dest,sec,progress):
    run(['ffmpeg','-y','-v','error','-i',src,'-map','0:v:0','-map','0:a:0?',
         '-vf','scale=540:960:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1,fps=30',
         '-c:v','libx264','-preset','ultrafast','-crf','25','-threads','2','-pix_fmt','yuv420p',
         '-c:a','aac','-ar','48000','-movflags','+faststart',dest],seconds=sec,progress=progress)

def analyze(path,metadata):
    """Sample up to 120 frames, detect boundaries and rank quality/motion candidates.
    Audio RMS is explicitly a signal-presence heuristic, not speech recognition.
    """
    sec=metadata['duration'];fps=min(2,120/sec)
    raw=run(['ffmpeg','-v','error','-i',path,'-vf',f'fps={fps},scale=96:54,format=gray','-frames:v','120','-f','rawvideo','-pix_fmt','gray','-'],timeout=180)
    frames=np.frombuffer(raw,dtype=np.uint8)
    count=len(frames)//(96*54)
    if not count:return {'mode':'rules','candidates':[{'start':0,'score':0}],'warnings':['분석 프레임 부족'],'speech':'unknown'}
    frames=frames[:count*96*54].reshape(count,54,96).astype(float)
    candidates=[];last=None;previous_diff=0;boundaries=[]
    for i,f in enumerate(frames):
        lap=-4*f[1:-1,1:-1]+f[:-2,1:-1]+f[2:,1:-1]+f[1:-1,:-2]+f[1:-1,2:]
        sharp=float(np.var(lap));over=float(np.mean(f>245));dark=float(np.mean(f<10))
        diff=float(np.mean(abs(f-last))/255) if last is not None else 0
        shake=abs(diff-previous_diff) if last is not None else 0
        scene_change=diff>.18
        if scene_change:boundaries.append(round(i/fps,3))
        score=np.clip(np.log1p(sharp)/10,0,1)*.5+min(diff,.15)*2-over*.6-dark*.25-max(0,shake-.12)*1.5
        candidates.append({'start':round(i/fps,3),'score':round(float(score),3),'sharpness':round(sharp,2),
                           'overexposure':round(over,3),'motion':round(diff,3),'shake':round(shake,3),'scene_change':scene_change})
        last=f;previous_diff=diff
    audio_rms=0
    if metadata['has_audio']:
        pcm=run(['ffmpeg','-v','error','-i',path,'-t','60','-vn','-ac','1','-ar','8000','-f','f32le','-'],timeout=120)
        a=np.frombuffer(pcm,dtype=np.float32)
        if len(a):audio_rms=float(np.sqrt(np.mean(a*a)))
    ranked=sorted(candidates,key=lambda x:x['score'],reverse=True)
    selected=[]
    for c in ranked:
        if all(abs(c['start']-s['start'])>=max(.5,sec/20) for s in selected):selected.append(c)
        if len(selected)>=8:break
    warnings=[]
    if np.median([c['sharpness'] for c in candidates])<25:warnings.append('흐림 또는 단색 장면 가능성')
    if np.mean([c['overexposure'] for c in candidates])>.3:warnings.append('과노출 가능성')
    if max(c['shake'] for c in candidates)>.25:warnings.append('급격한 화면 변화 또는 흔들림 가능성')
    return {'mode':'rules','candidates':selected,'scene_changes':boundaries,'warnings':warnings,
            'speech':'possible' if audio_rms>.008 else 'not_detected','audio_rms':round(audio_rms,5),
            'note':'프레임 차이·선명도·노출 및 오디오 에너지 기반 추정입니다. 음성과 의미를 확정하지 않습니다.'}

def validate_export(path,width,height,total):
    d=probe(path);v=next((s for s in d['streams'] if s['codec_type']=='video'),None);a=next((s for s in d['streams'] if s['codec_type']=='audio'),None)
    if not v or not a:raise ValueError('출력에 영상 또는 오디오 스트림이 없습니다.')
    fps_num,fps_den=map(int,v['avg_frame_rate'].split('/'))
    vd=float(v.get('duration',d['format']['duration']));ad=float(a.get('duration',d['format']['duration']))
    delta=abs(float(v.get('start_time',0))-float(a.get('start_time',0)))
    end_delta=abs(vd-ad)
    if (v['codec_name'],a['codec_name'],v['width'],v['height'])!=('h264','aac',width,height):raise ValueError('출력 코덱/해상도 검증 실패')
    if abs(fps_num/fps_den-30)>.01 or abs(vd-total)>.12:raise ValueError('출력 프레임레이트/길이 검증 실패')
    if delta>.1 or end_delta>.12:raise ValueError('오디오/영상 타임스탬프 동기화 검증 실패')
    return {'passed':True,'video_codec':'h264','audio_codec':'aac','fps':30,'width':width,'height':height,
            'duration':round(vd,3),'start_delta':round(delta,4),'end_delta':round(end_delta,4),
            'scope':'컨테이너 타임스탬프 검사; 발화와 입 모양의 의미적 동기화 판정은 아닙니다.'}
