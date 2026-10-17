import {spawn} from 'node:child_process';
const children = [spawn(process.env.PYTHON || 'python', ['-m','uvicorn','app.server:app','--host','127.0.0.1','--port','8787'],{stdio:'inherit'}),spawn(process.execPath,['node_modules/vite/bin/vite.js'],{stdio:'inherit'})];
let stopping=false;
function stop(code=0){if(stopping)return;stopping=true;for(const child of children)child.kill('SIGTERM');process.exitCode=code;}
for(const child of children){child.on('error',e=>{console.error(e);stop(1)});child.on('exit',code=>stop(code||0));}
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>stop());
