"""Start a single-host renderer, requiring explicit opt-in for public browser workspaces."""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def configure():
    accounts = json.loads(os.environ.get('AUTO_SHORTS_ACCOUNTS', '{}'))
    public_access=os.environ.get('AUTO_SHORTS_ACCESS_MODE') == 'public'
    if (not isinstance(accounts, dict) or (not accounts and not public_access) or
            any(not isinstance(name, str) or not name.strip() or not isinstance(token, str) or
                len(token) < 32 for name, token in accounts.items()) or
            len(set(accounts.values())) != len(accounts)):
        raise ValueError('Configure personal AUTO_SHORTS_ACCOUNTS keys or explicitly set AUTO_SHORTS_ACCESS_MODE=public')
    if len(os.environ.get('AUTO_SHORTS_TRANSFER_SECRET', '')) < 32:
        raise ValueError('AUTO_SHORTS_TRANSFER_SECRET must contain at least 32 random characters')
    from app.transfers import origin
    public = origin()
    if not public.startswith('https://'):
        raise ValueError('AUTO_SHORTS_PUBLIC_URL must be the HTTPS origin of this rendering service')
    origins = list(filter(None, os.environ.get('AUTO_SHORTS_ORIGINS', '').split(',')))
    if not origins:
        raise ValueError('AUTO_SHORTS_ORIGINS must contain the Vercel site origin')
    for value in origins:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or
                parsed.path or parsed.query or parsed.fragment or '*' in value):
            raise ValueError('Each frontend origin must be an exact HTTPS origin without a path')
    hosts = [urlsplit(public).hostname, 'healthcheck.railway.app']
    hosts.extend(urlsplit(value).hostname for value in origins)
    os.environ['AUTO_SHORTS_HOSTS'] = ','.join(hosts)
    os.environ['AUTO_SHORTS_SECURE_COOKIE'] = '1'
    os.environ.setdefault('AUTO_SHORTS_EMBEDDED_WORKER', '1')
    port = int(os.environ.get('PORT', '8080'))
    if not 1 <= port <= 65535:
        raise ValueError('PORT must be between 1 and 65535')
    return port


if __name__ == '__main__':
    try:
        port = configure()
    except (ValueError, TypeError) as exc:
        raise SystemExit(f'Invalid deployment configuration: {exc}') from exc
    import uvicorn
    # URLs contain scoped file tickets; do not put them into access logs.
    uvicorn.run('app.server:app', host='0.0.0.0', port=port, access_log=False)
