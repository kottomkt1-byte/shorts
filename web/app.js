'use strict';
const $ = id => document.getElementById(id);
const state = {templates:[], selected:null, category:'전체', files:[], working:false, timer:null};
const el = (tag, cls, text) => {const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
const durationLabel = s => `${s}초`;

async function load(){
  try{const r=await fetch('/api/templates'); if(!r.ok) throw Error('템플릿 응답 오류');state.templates=await r.json(); state.selected=state.templates[0]; renderFilters();renderCards();select(state.selected.id)}
  catch(err){$('cards').textContent='템플릿을 불러오지 못했습니다. '+err.message;}
}
function renderFilters(){
 const div=$('filters');div.replaceChildren();
 for(const cat of ['전체',...new Set(state.templates.map(x=>x.category))]){
  const btn=el('button',cat===state.category?'active':'',cat);btn.type='button';btn.addEventListener('click',()=>{state.category=cat;renderFilters();renderCards()});div.appendChild(btn);
 }
}
function renderCards(){
 const div=$('cards');div.replaceChildren();
 const data=state.templates.filter(t=>state.category==='전체'||t.category===state.category);
 $('count').textContent=`${data.length} STYLES`;
 for(const t of data){
  const btn=el('button',`card ${state.selected?.id===t.id?'active':''}`);btn.type='button';
  const img=el('img');img.src=`/covers/${t.id}.jpg`;img.alt=t.name+' 템플릿 이미지';
  const copy=el('div');copy.append(el('span','card-type',t.category),el('h3','',t.name),el('p','',t.subtitle),el('span','card-duration',durationLabel(t.duration)));
  btn.append(img,copy);btn.addEventListener('click',()=>select(t.id));div.appendChild(btn);
 }
}
function select(id){
 state.selected=state.templates.find(t=>t.id===id);const t=state.selected;
 $('selectedImage').style.backgroundImage=`url('/covers/${t.id}.jpg')`;
 $('selectedName').textContent=t.name;$('selectedDesc').textContent=t.subtitle;
 $('selectedTags').replaceChildren(...t.tags.map(x=>el('span','',x)));
 $('duration').textContent=`${t.duration}초 / ${t.shots.length}장면`;
 $('scenes').replaceChildren();
 t.shots.forEach((sec,i)=>{
  const line=el('div','scene');line.append(el('span','scene-num',String(i+1).padStart(2,'0')));
  const inp=el('input','scene-input');inp.type='text';inp.maxLength=120;inp.value=t.caption[i];inp.setAttribute('aria-label',`${i+1}번 장면 문구`);
  line.append(inp,el('span','scene-time',sec+'s'));$('scenes').appendChild(line);
 });
 $('hook').value='';$('cta').value=t.category==='제품 광고'?'자세한 정보는 프로필에서':'';
 renderCards();
}
function addFilesUI(){
 const list=$('filesList');list.replaceChildren();
 for(const f of state.files){const row=el('div','file-line');row.append(el('b','',f.name),el('span','',`${f.duration}초 · 업로드 완료`));list.appendChild(row)}
 $('renderBtn').disabled=!state.files.length||state.working;
 $('renderBtn').innerHTML=state.files.length?'<span>▶</span> 자동 숏폼 영상 만들기 <b>↗</b>':'<span>▶</span> 영상 업로드 후 렌더링 가능 <b>↗</b>';
}
async function upload(files){
 const allowed=['mp4','mov','m4v','webm','mkv'];const valid=[...files].filter(f=>allowed.includes(f.name.split('.').pop().toLowerCase()));
 if(!valid.length){alert('MP4, MOV, M4V, WEBM, MKV 파일을 선택해 주세요.');return;}
 if(valid.some(f=>f.size>500*1024*1024)){alert('파일당 최대 500MB까지만 가능합니다.');return;}
 const fd=new FormData();valid.forEach(f=>fd.append('files',f,f.name));
 const btn=$('renderBtn');btn.disabled=true;btn.textContent='영상 업로드 중...';
 try{const r=await fetch('/api/upload',{method:'POST',body:fd});const data=await r.json();if(!r.ok)throw Error(data.detail||'업로드 실패');state.files.push(...data.files);addFilesUI()}
 catch(err){alert('업로드 오류: '+err.message);addFilesUI()}
}
async function startRender(){
 if(state.working||!state.files.length)return;
 state.working=true;addFilesUI();$('renderBtn').textContent='렌더링 중...';
 $('status').hidden=false;$('result').hidden=true;$('statusTitle').textContent='영상 작업 진행 중';$('statusMessage').textContent='렌더링 작업을 생성하고 있습니다.';
 try{
  const req={template_id:state.selected.id,clip_ids:state.files.map(f=>f.id), brand:$('brand').value.trim(),hook:$('hook').value.trim(),cta:$('cta').value.trim(),
   captions:[...$('scenes').querySelectorAll('input')].map(x=>x.value.trim()),quality:document.querySelector('input[name=quality]:checked').value,music:$('music').checked};
  const r=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(req)});
  const job=await r.json();if(!r.ok)throw Error(job.detail||'렌더링 요청 실패');
  poll(job.id);
 }catch(err){fail(err.message)}
}
async function poll(id){
 try{
  const r=await fetch('/api/jobs/'+encodeURIComponent(id));const j=await r.json();
  if(!r.ok)throw Error(j.detail||'작업 조회 실패');
  $('statusPercent').textContent=`${j.progress||0}%`;$('progressBar').style.width=`${j.progress||0}%`;$('statusMessage').textContent=j.message||'';
  if(j.status==='done'){
   $('statusTitle').textContent='영상 제작 완료';const video=$('preview');video.src=j.file;video.load();
   $('download').href=j.file;$('download').download=`auto-shorts-${state.selected.id}.mp4`;
   $('result').hidden=false;state.working=false;addFilesUI();return;
  }
  if(j.status==='failed')throw Error(j.message||'알 수 없는 오류');
  state.timer=setTimeout(()=>poll(id),1500);
 }catch(err){fail(err.message)}
}
function fail(msg){state.working=false;addFilesUI();$('statusTitle').textContent='작업 실패';$('statusMessage').textContent=msg;$('statusPercent').textContent='!';}
function wire(){
 $('files').addEventListener('change',e=>{upload(e.target.files);e.target.value=''});
 const drop=$('dropzone');
 drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('drag')});
 drop.addEventListener('dragleave',()=>drop.classList.remove('drag'));
 drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('drag');upload(e.dataTransfer.files)});
 $('renderBtn').addEventListener('click',startRender);
}
wire();load();
