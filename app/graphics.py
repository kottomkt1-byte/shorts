"""Copyright-original graphic overlays for eight short video templates.

Designs are generated, not copied from any third-party template.
"""
from __future__ import annotations
from pathlib import Path
import math
from functools import lru_cache
import os
import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONT_SANS = ["Noto Sans CJK KR", "NanumGothic", "DejaVu Sans"]
FONT_SERIF = ["Noto Serif CJK KR", "NanumMyeongjo", "DejaVu Serif"]


def _find_font(serif: bool = False, bold: bool = False) -> str | None:
    # Explicit font override and OS fonts support Windows/macOS where fc-match may be absent.
    override = os.environ.get('AUTO_SHORTS_FONT')
    if override and Path(override).is_file():
        return override
    alternatives = (
        [r'C:\Windows\Fonts\batang.ttc', '/System/Library/Fonts/Supplemental/AppleMyungjo.ttf']
        if serif else
        ([r'C:\Windows\Fonts\malgunbd.ttf', r'C:\Windows\Fonts\malgun.ttf']
         if bold else [r'C:\Windows\Fonts\malgun.ttf']) +
        ['/System/Library/Fonts/AppleSDGothicNeo.ttc']
    )
    for f in alternatives:
        if Path(f).is_file():
            return f
    family = FONT_SERIF if serif else FONT_SANS
    # Use system fonts, and never bundle fonts in output.
    for name in family:
        pat = name + (":style=Bold" if bold else "")
        try:
            p = subprocess.run(["fc-match", "-f", "%{file}", pat], capture_output=True, text=True, timeout=3)
            if p.returncode == 0 and Path(p.stdout.strip()).is_file():
                return p.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None

_FONT_FILES = {
    "sans": _find_font(),
    "bold": _find_font(bold=True),
    "serif": _find_font(serif=True),
}


@lru_cache(maxsize=256)
def font(size: int, typ: str = "bold") -> ImageFont.FreeTypeFont:
    name = _FONT_FILES.get(typ) or _FONT_FILES["sans"]
    if name:
        return ImageFont.truetype(name, size=max(12, size))
    return ImageFont.load_default(size=max(12, size))


def rgb(hx: str):
    hx = hx.lstrip("#")
    return tuple(int(hx[i:i+2], 16) for i in (0, 2, 4))


def _blend(c1, c2, a: float):
    return tuple(int(c1[i] * (1-a) + c2[i] * a) for i in range(3))


def transparent(width: int, height: int) -> Image.Image:
    return Image.new("RGBA", (width, height), (0, 0, 0, 0))


def wrap_text(draw: ImageDraw.ImageDraw, txt: str, max_width: int, ft, max_lines=3):
    out = []
    for para in (txt or "").split("\n"):
        if not para:
            continue
        line = ""
        for ch in para:
            if draw.textlength(line + ch, font=ft) <= max_width:
                line += ch
            else:
                if line:
                    out.append(line.strip())
                line = ch
        if line:
            out.append(line.strip())
    if len(out) > max_lines:
        out = out[:max_lines]
        while draw.textlength(out[-1] + '…', font=ft) > max_width and out[-1]:
            out[-1] = out[-1][:-1]
        out[-1] += '…'
    return out


def title_text(draw, xy, text: str, *, width: int, fsize: int, fill, mode="bold", spacing=1.17, anchor="lt", shadow=True, max_lines=3):
    x,y = xy
    ft = font(fsize, mode)
    available_height = fsize * spacing * max_lines
    lines = wrap_text(draw, text, width, ft, 1000)
    while len(lines) * fsize * spacing > available_height and fsize > 12:
        fsize -= 1
        ft = font(fsize, mode)
        lines = wrap_text(draw, text, width, ft, 1000)
    step = int(fsize*spacing)
    for i,line in enumerate(lines):
        bx = x
        if anchor == "center":
            bx = x - int(draw.textlength(line, font=ft)/2)
        if shadow:
            draw.text((bx+3,y+i*step+5),line,font=ft,fill=(0,0,0,160),stroke_width=0)
        draw.text((bx,y+i*step),line,font=ft,fill=fill)
    return y + len(lines)*step


def _block(draw, xy, *, radius, fill, outline=None, width=2):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _common_top(draw, r, spec, label, brand, idx, total):
    # All coordinates in normalized 1080x1920 base canvas.
    draw.rectangle((0,0,1080,18), fill=rgb(spec['color'])+(255,))
    draw.text((80,72), brand or 'YOUR BRAND', font=font(43,'bold'), fill=(255,255,255,240))
    draw.text((995,80),f"{idx+1:02d}/{total:02d}",font=font(37),fill=(255,255,255,220), anchor='ra')


def make_overlay(spec: dict, scene: int, *, text: str, brand: str, hook: str, cta: str, out_file: Path, width=1080, height=1920):
    s = spec['style']
    accent = rgb(spec['color'])
    img = transparent(1080, 1920)
    draw = ImageDraw.Draw(img)
    # Visual UI elements are composed independently from the user's footage.
    if s == 'punch':
        draw.rectangle((0,0,1080,400),fill=(9,10,17,130))
        draw.rectangle((0,1100,1080,1920),fill=(9,10,17,175))
        draw.polygon([(1080,245),(800,245),(1080,540)],fill=accent+(235,))
        _block(draw,(80,305,590,385),radius=15,fill=accent+(255,))
        draw.text((110,320),'CHECK THIS OUT',font=font(41,'bold'),fill=(14,14,14,255))
        content = (hook if scene==0 and hook else text)
        title_text(draw,(82,1165),content,width=900,fsize=108,fill=(255,255,255,255),max_lines=3)
        draw.rectangle((80,1585,998,1595),fill=accent+(255,))
        title_text(draw,(80,1650),(cta if scene==len(spec['shots'])-1 and cta else brand),width=920,fsize=53,mode='bold',fill=accent+(255,),max_lines=1,shadow=False)
        for i in range(len(spec['shots'])):
            draw.rectangle((i*178,1907,i*178+170,1920), fill=accent+(255,) if i<=scene else (255,255,255,55))
    elif s == 'review':
        draw.rectangle((0,0,1080,270),fill=(12,25,17,160))
        _block(draw,(70,1040,1010,1615),radius=43,fill=(253,249,239,245))
        draw.rectangle((98,1100,115,1545),fill=accent+(255,))
        n = f'0{scene+1}'
        draw.text((150,1092),f'POINT {n}',font=font(49,'bold'),fill=(43,95,59,255))
        title_text(draw,(150,1210),hook if scene==0 and hook else text,width=790,fsize=91,fill=(14,32,25,255),shadow=False)
        title_text(draw,(80,1680),brand or 'REVIEW',width=920,fsize=55,mode='bold',fill=(255,255,255,255),max_lines=1,shadow=False)
    elif s=='meme':
        draw.rectangle((0,0,1080,280),fill=(32,9,59,165))
        draw.rounded_rectangle((62,365,1020,820),radius=60,fill=(253,78,183,235),outline=(255,255,255,255),width=10)
        draw.polygon([(810,804),(905,912),(876,806)],fill=(253,78,183,250))
        title_text(draw,(115,448),hook if scene==0 and hook else text,width=850,fsize=105,fill=(255,255,255,255),shadow=True,max_lines=3)
        draw.ellipse((805,1010,1040,1240),outline=accent+(255,),width=23)
        draw.text((852,1037),'!!',font=font(110,'bold'),fill=accent+(255,))
        draw.rectangle((0,1640,1080,1920),fill=(31,10,64,190))
        title_text(draw,(70,1730),brand or 'MEME MODE',width=930,fsize=65,mode='bold',fill=accent+(255,),max_lines=1,shadow=False)
    elif s=='chat':
        draw.rectangle((0,0,1080,320),fill=(11,15,49,205))
        _block(draw,(75,530,950,950),radius=55,fill=(239,245,255,245))
        draw.ellipse((113,570,184,641),fill=(69,106,242,255))
        draw.text((205,565),'POV',font=font(52,'bold'),fill=(40,58,120,255))
        title_text(draw,(132,680),hook if scene==0 and hook else text,width=740,fsize=84,fill=(20,26,59,255),shadow=False)
        _block(draw,(350,1040,1022,1220),radius=49,fill=accent+(238,))
        draw.text((413,1097),'...입력 중',font=font(50,'bold'),fill=(15,29,78,255))
        title_text(draw,(78,1700),brand or 'STORY',width=922,fsize=61,mode='bold',fill=(255,255,255,250),max_lines=1,shadow=False)
    elif s=='luxe':
        draw.rectangle((0,0,1080,220),fill=(0,0,0,235))
        draw.rectangle((0,1460,1080,1920),fill=(0,0,0,210))
        draw.line((85,1500,995,1500),fill=accent+(225,),width=3)
        draw.text((85,1515),'E D I T O R I A L    F I L M',font=font(33,'serif'),fill=accent+(255,))
        title_text(draw,(86,1600),hook if scene==0 and hook else text,width=905,fsize=73,fill=(245,240,231,255),mode='serif',shadow=False)
        title_text(draw,(85,104),brand or 'THE COLLECTION',width=915,fsize=50,mode='serif',fill=accent+(255,),max_lines=1,shadow=False)
    elif s=='travel':
        draw.rectangle((0,0,1080,275),fill=(7,42,60,155))
        draw.rectangle((0,1430,1080,1920),fill=(8,47,75,135))
        draw.ellipse((85,352,142,409),outline=(255,255,255,235),width=6)
        draw.ellipse((104,370,123,390),fill=(255,255,255,235))
        draw.text((167,360),'MOMENTS / PLACES',font=font(46,'bold'),fill=(255,255,255,235))
        title_text(draw,(80,1470),hook if scene==0 and hook else text,width=910,fsize=91,fill=(255,255,255,255))
        title_text(draw,(82,1760),brand or 'TRAVEL NOTES',width=918,fsize=49,mode='bold',fill=(255,255,255,240),max_lines=1,shadow=False)
    elif s=='mood':
        # Warm film tone; the footage remains visible under a transparent wash.
        draw.rectangle((0,0,1080,1920),fill=(72,68,40,45))
        draw.rectangle((0,0,1080,180),fill=(18,32,23,96))
        draw.rectangle((0,1275,1080,1920),fill=(23,33,26,122))
        draw.line((100,1320,265,1320),fill=accent+(250,),width=4)
        title_text(draw,(95,1390),hook if scene==0 and hook else text,width=895,fsize=79,fill=(255,249,239,255),mode='serif',shadow=False,max_lines=3)
        title_text(draw,(97,1730),brand or 'SLOW MOMENTS',width=903,fsize=49,mode='serif',fill=(255,249,239,245),max_lines=1,shadow=False)
    elif s=='letter':
        draw.rectangle((0,0,1080,1920),fill=(13,13,12,104))
        _block(draw,(85,760,995,1460),radius=8,fill=(30,29,27,198),outline=accent+(175,),width=3)
        draw.text((130,825),'A LETTER FROM',font=font(47,'serif'),fill=accent+(255,))
        draw.line((130,900,335,900),fill=accent+(255,),width=3)
        title_text(draw,(130,970),hook if scene==0 and hook else text,width=812,fsize=76,fill=(246,240,226,255),mode='serif',shadow=False,max_lines=4)
        title_text(draw,(130,1328),brand or 'BRAND STORY',width=870,fsize=46,mode='serif',fill=accent+(255,),max_lines=1,shadow=False)
    # Scale with high-quality resampling, preserve actual design ratios.
    if (width,height)!=(1080,1920):
        img=img.resize((width,height),Image.Resampling.LANCZOS)
    out_file.parent.mkdir(parents=True,exist_ok=True)
    img.save(out_file)


def cover(spec: dict, out_file: Path, width=420, height=746):
    # A visual reference thumbnail that is not borrowed from a third party.
    base=Image.new('RGB',(1080,1920),rgb(spec['surface']))
    d=ImageDraw.Draw(base)
    for k in range(22):
        x=(k*123)%1080; y=(k*419)%1920
        c=_blend(rgb(spec['surface']),rgb(spec['color']),0.12+(k%5)*0.07)
        d.rounded_rectangle((x-140,y-140,x+180,y+370),radius=90,fill=c)
    dim=Image.new('RGBA',(1080,1920),(0,0,0,100 if spec['style'] not in ['review','meme'] else 40))
    base=Image.alpha_composite(base.convert('RGBA'),dim)
    d=ImageDraw.Draw(base)
    d.rounded_rectangle((95,134,985,1792),radius=57,outline=rgb(spec['color'])+(230,),width=5)
    d.rectangle((95,134,985,151),fill=rgb(spec['color'])+(255,))
    d.text((151,250),spec['category'].upper(),font=font(65,'bold'),fill=(255,255,255,242))
    for i,ln in enumerate(spec['name'].split(' ')):
        d.text((130,820+i*146),ln,font=font(145,'bold'),fill=(255,255,255,255),stroke_width=3,stroke_fill=(0,0,0,80))
    d.text((135,1540),f"{spec['duration']} SEC  /  {len(spec['shots'])} SCENES",font=font(60,'bold'),fill=rgb(spec['color'])+(255,))
    base.resize((width,height),Image.Resampling.LANCZOS).convert('RGB').save(out_file,quality=90)
