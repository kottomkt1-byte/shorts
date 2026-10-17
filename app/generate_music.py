"""Make copyright-original, optional *demo* soundtrack loops.

The bundled tracks are simple synthesized reference audio, not commercial-grade
music. Replace with properly licensed files for production campaigns.
"""
from pathlib import Path
import wave
import numpy as np

SAMPLE_RATE = 24000
LENGTH = 34


def note_to_hz(note):
    return 440 * 2 ** ((note-69)/12)


def put_tone(target, start, duration, midi, vol, *, kind='soft'):
    a=int(start*SAMPLE_RATE); b=min(len(target),a+int(duration*SAMPLE_RATE))
    if b <= a:return
    t=np.arange(b-a,dtype=np.float64)/SAMPLE_RATE
    freq=note_to_hz(midi)
    if kind=='bell':
        snd=np.sin(2*np.pi*freq*t)+0.30*np.sin(2*np.pi*freq*2*t)
        env=np.exp(-t*3.8)*np.minimum(1,t*110)
    elif kind=='pluck':
        snd=np.sin(2*np.pi*freq*t)+.23*np.sin(2*np.pi*freq*2*t)+.08*np.sin(2*np.pi*freq*3*t)
        env=np.exp(-t*4.5)*np.minimum(1,t*120)
    else:
        snd=np.sin(2*np.pi*freq*t)+0.11*np.sin(2*np.pi*freq*.501*t)
        env=np.minimum(1,t*.85) * np.minimum(1,(duration-t)*1.1)
    target[a:b]+=snd*env*vol


def put_kick(target,start,vol=.2):
    a=int(start*SAMPLE_RATE); b=min(len(target),a+int(.28*SAMPLE_RATE))
    if b<=a:return
    t=np.arange(b-a)/SAMPLE_RATE
    phase=2*np.pi*(74*t + (85-74)*(1-np.exp(-t*22))/22)
    env=np.exp(-t*19)
    target[a:b]+=vol*np.sin(phase)*env


def put_click(target,start,vol=.10):
    a=int(start*SAMPLE_RATE); b=min(len(target),a+int(.065*SAMPLE_RATE))
    if b<=a:return
    t=np.arange(b-a)/SAMPLE_RATE
    wavelet=(np.sin(t*2*np.pi*4800)+0.65*np.sin(t*2*np.pi*7187))*np.exp(-t*75)
    target[a:b]+=vol*wavelet


def track(which:str):
    out=np.zeros(LENGTH*SAMPLE_RATE, dtype=np.float64)
    if which in ('pulse','bounce'):
        bpm=122 if which=='pulse' else 142
        beat=60/bpm
        seq=[45,48,52,48,43,47,50,47] if which=='pulse' else [48,55,51,56,48,55,53,56]
        for k in range(int(LENGTH/beat)+1):
            at=k*beat
            put_kick(out,at,.28 if which=='pulse' else .23)
            if k%2==1:put_click(out,at,.09)
            if k%4==0:
                for n in (0,7,12):put_tone(out,at,beat*3,seq[(k//4)%len(seq)]+n,.028,kind='soft')
            put_tone(out,at,beat*.72,seq[(k//2)%len(seq)]-12,.090,kind='pluck')
            if which=='bounce' and k%2==1:
                put_tone(out,at,beat*.3,seq[(k//2)%len(seq)]+12,.045,kind='bell')
    elif which=='cinema':
        chords=[(48,55,60,64),(45,52,57,60),(50,57,62,65),(43,50,55,59)]
        for k in range(6):
            st=k*6
            for n in chords[k%len(chords)]:put_tone(out,st,6.7,n,.035,kind='soft')
            for j in range(3):put_tone(out,st+j*2,1.6,chords[k%len(chords)][2]+12,.017,kind='bell')
    else:
        chords=[(48,55,59,64),(53,60,64,69),(45,52,57,60),(50,57,60,65)]
        for k in range(5):
            st=k*8
            for n in chords[k%len(chords)]:put_tone(out,st,9,n,.032,kind='soft')
            for j in range(4):put_tone(out,st+1.2+2*j,1.7,chords[k%len(chords)][2]+12,.018,kind='bell')
    # A simple, warm delay; subtle stereo not needed for functional demo.
    d=int(.24*SAMPLE_RATE)
    out[d:]+=out[:-d]*.22
    out=np.tanh(out*1.8)
    peak=np.max(np.abs(out))
    if peak>0:out=out/max(peak,1e-6)*0.73
    fade=int(.6*SAMPLE_RATE)
    out[-fade:]*=np.linspace(1,0,fade)
    return np.asarray(out*32767,dtype=np.int16)


def main(root:Path):
    root.mkdir(parents=True,exist_ok=True)
    for name in ('pulse','bounce','cinema','ambient'):
        path=root/f'{name}.wav'
        with wave.open(str(path),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(SAMPLE_RATE)
            f.writeframes(track(name).tobytes())
        print(name,path.stat().st_size)

if __name__=='__main__':
    main(Path(__file__).resolve().parents[1]/'assets'/'music')
