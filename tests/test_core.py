import copy, json, os, tempfile, unittest
from pathlib import Path
from pydantic import ValidationError
from app.schema import SPECS, Template, Edit
from app.compose import composition, checklist
from app import store
from app.providers import capabilities

class Contracts(unittest.TestCase):
    def test_eight_original_templates(self):
        self.assertEqual([t['duration'] for t in SPECS],[18,24,15,18,24,20,30,24])
        self.assertEqual(len({t['motion'] for t in SPECS}),8)
        for spec in SPECS:self.assertEqual(sum(spec['shots']),spec['duration'])
    def test_schema_rejects_broken_timing(self):
        spec=copy.deepcopy(SPECS[0]);spec['shots'][0]=99
        with self.assertRaises(ValidationError):Template.model_validate(spec)
    def test_scene_ownership_and_boundaries(self):
        options=Edit(template_id='flash-hook',clip_ids=['mine'],scenes=[{'clip_id':'other','start':0,'duration':1}]).model_dump()
        with self.assertRaises(ValueError):composition(options,[{'id':'mine','duration':1}])
        options['scenes'][0].update(clip_id='mine',start=1)
        with self.assertRaises(ValueError):composition(options,[{'id':'mine','duration':1}])
    def test_short_clip_plan_and_copy(self):
        opts=Edit(template_id='flash-hook',clip_ids=['a'],brand='브랜드',hook='긴 문구'*40,cta='확인',color='#123456').model_dump()
        p=composition(opts,[{'id':'a','duration':.15}])
        self.assertEqual(p['scenes'][0]['start'],0);self.assertEqual(p['scenes'][0]['text'],opts['hook'])
        self.assertEqual(p['scenes'][-1]['text'],'확인');self.assertEqual(p['spec']['color'],'#123456')
        self.assertEqual(p,composition(opts,[{'id':'a','duration':.15}]))
    def test_disclosure_requires_manual_confirmation(self):
        with self.assertRaises(ValidationError):Edit(template_id='flash-hook',insert_disclosure=True,disclosure='광고')
    def test_subtitles_require_ordered_real_times(self):
        with self.assertRaises(ValidationError):Edit(template_id='flash-hook',words=[{'start':1,'end':2,'text':'하나'},{'start':1.5,'end':3,'text':'둘'}])
        with self.assertRaises(ValidationError):Edit(template_id='flash-hook',words=[{'start':float('nan'),'end':2,'text':'하나'}])
    def test_ad_flags_do_not_generate_claims(self):
        self.assertEqual(checklist({'hook':'100% 보장'})['flags'],['100%','보장'])
    def test_platform_checklists_are_specific(self):
        self.assertTrue(any('유료 프로모션' in s for s in checklist({'platform':'youtube'})['items']))
        self.assertTrue(any('파트너십' in s for s in checklist({'platform':'instagram'})['items']))
        self.assertTrue(any('콘텐츠 공개' in s for s in checklist({'platform':'tiktok'})['items']))
    def test_disabled_providers_are_explicit(self):
        from unittest.mock import patch
        with patch.dict(os.environ,{'AUTO_SHORTS_ASR_MODEL':'','OPENAI_API_KEY':''}):
            self.assertFalse(capabilities()['asr']);self.assertFalse(capabilities()['vision'])

class Queue(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=store.DATA;store.DATA=Path(self.tmp.name);store.init();self.owner,self.token=store.account()
    def tearDown(self):store.DATA=self.old;self.tmp.cleanup()
    def test_account_isolation_and_cookie_recovery(self):
        self.assertEqual(store.account(self.token),(self.owner,None));other,_=store.account()
        jid=store.enqueue(self.owner,'render',{})
        self.assertIsNone(store.job(other,jid));self.assertEqual(len(store.jobs(self.owner)),1)
    def test_single_worker_claim_and_retry_recovery(self):
        jid=store.enqueue(self.owner,'render',{});first=store.claim('worker1');self.assertEqual(first['id'],jid);self.assertIsNone(store.claim('worker2'))
        with store.transaction() as d:d.execute('UPDATE jobs SET lease=0 WHERE id=?',(jid,))
        recovered=store.claim('worker2');self.assertEqual(recovered['id'],jid)
        store.finish(jid,'worker1','done','stale worker')
        self.assertEqual(store.job(self.owner,jid)['status'],'running')
        store.finish(jid,'worker2','done','complete',{'passed':True})
        self.assertEqual(store.job(self.owner,jid)['attempts'],2)
    def test_cancel_and_expiry(self):
        jid=store.enqueue(self.owner,'render',{})
        with store.transaction() as d:d.execute('UPDATE jobs SET cancel=1 WHERE id=?',(jid,))
        self.assertIsNone(store.claim('worker'));self.assertEqual(store.job(self.owner,jid)['status'],'cancelled')
        work=store.owner_dir(self.owner)/'jobs'/jid;work.mkdir(parents=True);(work/'output.mp4').write_bytes(b'123')
        with store.transaction() as d:d.execute('UPDATE jobs SET updated=0 WHERE id=?',(jid,))
        store.cleanup();self.assertIsNone(store.job(self.owner,jid));self.assertFalse(work.exists())
    def test_path_traversal_blocked(self):
        with self.assertRaises(ValueError):store.owner_dir('../escape')
if __name__=='__main__':unittest.main()

class AtomicQueue(unittest.TestCase):
    setUp = Queue.setUp
    tearDown = Queue.tearDown
    def test_batch_admission_rolls_back(self):
        for i in range(26):store.enqueue(self.owner,'preview',{})
        with self.assertRaises(ValueError):store.enqueue_many(self.owner,[('render',{})]*8)
        self.assertEqual(len(store.jobs(self.owner)),26)
    def test_stale_worker_cannot_publish(self):
        jid=store.enqueue(self.owner,'render',{});store.claim('first')
        with store.transaction() as d:d.execute('UPDATE jobs SET lease=0 WHERE id=?',(jid,))
        store.claim('second');source=store.DATA/'attempt.mp4';target=store.DATA/'final.mp4';source.write_bytes(b'test')
        self.assertFalse(store.finish(jid,'first','done','old',{},(source,target)))
        self.assertFalse(target.exists());self.assertTrue(source.exists())
        self.assertTrue(store.finish(jid,'second','done','new',{},(source,target)))
        self.assertEqual(target.read_bytes(),b'test')
    def test_cancelled_worker_cannot_publish(self):
        jid=store.enqueue(self.owner,'render',{});store.claim('one')
        with store.transaction() as d:d.execute('UPDATE jobs SET cancel=1 WHERE id=?',(jid,))
        self.assertFalse(store.finish(jid,'one','done','late'))
