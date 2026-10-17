import os, tempfile, unittest, json
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import store
from app.server import app
from app.media import run

class API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.old=store.DATA;store.DATA=Path(cls.tmp.name);store.init()
        cls.env=patch.dict(os.environ,{'AUTO_SHORTS_EMBEDDED_WORKER':'0','OPENAI_API_KEY':'','AUTO_SHORTS_ASR_MODEL':''});cls.env.start()
        cls.client=TestClient(app);cls.client.__enter__()
        cls.sample=(store.DATA/'sample.mp4').read_bytes()
    @classmethod
    def tearDownClass(cls):cls.client.__exit__(None,None,None);cls.env.stop();store.DATA=cls.old;cls.tmp.cleanup()
    def test_upload_durable_and_owned(self):
        c=self.client;r=c.post('/api/upload',files={'files':('sample.mp4',self.sample,'video/mp4')});self.assertEqual(r.status_code,201)
        info=r.json()['files'][0];self.assertNotIn('path',info)
        self.assertEqual(c.get('/api/jobs/'+info['job_id']).status_code,200)
        with TestClient(app) as other:
            self.assertEqual(other.get('/api/jobs/'+info['job_id']).status_code,404)
            self.assertEqual(other.get('/api/media/'+info['id']+'/file').status_code,404)
            self.assertEqual(other.post('/api/render',json={'template_id':'flash-hook','clip_ids':[info['id']]}).status_code,404)
        self.assertEqual(c.get('/api/jobs/'+info['job_id']+'/file').status_code,409)
    def test_invalid_upload_rolls_back(self):
        before=len(self.client.get('/api/media').json())
        r=self.client.post('/api/upload',files=[('files',('ok.mp4',self.sample)),('files',('bad.mp4',b'not a movie'))]);self.assertEqual(r.status_code,400)
        self.assertEqual(len(self.client.get('/api/media').json()),before)
    def test_missing_asr_not_faked(self):
        self.assertEqual(self.client.post('/api/asr/missing').status_code,503)
        self.assertEqual(self.client.post('/api/vision/missing').status_code,503)
    def test_sample_plan_and_private_presets(self):
        options={'template_id':'pov-story','color':'#abcdef','hook':'확인할 문구'}
        r=self.client.post('/api/plan',json=options);self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['plan']['spec']['color'],'#abcdef')
        self.assertEqual(r.json()['plan']['scenes'][0]['text'],'확인할 문구')
        r=self.client.post('/api/presets',json={'name':'내 스타일','options':options});self.assertEqual(r.status_code,201)
        with TestClient(app) as other:self.assertEqual(other.get('/api/presets').json(),[])
    def test_csrf_and_traversal(self):
        self.assertEqual(self.client.post('/api/preview',json={'template_id':'flash-hook'},headers={'Origin':'https://evil.test'}).status_code,403)
        self.assertEqual(self.client.get('/api/media/..%2F..%2Fetc%2Fpasswd/file').status_code,404)
    def test_cancel_and_retry_are_owned(self):
        r=self.client.post('/api/preview',json={'template_id':'flash-hook'});jid=r.json()['id']
        self.assertEqual(self.client.post('/api/jobs/'+jid+'/cancel').status_code,200)
        store.claim('test')
        self.assertEqual(self.client.get('/api/jobs/'+jid).json()['status'],'cancelled')
        r=self.client.post('/api/jobs/'+jid+'/retry');self.assertEqual(r.status_code,202);self.assertNotEqual(r.json()['id'],jid)
    def test_size_and_extension_limits(self):
        self.assertEqual(self.client.post('/api/upload',files={'files':('x.exe',b'x')}).status_code,400)
        with patch('app.server.MAX_FILE',8):
            self.assertEqual(self.client.post('/api/upload',files={'files':('x.mp4',self.sample)}).status_code,413)
    def test_empty_final_export_rejected(self):
        self.assertEqual(self.client.post('/api/render',json={'template_id':'flash-hook'}).status_code,400)

    def test_configured_account_cookie_and_isolation(self):
        with patch.dict(os.environ,{'AUTO_SHORTS_ACCOUNTS':json.dumps({'alice':'a-secret','bob':'b-secret'})}):
            with TestClient(app) as alice,TestClient(app) as bob:
                self.assertEqual(alice.get('/api/config').status_code,401)
                self.assertEqual(alice.get('/api/config',headers={'Authorization':'Bearer a-secret'}).status_code,200)
                self.assertEqual(alice.get('/api/config').status_code,200)
                r=alice.post('/api/preview',json={'template_id':'flash-hook'});self.assertEqual(r.status_code,202)
                bob.get('/api/config',headers={'Authorization':'Bearer b-secret'})
                self.assertEqual(bob.get('/api/jobs/'+r.json()['id']).status_code,404)
                self.assertEqual(bob.get('/api/jobs').json(),[])
    def test_unknown_host_rejected(self):
        self.assertEqual(self.client.get('/api/config',headers={'Host':'evil.test'}).status_code,400)
