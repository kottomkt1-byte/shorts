"""Check local runtime without using any API credits."""
import importlib.util, json, platform, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.graphics import _FONT_FILES
from app.providers import capabilities
from app.schema import SPECS
missing=[]
for command in ['ffmpeg','ffprobe','node','npm']:
    print(command,shutil.which(command) or 'MISSING')
    if not shutil.which(command):missing.append(command)
filters=subprocess.check_output(['ffmpeg','-hide_banner','-filters'],stderr=subprocess.DEVNULL,text=True) if shutil.which('ffmpeg') else ''
for name in ['subtitles','sidechaincompress','xfade']:
    print('FFmpeg filter',name,'OK' if name in filters else 'MISSING')
    if name not in filters:missing.append(name)
print('Fonts',json.dumps(_FONT_FILES,ensure_ascii=False));print('Templates',len(SPECS));print('Providers',capabilities())
if missing:raise SystemExit('Missing: '+', '.join(missing))
