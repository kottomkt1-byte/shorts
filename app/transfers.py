"""Scoped, expiring file URLs for a frontend hosted separately from the renderer."""
import base64
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import urlencode, urlsplit

from fastapi import HTTPException
from . import store


def origin():
    value = os.environ.get('AUTO_SHORTS_PUBLIC_URL', '').rstrip('/')
    if not value:
        return ''
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
            parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('AUTO_SHORTS_PUBLIC_URL must be a server origin without a path')
    return value


def _key():
    value = os.environ.get('AUTO_SHORTS_TRANSFER_SECRET', '')
    if len(value) < 32:
        raise HTTPException(503, '파일 전송 인증 설정이 필요합니다.')
    return value.encode()


def _account_version(owner):
    accounts = json.loads(os.environ.get('AUTO_SHORTS_ACCOUNTS', '{}'))
    if not accounts and os.environ.get('AUTO_SHORTS_ACCESS_MODE') == 'public':
        with store.connect() as db:
            row=db.execute('SELECT token FROM users WHERE id=?',(owner,)).fetchone()
        if row:return row['token']
    for name, secret in accounts.items():
        if hashlib.sha256(name.encode()).hexdigest()[:32] == owner:
            return hashlib.sha256(secret.encode()).hexdigest()
    raise HTTPException(401, '사용할 수 없는 작업 공간입니다.')


def _encode(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def issue(owner, action, resource):
    # Stable within five minutes so polling does not continuously replace media elements.
    lifetime = 600 if action == 'upload' else 7200
    payload = {'owner': owner, 'action': action, 'resource': resource,
               'expires': int(time.time()) // 300 * 300 + lifetime,
               'account_version': _account_version(owner)}
    body = _encode(json.dumps(payload, separators=(',', ':'), sort_keys=True).encode())
    signature = _encode(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
    return body + '.' + signature


def verify(ticket, action, resource):
    try:
        if len(ticket) > 2048 or not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', ticket):
            raise ValueError('format')
        body, signature = ticket.split('.')
        expected = _encode(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError('signature')
        payload = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
        owner = payload['owner']
        if (payload['action'] != action or payload['resource'] != resource or
                payload['expires'] <= time.time() or not re.fullmatch(r'[a-f0-9]{32}', owner)):
            raise ValueError('scope')
        if not hmac.compare_digest(payload['account_version'], _account_version(owner)):
            raise ValueError('account changed')
        return owner
    except (ValueError, KeyError, TypeError, UnicodeError, HTTPException) as exc:
        raise HTTPException(401, '파일 링크가 만료되었거나 유효하지 않습니다. 새로고침 후 다시 시도하세요.') from exc


def file_url(owner, action, resource, *, attachment=False):
    query = {'ticket': issue(owner, action, resource)}
    if attachment:
        query['attachment'] = 'true'
    return f'{origin()}/transfer/{action}/{resource}?' + urlencode(query)
