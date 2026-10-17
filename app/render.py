"""Video compiler for Auto Shorts Studio.

Uses stock FFmpeg and Pillow. Previews and downloadable H.264 MP4 outputs
are genuine video exports, not static mockups. v1 uses deterministic cut
allocation; AI shot scoring is an explicit next-step extension.
"""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Callable
from .graphics import make_overlay

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = 'ffmpeg'
FFPROBE = 'ffprobe'


def cmd(args: list[str]):
    cp = subprocess.run(args, capture_output=True, text=True)
    if cp.returncode:
        raise RuntimeError(f'FFmpeg failed ({cp.returncode}): {cp.stderr[-2200:]}')
    return cp.stdout.strip()


def duration(path: Path) -> float:
    try:
        s = cmd([FFPROBE,'-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(path)])
        v=float(s)
        if not 0<v<86400:raise ValueError('invalid media duration')
        return v
    except (ValueError, RuntimeError) as exc:
        raise ValueError(f'동영상 길이를 확인할 수 없습니다: {path.name}') from exc


def segment_start(total: float, length: float, nth: int, occurrences: int) -> float:
    # Choose a different interior portion when a user supplies fewer clips
    # than slots, without fabricating footage.
    room=max(0.,total-length-.15)
    return room * ((nth+1)/(occurrences+1))


def _render_scene(src: Path, overlay: Path, output: Path, *, start:float, seconds:float, width:int, height:int, style:str):
    contrast = '1.10' if style in ('punch','meme') else '1.02'
    saturation = '1.16' if style in ('punch','meme','travel') else '0.91' if style in ('luxe','mood','letter') else '1.04'
    vf=(f'[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,'
        f'crop={width}:{height},setsar=1,fps=30,eq=contrast={contrast}:saturation={saturation},'
        'format=yuv420p[bg];'
        f'[1:v]format=rgba,fade=t=in:st=0:d=0.26:alpha=1,'
        f'fade=t=out:st={max(.3,seconds-.28):.3f}:d=0.28:alpha=1[txt];'
        f'[bg][txt]overlay=0:0:shortest=1,format=yuv420p[out]')
    cmd([FFMPEG,'-y','-hide_banner','-loglevel','error',
         '-stream_loop','-1','-ss',f'{start:.3f}','-i',str(src),
         '-loop','1','-i',str(overlay),'-filter_complex',vf,
         '-map','[out]','-t',f'{seconds:.3f}','-an','-r','30',
         '-c:v','libx264','-preset','veryfast','-crf','23',
         '-pix_fmt','yuv420p','-movflags','+faststart',str(output)])


def _join(clips:list[Path], out: Path, *, fade:bool, shot_lengths:list[float], fade_length:float):
    if len(clips)==1:
        cmd([FFMPEG,'-y','-hide_banner','-loglevel','error','-i',str(clips[0]),'-c','copy',str(out)])
        return
    if not fade:
        txt = out.parent/'list.txt'
        # Input filenames are generated paths, never directly provided by users.
        txt.write_text(''.join("file '"+str(p).replace("'", "'\\''")+"'\n" for p in clips),encoding='utf-8')
        cmd([FFMPEG,'-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',str(txt),'-c','copy',str(out)])
        return
    args=[FFMPEG,'-y','-hide_banner','-loglevel','error']
    for p in clips:args+=['-i',str(p)]
    trans='fade'
    # Inputs were already normalized to CFR 30 fps and identical dimensions.
    # Keep FFmpeg's native frame-rate metadata: applying `fps` or `settb`
    # before xfade triggers an FFmpeg 7.1 1/0 fps negotiation bug.
    filters=[]
    current='0:v'
    offset=0.
    for i in range(1,len(clips)):
        offset += shot_lengths[i-1]
        nextout=f'x{i}'
        filters.append(f'[{current}][{i}:v]xfade=transition=fade:duration={fade_length:.2f}:offset={offset:.2f}[{nextout}]')
        current=nextout
    cmd(args+['-filter_complex',';'.join(filters),'-map',f'[{current}]',
              '-an','-c:v','libx264','-preset','veryfast','-crf','23',
              '-pix_fmt','yuv420p','-movflags','+faststart',str(out)])


def _music(silent:Path, out:Path, soundtrack:str|None, total:float):
    if not soundtrack:
        cmd([FFMPEG,'-y','-hide_banner','-loglevel','error','-i',str(silent),'-c','copy',str(out)])
        return
    audio=ROOT/'assets'/'music'/f'{soundtrack}.wav'
    if not audio.is_file():raise RuntimeError('Missing music file: '+str(audio))
    cmd([FFMPEG,'-y','-hide_banner','-loglevel','error','-i',str(silent),'-i',str(audio),
         '-filter_complex',f'[1:a]volume=0.50,afade=t=out:st={max(0,total-1.2):.2f}:d=1.2[a]',
         '-map','0:v:0','-map','[a]','-c:v','copy','-c:a','aac','-b:a','192k',
         '-t',str(total),'-movflags','+faststart',str(out)])


def render(spec:dict, media:list[dict], options:dict, dest:Path, progress:Callable[[int,str],None]):
    quality=options.get('quality','draft')
    width,height=(540,960) if quality=='draft' else (1080,1920)
    shots=spec['shots']; n=len(shots)
    if not media:raise ValueError('영상이 하나 이상 필요합니다.')
    fade=spec['transition']=='fade'
    cross=.35 if fade else 0.
    counts={i:0 for i in range(len(media))}
    occurrences={i:0 for i in range(len(media))}
    for j in range(n):occurrences[j%len(media)]+=1
    clip_durations={m['id']:duration(Path(m['path'])) for m in media}
    progress(3,'영상 길이 분석 완료')
    with tempfile.TemporaryDirectory(prefix='auto-shorts-') as d:
        tmp=Path(d)
        scene_mp4=[]
        for i,sec in enumerate(shots):
            m_idx=i%len(media); m=media[m_idx]
            occ=counts[m_idx];counts[m_idx]+=1
            scene_seconds=sec+(cross if i<n-1 else 0)
            start=segment_start(clip_durations[m['id']],scene_seconds,occ,occurrences[m_idx])
            label=(options.get('captions') or spec['caption'])
            scene_text=label[i] if i<len(label) and label[i] else spec['caption'][i]
            bg=tmp/f'overlay_{i:02d}.png'
            make_overlay(spec,i,text=scene_text,brand=options.get('brand',''),
                         hook=options.get('hook',''),cta=options.get('cta',''),
                         out_file=bg,width=width,height=height)
            scene_file=tmp/f'scene_{i:02d}.mp4'
            _render_scene(Path(m['path']),bg,scene_file,start=start,
                          seconds=scene_seconds,width=width,height=height,style=spec['style'])
            scene_mp4.append(scene_file)
            progress(round(6+74*(i+1)/n),f'장면 {i+1}/{n} 완성')
        muted=tmp/'video_only.mp4'
        _join(scene_mp4,muted,fade=fade,shot_lengths=shots,fade_length=cross)
        progress(92,'영상 연결 완료 · 음악 처리 중')
        _music(muted,dest,spec['music'] if options.get('music',True) else None,sum(shots))
    progress(100,'완성된 MP4를 다운로드할 수 있습니다.')
    return {'path':str(dest),'size':dest.stat().st_size,'duration':sum(shots),'width':width,'height':height}
