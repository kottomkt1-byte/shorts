import {spawnSync} from 'node:child_process';
import {cpSync, mkdirSync, rmSync, writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

process.chdir(fileURLToPath(new URL('..', import.meta.url)));
const backend = new URL(process.env.SHORTS_BACKEND_ORIGIN || 'invalid:');
if (backend.protocol !== 'https:' || !backend.hostname || backend.username || backend.password ||
    backend.pathname !== '/' || backend.search || backend.hash) {
  throw Error('Set SHORTS_BACKEND_ORIGIN to the HTTPS origin of the running renderer before deploying.');
}
const build = spawnSync('npm', ['run', 'build'], {stdio: 'inherit'});
if (build.status !== 0) process.exit(build.status || 1);
rmSync('.vercel/output', {recursive: true, force: true});
mkdirSync('.vercel/output/static', {recursive: true});
cpSync('dist', '.vercel/output/static', {recursive: true});
cpSync('web/covers', '.vercel/output/static/covers', {recursive: true});
writeFileSync('.vercel/output/config.json', JSON.stringify({
  version: 3,
  routes: [
    {src: '/api/(.*)', dest: `${backend.origin}/api/$1`, headers: {'Cache-Control': 'no-store'}},
    {handle: 'filesystem'},
    {src: '/(.*)', dest: '/index.html'}
  ]
}, null, 2) + '\n');
console.log('Prepared Vercel static editor and API proxy. Video transfers use the renderer directly.');
