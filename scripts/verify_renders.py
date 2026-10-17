"""Acceptance matrix: 1/3/10 sources × all 8 templates at full duration + 8 samples.
No model/API access. All sources are generated locally. Reports actual ffprobe results.
"""
import copy, json, sys, time, argparse, re
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.schema import SPECS
from app.render import render
from app.media import run, inspect, analyze, probe, proxy

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/renders';OUT.mkdir(parents=True,exist_ok=True)

def fixtures(folder=OUT):
    folder.mkdir(parents=True,exist_ok=True)
    voice=folder/'voice.wav'
    run(['ffmpeg','-y','-v','error','-f','lavfi','-i','flite=text=This is original speech for our video editing test.:voice=slt','-ar','48000',voice])
    sources=[]
    for i in range(10):
        ext=['mp4','mov','mp4','webm','m4v'][i%5];p=folder/f'source-{i}.{ext}'
        sec=.2 if i==2 else 3
        size='640x360' if i%2 else '360x640'
        args=['ffmpeg','-y','-v','error','-f','lavfi','-i',f'testsrc2=size={size}:rate=30']
        if i%3==0:args+=['-i',voice]
        args+=['-t',sec,'-c:v','libvpx-vp9' if ext=='webm' else 'libx264','-threads','2']
        if ext=='webm':args+=['-deadline','realtime','-cpu-used','8','-c:a','libopus']
        else:args+=['-preset','ultrafast','-c:a','aac']
        run([*args,'-pix_fmt','yuv420p',p])
        metadata=inspect(p);analysis=analyze(p,metadata)
        sources.append({'id':str(i),'path':str(p),'analysis':analysis,**metadata})
    return sources

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--only',help='rerun matching cases and retain other verified results');args=parser.parse_args()
    sources=fixtures();report_path=ROOT/'evidence/render-report.json'
    report=json.loads(report_path.read_text()) if args.only and report_path.exists() else {'started':datetime.now(timezone.utc).isoformat(),'results':[],'inputs':[dict(m,path=Path(m['path']).name) for m in sources]}
    def record(name,spec,media,options):
        if args.only and not re.search(args.only,name):return
        report['results']=[r for r in report['results'] if r['name']!=name]
        start=time.monotonic();dest=OUT/(name+'.mp4');last=[-1]
        def progress(p,msg):
            if p//25>last[0]:last[0]=p//25;print(name,p,msg,flush=True)
        result=render(spec,media,options,dest,progress)
        # Decode the entire completed file too: metadata alone cannot prove valid video packets.
        run(['ffmpeg','-v','error','-i',dest,'-f','null','-'],timeout=300)
        report['results'].append({'name':name,'template':spec['id'],'sources':len(media),'seconds_elapsed':round(time.monotonic()-start,2),
                                  'bytes':result['size'],'validation':result['validation'],'file':str(dest.relative_to(ROOT))})
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print('PASS',name,flush=True)
    for n in (1,3,10):
        for spec in SPECS:
            record(f'{n}inputs-{spec["id"]}',spec,sources[:n],{'quality':'full','brand':'나의 브랜드','hook':'일상에서 직접 확인한 장면을 담았습니다','cta':'자세한 정보 확인하기','music':n==3,'original_audio':True})
    # Same actual rendering path, all original durations, before any user upload.
    sample=[dict(sources[1],id='sample')]
    for spec in SPECS:record('sample-'+spec['id'],spec,sample,{'quality':'draft','music':False})
    spec=copy.deepcopy(SPECS[0]);spec['shots']=[1,1];spec['caption']=['한국어 긴 문구를 화면 밖으로 넘치지 않게 표시하는지 확인합니다. '*8,'광고 정보를 확인하세요']
    record('edge-silent-short-korean',spec,[sources[2]],{'quality':'full','brand':'긴 브랜드명 '*10,'original_audio':False,'words':[{'start':.1,'end':.6,'text':'안녕하세요'},{'start':.6,'end':1.5,'text':'한국어자막입니다'}],'insert_disclosure':True,'disclosure':'유료 광고를 포함합니다','platform':'tiktok'})
    for m in sources[:5]:
        dest=OUT/f'proxy-{m["id"]}.mp4';proxy(Path(m['path']),dest,m['duration'],lambda _:None)
        p=probe(dest);assert p['streams'][0]['codec_name']=='h264'
    report['proxy_formats']=['mp4','mov','webm','m4v'];report['completed']=datetime.now(timezone.utc).isoformat();report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('ALL',len(report['results']),'RENDERS PASSED',flush=True)
if __name__=='__main__':main()
