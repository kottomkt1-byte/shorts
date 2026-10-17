"""FFmpeg compositions shared by exact previews and downloadable exports."""
from __future__ import annotations
from pathlib import Path
import tempfile, json, wave
import numpy as np
from PIL import ImageDraw
from .graphics import make_overlay, transparent, font, title_text
from .media import run, inspect, validate_export
from .compose import composition
from .schema import SAFE_AREAS
ROOT=Path(__file__).resolve().parents[1]

def cmd(args):return run(args).decode().strip()
def duration(path):return inspect(path)['duration']

def subtitle_ass(words,path,position,platform):
    area=SAFE_AREAS[platform]
    margin={'top':area['top']+70,'center':0,'bottom':area['bottom']+55}[position]
    alignment={'top':8,'center':5,'bottom':2}[position]
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK KR,54,&H00FFFFFF,&H0070FFE1,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,3,0,{alignment},{area['left']+25},{area['right']+25},{margin},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    def stamp(t):
        cs=round(t*100);return f'{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}'
    # Group up to 18 Korean characters; every word retains its own timing/highlight.
    groups=[];group=[]
    for word in words:
        if group and (sum(len(w['text'])+1 for w in group)+len(word['text'])>18 or word['start']-group[-1]['end']>.5):groups.append(group);group=[]
        group.append(word)
    if group:groups.append(group)
    def safe(text):return text.replace('\\','＼').replace('{','｛').replace('}','｝').replace('\n',' ')
    lines=[]
    for group in groups:
        for index,word in enumerate(group):
            text=' '.join(('{\\c&H70FFE1&}' if i==index else '{\\c&HFFFFFF&}')+safe(w['text']) for i,w in enumerate(group))
            lines.append(f"Dialogue: 0,{stamp(word['start'])},{stamp(word['end'])},Default,,0,0,0,,{text}")
    path.write_text(header+'\n'.join(lines),encoding='utf-8')

def render(spec,media,options,dest,progress,plan=None):
    # Direct legacy callers may supply a shortened spec for regression testing.
    if plan is None:
        media=[dict(m,**inspect(Path(m['path']))) if 'duration' not in m else m for m in media]
        opts=dict(options,template_id=spec['id'])
        if not opts.get('scenes'):
            opts['scenes']=[{'clip_id':media[i%len(media)]['id'],'start':0,'duration':sec,'text':(opts.get('captions') or spec['caption'])[i]} for i,sec in enumerate(spec['shots'])]
        plan=composition(opts,media)
        plan['spec'].update({k:spec[k] for k in ('transition','color','style')})
    spec=plan['spec'];scenes=plan['scenes'];options=plan['options']
    width,height=(540,960) if options.get('quality')=='draft' else (1080,1920)
    total=sum(s['duration'] for s in scenes);by_id={m['id']:m for m in media}
    cross=.3 if spec['transition']=='fade' else 0
    progress(1,'렌더 준비 완료')
    dest=Path(dest).resolve();dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='render-',dir=dest.parent) as folder:
        tmp=Path(folder);clips=[];audios=[]
        for i,s in enumerate(scenes):
            sec=s['duration'];extra=cross if i<len(scenes)-1 else 0
            m=by_id[s['clip_id']];source=Path(m['path'])
            overlay=tmp/f'overlay_{i}.png'
            make_overlay(spec,i,text=s['text'],brand=options.get('brand') or options.get('product',''),hook='',cta='',out_file=overlay,width=width,height=height)
            motion=spec['motion']
            x={'snap':"0",'rise':"0",'bounce':"0",'slide':f"{width}*max(0,1-t/0.35)",'drift':"0",'pan':"0",'breathe':"0",'reveal':"0"}[motion]
            y={'snap':f"-{height}*0.03*max(0,1-t/0.12)",'rise':f"{height}*0.08*max(0,1-t/0.5)",'bounce':f"{height}*0.045*sin(t*20)*exp(-t*5)",'slide':"0",'drift':f"{height}*0.007*sin(t*0.9)",'pan':"0",'breathe':f"{height}*0.004*sin(t*1.6)",'reveal':f"{height}*0.02*max(0,1-t/0.8)"}[motion]
            fade={'snap':.10,'rise':.25,'bounce':.10,'slide':.15,'drift':.65,'pan':.4,'breathe':.9,'reveal':.8}[motion]
            scaled_w=width+40;scaled_h=height+72
            cropx="(iw-ow)/2";cropy="(ih-oh)/2"
            if motion=='pan':cropx=f"(iw-ow)*min(1,t/{sec+extra})"
            if motion=='drift':cropy=f"(ih-oh)*(1-min(1,t/{sec+extra}))"
            if motion=='breathe':cropx="(iw-ow)/2+10*sin(t*0.7)"
            vf=(f'[0:v]setpts=PTS-STARTPTS,scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,'
                f"crop={width}:{height}:x='{cropx}':y='{cropy}',setsar=1,fps=30,"
                f"eq=contrast={spec['contrast']}:saturation={spec['saturation']},format=yuv420p[bg];"
                f'[1:v]format=rgba,fade=t=in:d={fade}:alpha=1[txt];'
                f"[bg][txt]overlay=x='{x}':y='{y}':shortest=1,format=yuv420p[out]")
            scene=tmp/f'scene_{i}.mp4'
            run(['ffmpeg','-y','-v','error','-stream_loop','-1','-ss',s['start'],'-i',source,'-loop','1','-i',overlay,
                 '-filter_complex',vf,'-map','[out]','-t',sec+extra,'-an','-r','30','-c:v','libx264','-threads','2',
                 '-preset','ultrafast','-crf','22','-pix_fmt','yuv420p',scene],seconds=sec+extra,
                progress=lambda f:progress(round(2+65*(i+f)/len(scenes)),f'장면 {i+1}/{len(scenes)} 인코딩'))
            clips.append(scene)
            audio=tmp/f'audio_{i}.wav'
            if m.get('has_audio') and options.get('original_audio',True):
                # Match video looping and seek; no fabricated speech on silent inputs.
                args=['-stream_loop','-1','-ss',s['start'],'-i',source]
            else:args=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
            run(['ffmpeg','-y','-v','error',*args,'-vn','-t',sec+extra,'-af','aresample=48000,asetpts=PTS-STARTPTS','-ac','2','-c:a','pcm_s16le',audio])
            audios.append(audio)
        joined=tmp/'joined.mp4';joined_audio=tmp/'joined.wav'
        if cross and len(clips)>1:
            args=[]
            for clip in clips:args+=['-i',clip]
            filters=[];current='0:v';offset=0
            for i in range(1,len(clips)):
                offset+=scenes[i-1]['duration'];nxt=f'x{i}'
                filters.append(f'[{current}][{i}:v]xfade=transition=fade:duration={cross}:offset={offset}[{nxt}]');current=nxt
            run(['ffmpeg','-y','-v','error',*args,'-filter_complex',';'.join(filters),'-map',f'[{current}]','-t',total,
                 '-an','-c:v','libx264','-threads','2','-preset','ultrafast','-crf','22','-pix_fmt','yuv420p',joined],seconds=total,progress=lambda f:progress(round(68+13*f),'장면 디졸브 연결'))
            args=[]
            for audio in audios:args+=['-i',audio]
            # Mix explicitly delayed, faded PCM tracks. A chain of acrossfade filters
            # can terminate early on silent inputs in some FFmpeg builds.
            filters=[];offset=0
            for i,audio in enumerate(audios):
                fade_in=f'afade=t=in:d={cross},' if i else ''
                fade_out=f'afade=t=out:st={scenes[i]["duration"]}:d={cross},' if i<len(audios)-1 else ''
                filters.append(f'[{i}:a]{fade_in}{fade_out}adelay={round(offset*1000)}:all=1[a{i}]')
                offset+=scenes[i]['duration']
            inputs=''.join(f'[a{i}]' for i in range(len(audios)))
            filters.append(f'{inputs}amix=inputs={len(audios)}:duration=longest:normalize=0,apad,atrim=duration={total},asetpts=N/SR/TB[voice]')
            run(['ffmpeg','-y','-v','error',*args,'-filter_complex',';'.join(filters),'-map','[voice]','-t',total,joined_audio])
        else:
            for items,out in [(clips,joined),(audios,joined_audio)]:
                listing=tmp/(out.stem+'.txt');listing.write_text(''.join(f"file '{p.name}'\n" for p in items))
                run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',listing,'-c','copy',out])
        progress(82,'원본 오디오 정규화 및 BGM 덕킹')
        music=options.get('_music_path') or (str(ROOT/'assets/music'/f"{spec['music']}.wav") if options.get('music') else None)
        mixed=tmp/'mixed.m4a'
        normalization_source=joined_audio
        if music:
            filters='[0:a]asplit=2[voice][side];[1:a]volume=0.22[bg];[bg][side]sidechaincompress=threshold=0.025:ratio=10:attack=15:release=500[duck];[voice][duck]amix=inputs=2:duration=first:normalize=0,aresample=48000,apad,atrim=duration='+str(total)+',asetpts=N/SR/TB[a]'
            normalization_source=tmp/'premix.wav'
            run(['ffmpeg','-y','-v','error','-i',joined_audio,'-stream_loop','-1','-i',music,'-filter_complex',filters,
                 '-map','[a]','-t',total,'-ar','48000','-ac','2','-c:a','pcm_s16le',normalization_source])
        # Integrated loudness is undefined for silence. Some FFmpeg versions emit
        # NaN or truncate their output when loudnorm receives only digital silence.
        audible=False
        with wave.open(str(normalization_source),'rb') as wav:
            while block:=wav.readframes(48000):
                if np.max(np.abs(np.frombuffer(block,dtype=np.int16).astype(np.int32)))>32:
                    audible=True;break
        normalization='loudnorm=I=-16:TP=-1.5:LRA=11,' if audible else ''
        filters=f'{normalization}aresample=48000,apad,atrim=duration={total},asetpts=N/SR/TB'
        run(['ffmpeg','-y','-v','error','-i',normalization_source,'-af',filters,'-t',total,'-ar','48000','-ac','2',
             '-c:a','aac','-b:a','192k',mixed])
        # Disclosure and word-timed captions are applied with exactly the same code in previews.
        filters=[];args=['-i',joined,'-i',mixed];current='0:v'
        if options.get('insert_disclosure'):
            img=transparent(width,height);d=ImageDraw.Draw(img)
            top=int(SAFE_AREAS[options.get('platform','youtube')]['top']*height/1920)
            d.rectangle((25,top,width-95,top+int(150*height/1920)),fill=(0,0,0,210))
            title_text(d,(35,top+8),options['disclosure'],width=width-140,fsize=int(40*height/1920),fill='white',max_lines=2,shadow=False)
            dp=tmp/'disclosure.png';img.save(dp);args+=['-loop','1','-i',dp]
            filters.append('[0:v][2:v]overlay=0:0:shortest=1[disclosed]');current='disclosed'
        if options.get('words'):
            ass=tmp/'captions.ass';subtitle_ass(options['words'],ass,options.get('subtitle_position','bottom'),options.get('platform','youtube'))
            # Generated path only. Never interpolate user text in filter expressions.
            filters.append(f"[{current}]subtitles=filename='{ass.name}'[subbed]");current='subbed'
        if filters:
            args+=['-filter_complex',';'.join(filters),'-map',f'[{current}]','-c:v','libx264','-threads','2','-preset','ultrafast','-crf','22']
        else:args+=['-map','0:v','-c:v','copy']
        run(['ffmpeg','-y','-v','error',*args,'-map','1:a','-c:a','copy','-t',total,'-pix_fmt','yuv420p','-movflags','+faststart',dest],seconds=total,progress=lambda f:progress(round(87+9*f),'최종 MP4 구성'),cwd=tmp)
        progress(97,'다운로드 전 오디오·영상 동기화 검사')
        validation=validate_export(dest,width,height,total)
    progress(100,'렌더링 및 출력 검증 완료')
    return {'size':dest.stat().st_size,'duration':total,'width':width,'height':height,'validation':validation,'plan':plan}
