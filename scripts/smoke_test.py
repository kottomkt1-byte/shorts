"""Generate tiny synthetic clips and verify the eight actual video templates.
Run from project root: python scripts/smoke_test.py
Requires FFmpeg on PATH; writes to a temporary directory, not uploads/outputs.
"""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import tempfile
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.render import render


def run(cmd):
    subprocess.run(cmd,check=True,capture_output=True)


def main():
    data=json.loads((ROOT/'templates.json').read_text(encoding='utf-8'))
    assert len(data)==8
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp)
        clips=[]
        for i,source in enumerate(['testsrc2','smptebars']):
            filename=tmp/f'input{i}.mp4'
            run(['ffmpeg','-y','-hide_banner','-loglevel','error','-f','lavfi','-i',
                 f'{source}=size=320x568:rate=30','-t','3','-c:v','libx264',
                 '-preset','ultrafast','-pix_fmt','yuv420p',str(filename)])
            clips.append({'id':str(i),'path':str(filename)})
        for spec in data:
            # Shorten clips only for this test, preserving original template lengths.
            sample=dict(spec);sample['shots']=[1.0,1.0,1.0];sample['caption']=spec['caption'][:3]
            out=tmp/(spec['id']+'.mp4')
            render(sample,clips,{'brand':'확인용 테스트','music':True,'quality':'draft'},out,lambda p,s:None)
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error',
                 '-show_entries','stream=codec_name,width,height',
                 '-show_entries','format=duration','-of','json',str(out)],text=True))
            assert out.stat().st_size>1024
            streams=probe['streams']
            assert any(s.get('codec_name')=='h264' and s.get('width')==540 for s in streams)
            assert any(s.get('codec_name')=='aac' for s in streams)
            assert 2.5 < float(probe['format']['duration']) < 3.5
            print('PASS',spec['id'],out.stat().st_size,'bytes')
    print('ALL EIGHT VIDEO TEMPLATES PASSED')

if __name__=='__main__':main()
