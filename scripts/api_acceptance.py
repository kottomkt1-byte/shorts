"""Real HTTP upload + custom BGM + batch rendering + preview authorization checks."""
import json,time,sys
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
def main():
    with httpx.Client(base_url='http://127.0.0.1:8787',trust_env=False,timeout=60) as c:
        def wait(ids):
            deadline=time.monotonic()+1200
            while time.monotonic()<deadline:
                states=[c.get('/api/jobs/'+jid).json() for jid in ids]
                if any(j['status']=='failed' for j in states):raise AssertionError(states)
                if all(j['status']=='done' for j in states):return states
                time.sleep(1)
            raise TimeoutError(states)
        with open(ROOT/'evidence/renders/source-0.mp4','rb') as f:
            u=c.post('/api/upload',files={'files':('speech.mp4',f,'video/mp4')});u.raise_for_status();clip=u.json()['files'][0]
        with open(ROOT/'assets/music/pulse.wav','rb') as f:
            u=c.post('/api/upload?kind=music',files={'files':('licensed-test-bgm.wav',f,'audio/wav')});u.raise_for_status();music=u.json()['files'][0]
        wait([clip['job_id'],music['job_id']])
        response=c.post('/api/batch',json={'template_id':'flash-hook','clip_ids':[clip['id']],'music_id':music['id'],'brand':'배치 검증','original_audio':True})
        response.raise_for_status();ids=[j['id'] for j in response.json()['jobs']];assert len(ids)==8
        done=wait(ids);assert len({j['template_id'] for j in done})==8
        reports=[]
        for j in done:
            result=j['result'];assert result['validation']['passed'];assert result['width']==1080
            response=c.get(result['file']);response.raise_for_status();assert len(response.content)==result['size']
            assert '_music_path' not in result['plan']['options']
            reports.append({'template_id':j['template_id'],'bytes':len(response.content),'validation':result['validation']})
        with httpx.Client(base_url='http://127.0.0.1:8787',trust_env=False) as stranger:
            assert stranger.get(done[0]['result']['file']).status_code==404
        report={'custom_bgm_upload':True,'batch_size':8,'downloaded':reports,'cross_account_download':'blocked'}
        (ROOT/'evidence/api-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print('PASS: custom BGM + 8 full batch exports + downloads + ownership')
if __name__=='__main__':main()
