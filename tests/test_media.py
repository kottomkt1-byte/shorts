import tempfile, unittest
from pathlib import Path
from app.media import run, inspect, Cancelled, STATE, probe
from app.render import render
from app.schema import SPECS

class MediaRegression(unittest.TestCase):
    def test_silent_dissolve_and_short_source_keep_audio_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);source=folder/'short.mp4'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=blue:size=160x90:rate=30','-t','0.2','-c:v','libx264','-threads','2',source])
            spec=dict(SPECS[4],shots=[.5]*6,caption=['긴 한국어 테스트']*6)
            result=render(spec,[{'id':'source','path':str(source)}],{'quality':'draft','music':False},folder/'result.mp4',lambda *_:None)
            self.assertTrue(result['validation']['passed'])
            self.assertLess(result['validation']['end_delta'],.04)
            d=probe(folder/'result.mp4');self.assertEqual(len(d['streams']),2)
    def test_two_second_digital_silence_avoids_loudnorm_nan(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)/"한글 폴더 ' test";folder.mkdir();source=folder/'silent.mp4'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=blue:size=160x90:rate=30','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','0.2','-c:v','libx264','-threads','2','-c:a','aac',source])
            spec=dict(SPECS[0],shots=[1,1],caption=['하나','둘'])
            result=render(spec,[{'id':'source','path':str(source)}],{'quality':'draft','music':False,'words':[{'start':.1,'end':1.5,'text':'경로 검증'}]},folder/'result.mp4',lambda *_:None)
            self.assertTrue(result['validation']['passed'])
            self.assertEqual(result['validation']['duration'],2)
    def test_cancel_terminates_child_process(self):
        STATE.cancel=lambda:True
        try:
            with self.assertRaises(Cancelled):run(['ffmpeg','-v','error','-re','-f','lavfi','-i','color=size=160x90','-t','60','-f','null','-'])
        finally:STATE.cancel=None
