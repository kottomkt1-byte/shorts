"""Real separate worker, cancellation, kill/recovery and upload retry acceptance."""
import json, os, signal, subprocess, sys, tempfile, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import store
from app.schema import Edit
from app.compose import composition
from app.media import inspect

ROOT=Path(__file__).resolve().parents[1]
def main():
    report=[]
    with tempfile.TemporaryDirectory() as tmp:
        store.DATA=Path(tmp);store.init();owner,_=store.account();folder=store.owner_dir(owner)/'media';folder.mkdir()
        source=folder/'sample.mp4';source.write_bytes((ROOT/'evidence/renders/source-0.mp4').read_bytes())
        info={'id':'source','name':'source.mp4','path':str(source),'size':source.stat().st_size,'ready':False,**inspect(source)}
        jid=store.register_uploads(owner,'video',[info])[0]
        env=dict(os.environ,AUTO_SHORTS_DATA=tmp,AUTO_SHORTS_EMBEDDED_WORKER='0')
        log=open(ROOT/'evidence/worker-run.log','w')
        worker=subprocess.Popen([sys.executable,'-m','app.worker'],env=env,cwd=ROOT,stdout=log,stderr=log)
        def wait(jid,states,seconds=60):
            until=time.monotonic()+seconds
            while time.monotonic()<until:
                row=store.job(owner,jid)
                if row['status'] in states:return row
                time.sleep(.2)
            raise AssertionError(store.job(owner,jid))
        try:
            assert wait(jid,['done','failed'])['status']=='done';assert store.media(owner,'source')[0]['ready'];report.append('external worker prepares proxy and analysis')
            options=Edit(template_id='flash-hook',clip_ids=['source'],quality='full').model_dump();media=store.media(owner)
            plan=composition(options,media)
            render=store.enqueue(owner,'render',{'plan':plan,'media':media});wait(render,['running'])
            time.sleep(.4)
            with store.transaction() as db:db.execute('UPDATE jobs SET cancel=1 WHERE id=?',(render,))
            assert wait(render,['cancelled','failed'],10)['status']=='cancelled'
            assert not (store.owner_dir(owner)/'jobs'/render/'output.mp4').exists();report.append('running FFmpeg cancellation prevents download')
            crashed=store.enqueue(owner,'render',{'plan':plan,'media':media});wait(crashed,['running']);time.sleep(.4)
            worker.kill();worker.wait(10)
            # Advance lease expiration instead of sleeping the production 90-second lease.
            with store.transaction() as db:db.execute('UPDATE jobs SET lease=0 WHERE id=?',(crashed,))
            worker=subprocess.Popen([sys.executable,'-m','app.worker'],env=env,cwd=ROOT,stdout=log,stderr=log)
            row=wait(crashed,['done','failed'],180);assert row['status']=='done',row
            assert row['attempts']==2;assert json.loads(row['result'])['validation']['passed'];report.append('killed worker recovery rerenders and validates (lease expiry accelerated)')
            failed=store.enqueue(owner,'prepare',{'media_id':'missing'})
            assert wait(failed,['failed'])['status']=='failed';report.append('missing source is an explicit failed job')
        finally:
            worker.terminate()
            try:worker.wait(15)
            except subprocess.TimeoutExpired:worker.kill();worker.wait()
            log.close()
    (ROOT/'evidence/worker-report.json').write_text(json.dumps({'checks':report},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
