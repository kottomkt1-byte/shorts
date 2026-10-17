import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import store, transfers
from app.server import app
from scripts.serve import configure


class HostedTransfers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data = store.DATA
        store.DATA = Path(self.tmp.name)
        self.accounts = {'alice': 'alice-key-' + 'a' * 40, 'bob': 'bob-key-' + 'b' * 40}
        self.owner = hashlib.sha256(b'alice').hexdigest()[:32]
        self.env = patch.dict(os.environ, {
            'AUTO_SHORTS_PUBLIC_URL': 'https://testserver',
            'AUTO_SHORTS_ORIGINS': 'https://studio.example',
            'AUTO_SHORTS_TRANSFER_SECRET': 'transfer-secret-' + 's' * 40,
            'AUTO_SHORTS_ACCOUNTS': json.dumps(self.accounts),
            'AUTO_SHORTS_SECURE_COOKIE': '1',
            'AUTO_SHORTS_EMBEDDED_WORKER': '0',
            'AUTO_SHORTS_ACCESS_MODE': 'private',
        })
        self.env.start()
        self.alice = TestClient(app, base_url='https://testserver')
        self.alice.__enter__()
        self.alice.get('/api/config', headers={'Authorization': 'Bearer ' + self.accounts['alice']})
        self.direct = TestClient(app, base_url='https://testserver')
        self.origin = {'Origin': 'https://studio.example'}

    def tearDown(self):
        self.direct.close()
        self.alice.__exit__(None, None, None)
        self.env.stop()
        store.DATA = self.old_data
        self.tmp.cleanup()

    def test_anonymous_cannot_issue_ticket_and_invalid_ticket_rejected_before_body(self):
        self.assertEqual(self.direct.post('/api/transfer', json={'kind': 'video'}).status_code, 401)
        r = self.direct.post('/transfer/upload/video?ticket=invalid', headers=self.origin,
                             content=b'invalid multipart body')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers['access-control-allow-origin'], 'https://studio.example')

    def test_cross_origin_upload_media_range_and_account_isolation(self):
        ticket = self.alice.post('/api/transfer', json={'kind': 'video'}, headers=self.origin).json()['url']
        preflight = self.direct.options(ticket, headers={**self.origin, 'Access-Control-Request-Method': 'POST',
                                                         'Access-Control-Request-Headers': 'Content-Type'})
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(preflight.headers['access-control-allow-origin'], 'https://studio.example')
        source = (store.DATA / 'sample.mp4').read_bytes()
        uploaded = self.direct.post(ticket, files={'files': ('sample.mp4', source)}, headers=self.origin)
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        self.assertFalse(self.direct.cookies)
        mid = uploaded.json()['files'][0]['id']
        store.update_media(self.owner, mid, {'ready': True})
        media = self.alice.get('/api/media').json()[0]
        self.assertEqual(urlsplit(media['url']).netloc, 'testserver')
        partial = self.direct.get(media['url'], headers={**self.origin, 'Range': 'bytes=0-99'})
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.content, source[:100])
        self.assertIn('no-store', partial.headers['cache-control'])
        self.direct.get('/api/config', headers={'Authorization': 'Bearer ' + self.accounts['bob']})
        self.assertEqual(self.direct.get('/api/media').json(), [])
        self.assertEqual(self.direct.get('/api/media/' + mid + '/file').status_code, 404)
        self.assertEqual(self.direct.get(media['url'].replace(mid, '0' * 32)).status_code, 401)

    def test_ticket_expiry_scope_signature_and_revoked_account(self):
        with patch('app.transfers.time.time', return_value=1000):
            ticket = transfers.issue(self.owner, 'upload', 'video')
        with patch('app.transfers.time.time', return_value=1100):
            self.assertEqual(transfers.verify(ticket, 'upload', 'video'), self.owner)
            for action, resource in [('upload', 'music'), ('media', 'video')]:
                with self.assertRaises(HTTPException):
                    transfers.verify(ticket, action, resource)
            with self.assertRaises(HTTPException):
                transfers.verify(ticket + 'x', 'upload', 'video')
            with patch.dict(os.environ, {'AUTO_SHORTS_ACCOUNTS': json.dumps({'alice': 'rotated-key-' + 'z' * 40})}):
                with self.assertRaises(HTTPException):
                    transfers.verify(ticket, 'upload', 'video')
        with patch('app.transfers.time.time', return_value=1600):
            with self.assertRaises(HTTPException):
                transfers.verify(ticket, 'upload', 'video')

    def test_foreign_origin_and_logout(self):
        ticket = self.alice.post('/api/transfer', json={'kind': 'video'}, headers=self.origin).json()['url']
        self.assertEqual(self.direct.options(ticket, headers={'Origin': 'https://foreign.example',
                                                              'Access-Control-Request-Method': 'POST'}).status_code, 403)
        self.assertEqual(self.direct.post(ticket, headers={'Origin': 'https://foreign.example'}).status_code, 403)
        self.assertTrue(self.alice.get('/api/config').json()['workspace']['team_login'])
        self.assertEqual(self.alice.post('/api/logout', headers=self.origin).status_code, 200)
        self.assertEqual(self.alice.get('/api/config').status_code, 401)

    def test_hosted_startup_requires_credentials_and_exact_https_origins(self):
        with patch.dict(os.environ, {}, clear=False):
            self.assertEqual(configure(), int(os.environ.get('PORT', '8080')))
        for key, value in [('AUTO_SHORTS_ACCOUNTS', '{}'), ('AUTO_SHORTS_TRANSFER_SECRET', 'short'),
                           ('AUTO_SHORTS_ORIGINS', 'https://*.vercel.app'),
                           ('AUTO_SHORTS_PUBLIC_URL', 'http://insecure.example')]:
            with patch.dict(os.environ, {key: value}):
                with self.assertRaises(ValueError):
                    configure()

    def test_health_check_does_not_expose_workspace(self):
        self.assertEqual(self.direct.get('/healthz').json(), {'status': 'ok'})

    def test_public_mode_without_keys_preserves_browser_isolation(self):
        with patch.dict(os.environ, {'AUTO_SHORTS_ACCOUNTS':'{}','AUTO_SHORTS_ACCESS_MODE':'public'}):
            self.assertEqual(configure(), int(os.environ.get('PORT', '8080')))
            first=self.direct.get('/api/config').json()['workspace']
            self.assertFalse(first['team_login'])
            ticket=self.direct.post('/api/transfer', json={'kind':'video'}, headers=self.origin).json()['url']
            with TestClient(app,base_url='https://testserver') as other:
                self.assertNotEqual(first['id'],other.get('/api/config').json()['workspace']['id'])
                uploaded=other.post(ticket,headers=self.origin,files={'files':('sample.mp4',(store.DATA/'sample.mp4').read_bytes())})
                self.assertEqual(uploaded.status_code,201)
                self.assertEqual(other.get('/api/media').json(),[])
            self.assertEqual(len(self.direct.get('/api/media').json()),1)

