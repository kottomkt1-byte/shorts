"""Validated, shared composition contracts. The JSON registry is the source of truth."""
from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator

ROOT = Path(__file__).resolve().parents[1]
class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Template(Strict):
    id: str = Field(pattern=r'^[a-z0-9-]+$')
    category: str
    name: str
    subtitle: str
    duration: float = Field(gt=0,le=180)
    shots: list[float] = Field(min_length=1,max_length=12)
    transition: Literal['cut','fade']
    color: str = Field(pattern=r'^#[0-9a-fA-F]{6}$')
    ink: str = Field(pattern=r'^#[0-9a-fA-F]{6}$')
    surface: str = Field(pattern=r'^#[0-9a-fA-F]{6}$')
    style: Literal['punch','review','meme','chat','luxe','travel','mood','letter']
    motion: Literal['snap','rise','bounce','slide','drift','pan','breathe','reveal']
    contrast: float = Field(ge=.5,le=2)
    saturation: float = Field(ge=0,le=2)
    music: Literal['pulse','bounce','cinema','ambient']
    caption: list[str]
    tags: list[str]
    @model_validator(mode='after')
    def valid_timing(self):
        if len(self.shots)!=len(self.caption) or not math.isclose(sum(self.shots),self.duration,abs_tol=.01):
            raise ValueError('Template timing and captions must agree')
        if any(not math.isfinite(s) or not .5<=s<=30 for s in self.shots):
            raise ValueError('Scene durations must be 0.5–30 seconds')
        return self

def load_templates():
    specs=[Template.model_validate(t).model_dump() for t in json.loads((ROOT/'templates.json').read_text())]
    if len(specs)!=8 or len({t['id'] for t in specs})!=8:raise ValueError('Exactly eight unique templates required')
    return specs

class Word(Strict):
    start: float = Field(ge=0,le=180)
    end: float = Field(gt=0,le=180)
    text: str = Field(min_length=1,max_length=120)
    @model_validator(mode='after')
    def order(self):
        if self.end<=self.start:raise ValueError('자막 종료 시간은 시작보다 커야 합니다.')
        return self

class Scene(Strict):
    clip_id: str = Field(max_length=64)
    start: float = Field(default=0,ge=0,le=3600)
    duration: float = Field(ge=.5,le=30)
    text: str = Field(default='',max_length=300)

class Edit(Strict):
    template_id: str = Field(max_length=64)
    clip_ids: list[str] = Field(default_factory=list,max_length=20)
    brand: str = Field(default='',max_length=80)
    hook: str = Field(default='',max_length=300)
    cta: str = Field(default='',max_length=200)
    captions: list[str] = Field(default_factory=list,max_length=12)
    scenes: list[Scene] = Field(default_factory=list,max_length=12)
    quality: Literal['draft','full'] = 'full'
    music: bool = False
    music_id: str | None = Field(default=None,max_length=64)
    original_audio: bool = True
    words: list[Word] = Field(default_factory=list,max_length=500)
    subtitle_position: Literal['top','center','bottom'] = 'bottom'
    platform: Literal['youtube','instagram','tiktok'] = 'youtube'
    product: str = Field(default='',max_length=80)
    benefits: str = Field(default='',max_length=300)
    audience: str = Field(default='',max_length=200)
    disclosure: str = Field(default='',max_length=200)
    insert_disclosure: bool = False
    disclosure_confirmed: bool = False
    color: str | None = Field(default=None,pattern=r'^#[0-9a-fA-F]{6}$')
    @model_validator(mode='after')
    def bounds(self):
        if len(self.clip_ids)!=len(set(self.clip_ids)):raise ValueError('Duplicate clip IDs')
        if sum(s.duration for s in self.scenes)>180:raise ValueError('최대 출력 길이는 180초입니다.')
        if self.insert_disclosure and (not self.disclosure.strip() or not self.disclosure_confirmed):
            raise ValueError('고지 문구를 입력하고 직접 확인해주세요.')
        if any(len(c)>300 for c in self.captions):raise ValueError('장면 문구는 300자 이하입니다.')
        if any(a.end>b.start+.001 for a,b in zip(self.words,self.words[1:])):raise ValueError('자막 시간은 겹치지 않게 정렬해주세요.')
        return self

SPECS=load_templates()
BY_ID={t['id']:t for t in SPECS}
# Insets in the 1080×1920 reference canvas; editorial guides, not policy guarantees.
SAFE_AREAS={'youtube':{'top':180,'right':170,'bottom':340,'left':65},'instagram':{'top':220,'right':160,'bottom':350,'left':65},'tiktok':{'top':210,'right':190,'bottom':380,'left':65}}
