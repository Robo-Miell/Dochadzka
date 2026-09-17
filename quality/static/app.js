const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state={user:null,jobs:[],users:[],view:null,presetJob:null};

async function api(url,opt={}){
  url='/quality'+url;
  opt.headers={...(opt.headers||{}),'Content-Type':'application/json',Authorization:'Bearer '+(localStorage.getItem('dochadzka_token')||'')};
  const r=await fetch(url,opt); let d={};
  try{d=await r.json()}catch{}
  if(!r.ok) throw Object.assign(new Error(d.error||d.detail||`HTTP ${r.status}`),{data:d,status:r.status});
  return d;
}
async function downloadFile(url){
  try{
    const r=await fetch('/quality'+url,{headers:{Authorization:'Bearer '+(localStorage.getItem('dochadzka_token')||'')}});
    if(!r.ok){let d={};try{d=await r.json()}catch{};throw new Error(d.error||d.detail||`HTTP ${r.status}`)}
    const blob=await r.blob();
    let name='report';
    const cd=r.headers.get('Content-Disposition')||'';
    const m=cd.match(/filename="?([^";]+)"?/i); if(m) name=m[1];
    const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(a.href),1500);
  }catch(e){toast(e.message,'error')}
}
function toast(msg,type='success'){const d=document.createElement('div');d.className='toast '+type;d.textContent=msg;$('#toast').appendChild(d);setTimeout(()=>d.remove(),4200)}
function setTitle(a,b=''){ $('#pageTitle').textContent=a; $('#pageSubtitle').textContent=b }
function showLogin(){location.replace('/?next=quality')}
function navItems(){return state.user.role==='admin'?[['dashboard','Dashboard'],['new','＋ Nový záznam'],['jobs','Zákazky'],['records','Záznamy']]:[['new','＋ Nový záznam'],['mine','Moje záznamy']]}
function showApp(){$('#loginScreen').classList.add('hidden');$('#appShell').classList.remove('hidden');$('#userBadge').innerHTML=`<b>${esc(state.user.display_name)}</b><br>${state.user.role.toUpperCase()}`;renderNav();go(state.user.role==='admin'?'dashboard':'new')}
function renderNav(){$('#nav').innerHTML=navItems().map(([id,t])=>`<button class="nav-btn" data-view="${id}">${t}</button>`).join('');$$('.nav-btn[data-view]').forEach(b=>b.onclick=()=>go(b.dataset.view))}
async function go(v,extra=null){state.view=v;$$('.nav-btn[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===v));$('.sidebar').classList.remove('open');if(v==='dashboard')return renderDashboard();if(v==='new')return renderNewRecord(extra||state.presetJob);if(v==='jobs')return renderJobs();if(v==='records')return renderRecords();if(v==='mine')return renderMyRecords();if(v==='jobdetail')return renderJobDetail(extra)}
async function loadJobs(all=false){state.jobs=(await api('/api/jobs'+(all?'?all=1':''))).jobs;return state.jobs}
async function loadUsers(){state.users=(await api('/api/users')).users;return state.users}
function kpi(label,value,sub=''){return `<div class="kpi"><div class="label">${label}</div><div class="value">${value}</div>${sub?`<div class="sub">${sub}</div>`:''}</div>`}
function normLabel(j){const mode=j?.norm_mode||'ct';if(mode==='ct')return `CT ${Number(j.norm_ct_seconds||0).toLocaleString('sk-SK')} s/ks`;return 'Čas zadáva OP / Operator time'}
function secToHMS(v){v=Math.max(0,Math.round(Number(v)||0));const h=Math.floor(v/3600),m=Math.floor((v%3600)/60),s=v%60;return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`}
function timeTextSeconds(v){if(!v||!/^\d{1,3}:[0-5]\d$/.test(v))return 0;const [h,m]=v.split(':').map(Number);return h*3600+m*60}
function zeroFriendly(root=document){root.querySelectorAll('input.number-zero').forEach(i=>{if(i.dataset.zeroBound)return;i.dataset.zeroBound='1';i.addEventListener('focus',()=>{if(i.value==='0'||i.value==='0.0')i.value=''});i.addEventListener('blur',()=>{if(i.value==='')i.value='0'});})}
function jobOption(j){const part=j.parts?.[0];return `<option value="${j.id}">${esc(j.order_number)}${part?' — '+esc(part.item_number):''}</option>`}
function fmtNum(v,d=0){return Number(v||0).toLocaleString('sk-SK',{maximumFractionDigits:d,minimumFractionDigits:d})}

async function renderDashboard(){
  setTitle('Dashboard','Aktívne zákazky a dnešný prehľad');
  const d=await api('/api/dashboard');
  const cards=(d.jobs||[]).map(j=>`<button class="job-card" data-id="${j.id}"><div class="job-card-top"><span class="status-dot"></span><b>${esc(j.order_number)}</b><span class="badge green">Active</span></div><div class="job-card-desc">${esc(j.brief_description)}</div><div class="job-card-parts">${(j.parts||[]).slice(0,3).map(p=>`<span>${esc(p.item_number)}</span>`).join('')}${(j.parts||[]).length>3?`<span>+${j.parts.length-3}</span>`:''}</div><div class="job-card-kpis"><span>Checked <b>${j.checked}</b></span><span>OK <b>${j.ok}</b></span><span>NOK <b>${j.nok}</b></span><span>NOK rate <b>${fmtNum(j.nok_rate,2)}%</b></span></div></button>`).join('');
  $('#view').innerHTML=`<div class="kpis">${kpi('Checked dnes',d.checked)}${kpi('OK dnes',d.ok)}${kpi('NOK dnes',d.nok)}${kpi('NOK rate',d.checked?(d.nok/d.checked*100).toFixed(2)+'%':'0.00%')}${kpi('Aktívne zákazky',d.active_jobs)}</div><div class="section-title"><div><h3>Aktívne zákazky / Active jobs</h3><div class="muted">Kliknutím otvoríš detail zákazky.</div></div></div><div class="dashboard-jobs">${cards||'<div class="panel"><div class="panel-body empty">Nie sú žiadne aktívne zákazky.</div></div>'}</div>`;
  $$('.job-card').forEach(b=>b.onclick=()=>go('jobdetail',+b.dataset.id));
}

function shiftSelector(value='R'){
  return `<div class="shift-picker"><label><input type="radio" name="rShift" value="R" ${value==='R'?'checked':''}><span>R.<small>Ranná</small></span></label><label><input type="radio" name="rShift" value="P" ${value==='P'?'checked':''}><span>P.<small>Poobedná</small></span></label><label><input type="radio" name="rShift" value="N" ${value==='N'?'checked':''}><span>N.<small>Nočná</small></span></label></div>`
}

async function renderNewRecord(extra=null){
  const editId=(extra&&typeof extra==='object'&&extra.recordId)?Number(extra.recordId):null;
  if(editId&&state.user.role!=='admin')return toast('Záznamy môže editovať iba admin.','error');
  const editRecord=editId?(await api('/api/records/'+editId)).record:null;
  const preset=(editRecord?.job_id)||((typeof extra==='number'||typeof extra==='string')?Number(extra):null);
  setTitle(editRecord?'Upraviť záznam / Edit record':'Nový záznam / New record',editRecord?'Editácia je dostupná iba administrátorovi.':(state.user.role==='admin'?'Admin môže zadávať aj spätne dopĺňať záznamy.':'Vyber zákazku a doplň výsledky kontroly.'));
  await loadJobs(!!editRecord);
  const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Bratislava',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  $('#view').innerHTML=`<div class="hero-form"><div class="job-select-card"><label>1. Zákazka / Job<select id="rJob"><option value="">— Vyber zákazku —</option>${state.jobs.map(jobOption).join('')}</select></label><div id="jobInfo" class="job-info muted">Po výbere zákazky sa načítajú preddefinované údaje.</div><label>2. Číslo dielu / Item number<select id="rPart" disabled><option value="">— Vyber diel —</option></select></label><div id="partInfo" class="muted smalltext"></div><div class="record-meta"><div><b>Zmena / Shift</b>${shiftSelector(editRecord?.shift||'R')}</div>${state.user.role==='admin'?`<label>Dátum / Date<input id="rDate" type="date" value="${esc(editRecord?.record_date||today)}"></label>`:''}</div>${state.user.role==='admin'&&!editRecord?`<label>Záznam uložiť pod<select id="recordEmployee"><option value="">Ja — ${esc(state.user.display_name)} (admin)</option></select><small id="recordEmployeeHint">Vyber zákazku pre načítanie zamestnancov prevádzky.</small></label>`:''}<div id="normInputWrap"></div><div id="normPreview" class="callout hidden"></div></div><div class="result-card"><div class="grid two"><label>Číslo dodacieho listu / Delivery note number<input id="rDelivery" value="${esc(editRecord?.delivery_note||'')}"><button type="button" class="btn scan-button" data-scan-target="rDelivery">▥ Skenovať čiarový kód</button></label><label class="span2">Poznámka / Note<textarea id="rNote" rows="3">${esc(editRecord?.note||'')}</textarea></label></div><div class="number-grid"><label>Checked<input id="rChecked" class="number-zero" type="number" min="0" value="${editRecord?.checked_items??0}"></label><label>OK<input id="rOK" class="number-zero" type="number" min="0" value="${editRecord?.ok_items??0}"></label><label>NOK<input id="rNOK" class="number-zero" type="number" min="0" value="${editRecord?.nok_items??0}"></label><label>Reworked OK<input id="rRWOK" class="number-zero" type="number" min="0" value="${editRecord?.reworked_ok??0}"></label><label>Reworked NOK<input id="rRWNOK" class="number-zero" type="number" min="0" value="${editRecord?.reworked_nok??0}"></label></div><div class="section-title compact"><div><h4>Druhy chýb / Error types</h4><div id="errorSumInfo" class="muted smalltext">Súčet chýb musí byť rovný NOK.</div></div></div><div id="recordErrors" class="errors-box"></div><div class="save-bar"><button id="saveRecord" class="btn primary wide">${editRecord?'Uložiť zmeny':'Uložiť záznam / Save record'}</button></div></div></div>`;
  zeroFriendly($('#view'));

  const getJob=()=>state.jobs.find(j=>j.id==$('#rJob').value);
  const getPart=()=>{const j=getJob();return j?.parts?.find(p=>p.id==$('#rPart').value)};
  const errorDefaults=editRecord?.error_counts_obj||{};
  function renderErrors(j){
    $('#recordErrors').innerHTML=(j?.errors||[]).map(e=>`<label>${esc(e.name)}<input class="number-zero err-count" data-id="${e.id}" type="number" min="0" value="${Number(errorDefaults[String(e.id)]||0)}"></label>`).join('')||'<div class="muted">Zákazka nemá definované druhy chýb.</div>';
    zeroFriendly($('#recordErrors')); $$('.err-count').forEach(i=>i.oninput=updateErrorSum); updateErrorSum();
  }
  function updateErrorSum(){const sum=$$('.err-count').reduce((a,i)=>a+Number(i.value||0),0),nok=Number($('#rNOK').value||0);$('#errorSumInfo').innerHTML=`Súčet chýb: <b>${sum}</b> / NOK: <b>${nok}</b>${sum===nok?' <span class="ok-text">✓</span>':' <span class="bad-text">— musí sa rovnať</span>'}`}
  function updateNormPreview(){
    const j=getJob();
    if(!j)return $('#normPreview').classList.add('hidden');
    if(j.norm_mode==='ct'){
      // CT is calculated in the background. Keep the left side focused on operator inputs.
      $('#normPreview').classList.add('hidden');
      return;
    }
    const checked=Number($('#rChecked').value||0);
    const secs=timeTextSeconds($('#rOperatorTime')?.value||'');
    const actual=secs>0?checked*3600/secs:0;
    $('#normPreview').className='callout';
    $('#normPreview').innerHTML=`Aktuálny výkon / Current output: <b>${actual?fmtNum(actual,2):'—'} ks/h</b>`;
  }
  let employeeRequest=0;
  async function updateEmployeeOptions(j){
    if(!$('#recordEmployee'))return;
    const seq=++employeeRequest;
    $('#recordEmployee').innerHTML=`<option value="">Ja — ${esc(state.user.display_name)} (admin)</option>`;
    $('#recordEmployeeHint').textContent=j?.location_id?'Načítavam zamestnancov…':'Zákazka nemá prevádzku. Najprv ju doplň v nastavení zákazky.';
    if(!j?.location_id)return;
    try{const d=await api('/api/employees?location_id='+j.location_id);if(seq!==employeeRequest||!$('#recordEmployee'))return;
      $('#recordEmployee').innerHTML+=d.employees.map(u=>`<option value="${u.id}">${esc(u.name)} (${esc(u.personal_number)})</option>`).join('');
      $('#recordEmployeeHint').textContent=d.employees.length?'Zamestnanci priradení k prevádzke zákazky.':'K prevádzke nie sú priradení aktívni zamestnanci.';
    }catch(e){if(seq===employeeRequest&&$('#recordEmployeeHint'))$('#recordEmployeeHint').textContent=e.message}
  }
  function updateJob(){
    const j=getJob();
    updateEmployeeOptions(j);
    if(!j){$('#rPart').innerHTML='<option value="">— Vyber diel —</option>';$('#rPart').disabled=true;$('#jobInfo').textContent='Po výbere zákazky sa načítajú preddefinované údaje.';$('#recordErrors').innerHTML='';$('#normInputWrap').innerHTML='';$('#normPreview').classList.add('hidden');return}
    $('#jobInfo').innerHTML=`<div><b>${esc(j.order_number)}</b></div><div>${esc(j.brief_description)}</div>`;
    $('#rPart').disabled=false; $('#rPart').innerHTML='<option value="">— Vyber diel —</option>'+j.parts.map(p=>`<option value="${p.id}">${esc(p.item_number)} — ${esc(p.part_name||'')}</option>`).join('');
    const oldPart=editRecord?.part_id;if(oldPart&&j.id==editRecord.job_id)$('#rPart').value=oldPart;
    if(j.norm_mode==='time') $('#normInputWrap').innerHTML=`<label>Pracovný čas / Working time (H:MM)<input id="rOperatorTime" placeholder="0:30" inputmode="numeric" value="${editRecord?.work_time_seconds?esc(Math.floor(editRecord.work_time_seconds/3600)+':'+String(Math.floor((editRecord.work_time_seconds%3600)/60)).padStart(2,'0')):''}"><small>Akceptované napr. 0:05, 1:30 alebo 08:00.</small></label>`;
    else $('#normInputWrap').innerHTML='';
    renderErrors(j); updatePart();
    if($('#rOperatorTime'))$('#rOperatorTime').oninput=updateNormPreview;
  }
  function updatePart(){const p=getPart();$('#partInfo').innerHTML=p?`Názov dielu: <b>${esc(p.part_name||'—')}</b>`:'';updateNormPreview()}
  $('#rJob').onchange=()=>{updateJob()}; $('#rPart').onchange=updatePart; $('#rNOK').oninput=()=>{updateErrorSum();updateNormPreview()}; $('#rChecked').oninput=updateNormPreview;
  if(preset){$('#rJob').value=String(preset);updateJob()} if(editRecord){$('#rJob').value=String(editRecord.job_id);updateJob();$('#rPart').value=String(editRecord.part_id||'');updatePart()}
  $('#saveRecord').onclick=async()=>{
    const j=getJob(); if(!j)return toast('Vyber zákazku.','error'); if(!$('#rPart').value)return toast('Vyber číslo dielu.','error');
    const counts={};$$('.err-count').forEach(i=>counts[i.dataset.id]=Number(i.value||0));
    const body={job_id:+$('#rJob').value,part_id:+$('#rPart').value,delivery_note:$('#rDelivery').value,checked_items:+($('#rChecked').value||0),ok_items:+($('#rOK').value||0),nok_items:+($('#rNOK').value||0),reworked_ok:+($('#rRWOK').value||0),reworked_nok:+($('#rRWNOK').value||0),note:$('#rNote').value,error_counts:counts,shift:$('input[name="rShift"]:checked')?.value||'',operator_time:$('#rOperatorTime')?.value||''};
    if(state.user.role==='admin'){body.record_date=$('#rDate').value;if(!editId)body.employee_id=Number($('#recordEmployee').value)||null;}
    try{await api(editId?'/api/records/'+editId:'/api/records',{method:editId?'PUT':'POST',body:JSON.stringify(body)});toast(editId?'Záznam bol upravený.':'Záznam bol uložený.');state.presetJob=null;go(state.user.role==='admin'?'records':'mine')}catch(e){toast(e.message,'error')}
  };
}

function addPartRow(p={}){
  const d=document.createElement('div');d.className='editor-row part-row';d.innerHTML=`<input class="part-num" placeholder="Číslo dielu / Item number" value="${esc(p.item_number||'')}"><input class="part-name" placeholder="Názov dielu / Part name" value="${esc(p.part_name||'')}"><label class="part-norm-hour-wrap"><span>Norma ks/h</span><input class="part-norm-hour" type="number" min="0" step="0.01" placeholder="napr. 120" value="${p.norm_per_hour??''}"></label><button type="button" class="icon-btn remove-row">×</button>`;$('#partsEditor').appendChild(d);d.querySelector('.remove-row').onclick=()=>d.remove();normToggle();
}
function addErrorRow(e='') {const d=document.createElement('div');d.className='editor-row error-row';d.innerHTML=`<input class="error-name" placeholder="Druh chyby / Error type" value="${esc(typeof e==='string'?e:(e.name||''))}"><button type="button" class="icon-btn remove-row">×</button>`;$('#errorsEditor').appendChild(d);d.querySelector('.remove-row').onclick=()=>d.remove()}
function normToggle(){const mode=$('#jobNormMode')?.value||'ct';$('#normCtWrap')?.classList.toggle('hidden',mode!=='ct');$$('.part-norm-hour-wrap').forEach(x=>x.classList.toggle('hidden',mode!=='time'))}
async function openJob(j=null){
  let locations;try{locations=(await api('/api/locations')).locations}catch(e){return toast(e.message,'error')}
  $('#jobLocation').innerHTML='<option value="">— Vyber prevádzku —</option>'+locations.map(l=>`<option value="${l.id}">${esc(l.name)}</option>`).join('');
  $('#jobLocation').value=j?.location_id||'';

  $('#jobDialogTitle').textContent=j?'Upraviť zákazku / Edit job':'Nová zákazka / New job';$('#jobId').value=j?.id||'';$('#jobOrder').value=j?.order_number||'';$('#jobBrief').value=j?.brief_description||'';$('#jobNormMode').value=(j?.norm_mode==='time')?'time':'ct';$('#jobNormCT').value=j?.norm_ct_seconds??0;$('#jobActive').checked=j?!!j.active:true;$('#partsEditor').innerHTML='';(j?.parts?.length?j.parts:[{}]).forEach(addPartRow);$('#errorsEditor').innerHTML='';(j?.errors?.length?j.errors:['']).forEach(addErrorRow);normToggle();zeroFriendly($('#jobDialog'));$('#jobDialog').showModal()
}
$('#addPartBtn').onclick=()=>addPartRow({});$('#addErrorBtn').onclick=()=>addErrorRow('');$('#jobNormMode').onchange=normToggle;
$('#saveJobBtn').onclick=async()=>{
  const id=$('#jobId').value;const parts=$$('.part-row').map(r=>({item_number:r.querySelector('.part-num').value.trim(),part_name:r.querySelector('.part-name').value.trim(),norm_per_hour:r.querySelector('.part-norm-hour').value.trim()?Number(r.querySelector('.part-norm-hour').value):null})).filter(p=>p.item_number||p.part_name);const errors=$$('.error-name').map(x=>x.value.trim()).filter(Boolean);const body={location_id:Number($('#jobLocation').value)||null,order_number:$('#jobOrder').value,brief_description:$('#jobBrief').value,norm_mode:$('#jobNormMode').value,norm_ct_seconds:Number($('#jobNormCT').value||0),parts,errors,active:$('#jobActive').checked};
  try{await api(id?'/api/jobs/'+id:'/api/jobs',{method:id?'PUT':'POST',body:JSON.stringify(body)});$('#jobDialog').close();toast('Zákazka uložená.');if(state.view==='jobs')renderJobs();else if(state.view==='jobdetail')go('jobdetail',+id||null);else if(state.view==='dashboard')renderDashboard()}catch(e){toast(e.message,'error')}
};

async function archiveJob(id,archive=true,after=null){try{await api(`/api/jobs/${id}/${archive?'archive':'restore'}`,{method:'POST',body:'{}'});toast(archive?'Zákazka bola archivovaná.':'Zákazka bola obnovená.');if(after)await after()}catch(e){toast(e.message,'error')}}
async function deleteJob(id,after=null){if(!confirm('TRVALO vymazať zákazku? Ak obsahuje záznamy, vymažú sa spolu so zákazkou. Túto operáciu nemožno vrátiť.'))return;try{const d=await api(`/api/jobs/${id}?force=1`,{method:'DELETE'});toast(`Zákazka bola vymazaná${d.deleted_records?` vrátane ${d.deleted_records} záznamov`:''}.`);if(after)await after()}catch(e){toast(e.message,'error')}}

async function renderJobs(){
  setTitle('Zákazky / Jobs','Aktívne a archivované zákazky');await loadJobs(true);
  $('#view').innerHTML=`<div class="section-title"><div><h3>Zákazky</h3><div class="muted">Otvor detail zákazky, uprav ju alebo zmeň jej stav.</div></div><button id="newJob" class="btn primary">＋ Nová zákazka</button></div><div class="panel"><div class="panel-body"><div class="toolbar"><label>Stav<select id="jobStatusFilter"><option value="active">Aktívne</option><option value="archived">Archivované</option><option value="all">Všetky</option></select></label><label>Hľadať<input id="jobSearch" placeholder="Order / diel / popis"></label></div></div></div><div class="panel"><div class="table-wrap"><table><thead><tr><th>Order</th><th>Popis</th><th>Norma</th><th>Diely</th><th>Chyby</th><th>Stav</th><th>Akcie</th></tr></thead><tbody id="jobsBody"></tbody></table></div></div>`;
  function draw(){const status=$('#jobStatusFilter').value,q=$('#jobSearch').value.toLowerCase().trim();const jobs=state.jobs.filter(j=>(status==='all'||(status==='active'&&j.active)||(status==='archived'&&!j.active))&&(!q||[j.order_number,j.brief_description,...(j.parts||[]).flatMap(p=>[p.item_number,p.part_name])].join(' ').toLowerCase().includes(q)));$('#jobsBody').innerHTML=jobs.map(j=>`<tr><td><button class="link-btn open-job" data-id="${j.id}"><b>${esc(j.order_number)}</b></button></td><td>${esc(j.brief_description)}</td><td>${esc(normLabel(j))}</td><td>${j.parts.map(p=>`<div><b>${esc(p.item_number)}</b>${p.part_name?' — '+esc(p.part_name):''}${j.norm_mode==='time'&&p.norm_per_hour?` <span class="badge">${fmtNum(p.norm_per_hour,2)} ks/h</span>`:''}</div>`).join('')}</td><td>${j.errors.map(e=>`<span class="chip">${esc(e.name)}</span>`).join('')}</td><td><span class="badge ${j.active?'green':'gray'}">${j.active?'Active':'Archived'}</span></td><td class="actions"><button class="btn small edit-job" data-id="${j.id}">Edit</button><button class="btn small ${j.active?'':'primary'} toggle-job" data-id="${j.id}" data-active="${j.active?1:0}">${j.active?'Archive':'Restore'}</button><button class="btn small danger delete-job" data-id="${j.id}">Delete</button></td></tr>`).join('')||'<tr><td colspan="7" class="empty">Žiadne zákazky pre zvolený filter.</td></tr>';
    $$('.open-job').forEach(b=>b.onclick=()=>go('jobdetail',+b.dataset.id));$$('.edit-job').forEach(b=>b.onclick=()=>openJob(state.jobs.find(j=>j.id==b.dataset.id)));$$('.toggle-job').forEach(b=>b.onclick=()=>archiveJob(+b.dataset.id,b.dataset.active==='1',async()=>{await loadJobs(true);draw()}));$$('.delete-job').forEach(b=>b.onclick=()=>deleteJob(+b.dataset.id,async()=>{await loadJobs(true);draw()}));
  }
  $('#newJob').onclick=()=>openJob();$('#jobStatusFilter').onchange=draw;$('#jobSearch').oninput=draw;draw();
}

function devText(r){return r.norm_deviation_pct==null?'':`${Number(r.norm_deviation_pct)>=0?'+':''}${fmtNum(r.norm_deviation_pct,2)}%`}
function tableRows(rows,admin=false,actions=false){
  return rows.map(r=>{const p=r.part_snapshot_obj||{};const norm=r.norm_seconds_per_item==null?'':fmtNum(r.norm_seconds_per_item,2);const status=r.archived?'Archived':'Active';return `<tr class="${r.norm_outside?'norm-outside ':''}${r.archived?'record-archived':''}"><td>${esc(r.record_date)}</td><td><b>${esc(r.shift||'')}</b></td><td><button class="link-btn open-row-job" data-job="${r.job_id}">${esc(r.order_number)}</button></td><td><b>${esc(p.item_number||'')}</b></td><td>${esc(p.part_name||'')}</td><td>${esc(r.delivery_note||'')}</td><td>${r.checked_items}</td><td>${r.ok_items}</td><td>${r.nok_items}</td><td>${r.reworked_ok}</td><td>${r.reworked_nok}</td><td>${r.work_time_seconds?secToHMS(r.work_time_seconds):''}</td><td>${norm}</td><td>${r.norm_target_per_hour!=null?fmtNum(r.norm_target_per_hour,2):''}</td><td>${r.actual_per_hour!=null?fmtNum(r.actual_per_hour,2):''}</td><td>${devText(r)}</td>${admin?`<td>${esc(r.display_name)}</td>`:''}<td>${esc(r.note||'')}</td>${actions&&state.user.role==='admin'?`<td><span class="badge ${r.archived?'gray':'green'}">${status}</span></td><td class="actions record-actions"><button class="btn small edit-record" data-id="${r.id}">Edit</button><button class="btn small toggle-record" data-id="${r.id}" data-archived="${r.archived?1:0}">${r.archived?'Obnoviť záznam':'Archivovať záznam'}</button><button class="btn small danger delete-record" data-id="${r.id}">Vymazať záznam</button><button class="btn small outline archive-job-row" data-job="${r.job_id}" data-active="${r.job_active?1:0}">${r.job_active?'Archivovať zákazku':'Obnoviť zákazku'}</button><button class="btn small danger-outline delete-job-row" data-job="${r.job_id}">Vymazať zákazku</button></td>`:''}</tr>`}).join('')||'<tr><td colspan="30" class="empty">Žiadne záznamy</td></tr>'
}
function bindOpenJobs(){$$('.open-row-job').forEach(b=>b.onclick=()=>go('jobdetail',+b.dataset.job))}
function bindRecordActions(reload){bindOpenJobs();if(state.user.role!=='admin')return;$$('.edit-record').forEach(b=>b.onclick=()=>go('new',{recordId:+b.dataset.id}));$$('.toggle-record').forEach(b=>b.onclick=async()=>{try{await api(`/api/records/${b.dataset.id}/${b.dataset.archived==='1'?'restore':'archive'}`,{method:'POST',body:'{}'});toast(b.dataset.archived==='1'?'Záznam obnovený.':'Záznam archivovaný.');await reload()}catch(e){toast(e.message,'error')}});$$('.delete-record').forEach(b=>b.onclick=async()=>{if(!confirm('Trvalo vymazať tento záznam?'))return;try{await api('/api/records/'+b.dataset.id,{method:'DELETE'});toast('Záznam vymazaný.');await reload()}catch(e){toast(e.message,'error')}});$$('.archive-job-row').forEach(b=>b.onclick=()=>archiveJob(+b.dataset.job,b.dataset.active==='1',reload));$$('.delete-job-row').forEach(b=>b.onclick=()=>deleteJob(+b.dataset.job,reload))}
function pdfDownload(params){downloadFile('/api/export/pdf?'+params.toString())}

async function renderJobDetail(id){
  setTitle('Zákazka / Job detail','Sumár, záznamy a exporty');const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Bratislava',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());$('#view').innerHTML='<div class="panel"><div class="panel-body">Načítavam…</div></div>';
  async function load(){
    const oldFrom=$('#jdFrom')?.value||'',oldTo=$('#jdTo')?.value||'';const qs=new URLSearchParams();if(oldFrom)qs.set('date_from',oldFrom);if(oldTo)qs.set('date_to',oldTo);const d=await api(`/api/jobs/${id}/summary?`+qs);const j=d.job,t=d.totals;
    $('#view').innerHTML=`<div class="job-hero"><div><button class="link-btn" id="backJobs">← Zákazky</button><div class="job-title-line"><h2>${esc(j.order_number)}</h2><span class="badge ${j.active?'green':'gray'}">${j.active?'Active':'Archived'}</span></div><p>${esc(j.brief_description)}</p><div class="chips"><span class="chip">Norm: ${esc(normLabel(j))}</span>${j.parts.map(p=>`<span class="chip">${esc(p.item_number)} — ${esc(p.part_name||'')}${j.norm_mode==='time'&&p.norm_per_hour?` · ${fmtNum(p.norm_per_hour,2)} ks/h`:''}</span>`).join('')}</div></div><div class="job-hero-actions"><button id="jobNewRecord" class="btn primary" ${j.active?'':'disabled'}>＋ Nový záznam</button><button id="jobEdit" class="btn">Edit job</button><button id="jobArchive" class="btn">${j.active?'Archive':'Restore'}</button><button id="jobDelete" class="btn danger">Delete</button></div></div><div class="panel"><div class="panel-body"><div class="toolbar"><label>Od / From<input id="jdFrom" type="date" value="${esc(oldFrom)}"></label><label>Do / To<input id="jdTo" type="date" value="${esc(oldTo)}"></label><button id="jdLoad" class="btn">Načítať</button><button id="jdPdf" class="btn primary">PDF report</button><button id="jdXlsx" class="btn">XLS report</button><label>Daily XLSM date<input id="jdDay" type="date" value="${today}"></label><button id="jdXlsm" class="btn">XLSM podľa šablóny</button></div></div></div><div class="kpis">${kpi('Checked',t.checked_items)}${kpi('OK',t.ok_items)}${kpi('NOK',t.nok_items)}${kpi('NOK rate',t.nok_rate+'%')}${kpi('Records',t.record_count)}</div><div class="panel"><div class="panel-head"><h3>Druhy chýb / Error types</h3></div><div class="panel-body chips">${j.errors.length?j.errors.map(e=>`<span class="chip">${esc(e.name)}</span>`).join(''):'<span class="muted">None</span>'}</div></div><div class="panel"><div class="table-wrap"><table><thead>${recordHeader(true,true)}</thead><tbody>${tableRows(d.records,true,true)}</tbody></table></div></div>`;
    $('#backJobs').onclick=()=>go('jobs');$('#jobNewRecord').onclick=()=>j.active&&go('new',id);$('#jobEdit').onclick=()=>openJob(j);$('#jobArchive').onclick=()=>archiveJob(id,!!j.active,load);$('#jobDelete').onclick=()=>deleteJob(id,()=>go('jobs'));$('#jdLoad').onclick=load;
    const params=()=>{const q=new URLSearchParams({job_id:id});if($('#jdFrom').value)q.set('date_from',$('#jdFrom').value);if($('#jdTo').value)q.set('date_to',$('#jdTo').value);return q};
    $('#jdPdf').onclick=()=>downloadFile('/api/export/pdf?'+params());$('#jdXlsx').onclick=()=>downloadFile('/api/export/xlsx?'+params());$('#jdXlsm').onclick=()=>downloadFile(`/api/export/daily-xlsm?job_id=${id}&date=${encodeURIComponent($('#jdDay').value)}`);bindRecordActions(load);
  }
  await load();
}

function recordHeader(admin=true,actions=true){return `<tr><th>Date</th><th>Shift</th><th>Order</th><th>Item number</th><th>Part name</th><th>Delivery note</th><th>Checked</th><th>OK</th><th>NOK</th><th>R.OK</th><th>R.NOK</th><th>Working time</th><th>Norm s/item</th><th>Target/h</th><th>Actual/h</th><th>Deviation</th>${admin?'<th>Operator</th>':''}<th>Note</th>${actions?'<th>Status</th><th>Actions</th>':''}</tr>`}

async function renderMyRecords(){
  setTitle('Moje záznamy / My records','História operátora, číslo dielu a export');await loadJobs(false);const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Bratislava',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());const rows=(await api('/api/records')).records;
  $('#view').innerHTML=`<div class="panel"><div class="panel-head"><h3>Report</h3></div><div class="panel-body"><div class="toolbar"><label>Zákazka<select id="myPdfJob"><option value="">— Select —</option>${state.jobs.map(jobOption).join('')}</select></label><label>Dátum<input id="myPdfDate" type="date" value="${today}"></label><button id="myPdf" class="btn primary">PDF report</button><button id="myXlsm" class="btn">XLSM podľa šablóny</button></div><div class="muted smalltext">Report obsahuje iba tvoje záznamy.</div></div></div><div class="panel"><div class="table-wrap"><table><thead>${recordHeader(false,false)}</thead><tbody>${tableRows(rows,false,false)}</tbody></table></div></div>`;
  bindOpenJobs();$('#myPdf').onclick=()=>{if(!$('#myPdfJob').value)return toast('Vyber zákazku.','error');downloadFile('/api/export/pdf?'+new URLSearchParams({job_id:$('#myPdfJob').value,date:$('#myPdfDate').value}))};$('#myXlsm').onclick=()=>{if(!$('#myPdfJob').value)return toast('Vyber zákazku.','error');downloadFile(`/api/export/daily-xlsm?job_id=${encodeURIComponent($('#myPdfJob').value)}&date=${encodeURIComponent($('#myPdfDate').value)}`)};
}

function multiSelectMarkup(id,label,options){return `<div class="multi-field"><span class="field-label">${esc(label)}</span><details class="multi-select" id="${id}"><summary><span class="multi-summary">Všetky</span><span>▾</span></summary><div class="multi-options">${options.map(o=>`<label><input type="checkbox" value="${esc(o.value)}"><span>${esc(o.label)}</span></label>`).join('')||'<div class="muted">Žiadne možnosti</div>'}</div></details></div>`}
function bindMulti(id){const d=$('#'+id);if(!d)return;const upd=()=>{const c=[...d.querySelectorAll('input:checked')];d.querySelector('.multi-summary').textContent=c.length?`${c.length} vybrané`:'Všetky'};d.querySelectorAll('input').forEach(x=>x.onchange=upd);upd()}
function getMulti(id){return [...$('#'+id).querySelectorAll('input:checked')].map(x=>x.value)}

async function renderRecords(){
  setTitle('Záznamy / Records','Viacnásobné filtre, reporty, archivácia a editácia');await Promise.all([loadJobs(true),loadUsers()]);
  const partOptions=[];const seen=new Set();for(const j of state.jobs)for(const p of j.parts||[]){if(!seen.has(p.id)){seen.add(p.id);partOptions.push({value:p.id,label:`${p.item_number}${p.part_name?' — '+p.part_name:''}`})}}
  $('#view').innerHTML=`<div class="panel"><div class="panel-body"><div class="records-filters">${multiSelectMarkup('fJob','Zákazka / Job',state.jobs.map(j=>({value:j.id,label:`${j.order_number}${j.active?'':' [ARCHIVED]'}`})))}${multiSelectMarkup('fPart','Číslo dielu / Item',partOptions)}${multiSelectMarkup('fShift','Zmena / Shift',[{value:'R',label:'R. – Ranná'},{value:'P',label:'P. – Poobedná'},{value:'N',label:'N. – Nočná'}])}${multiSelectMarkup('fUser','Používateľ / User',state.users.map(u=>({value:u.id,label:u.display_name})))}<label>Od / From<input id="fFrom" type="date"></label><label>Do / To<input id="fTo" type="date"></label><label>Stav záznamu<select id="fRecordStatus"><option value="active">Aktívne</option><option value="archived">Archivované</option><option value="all">Všetky</option></select></label></div><div class="report-actions"><button id="loadRecords" class="btn primary">Načítať</button><button id="recordsPdf" class="btn primary">PDF report</button><button id="recordsXls" class="btn">XLS report</button></div><div class="muted smalltext">V roletových filtroch môžeš označiť viac zákaziek, dielov, zmien aj používateľov. Červený riadok = výkon mimo ±10 % hodinovej normy.</div></div></div><div class="panel"><div class="table-wrap"><table><thead>${recordHeader(true,true)}</thead><tbody id="recordsBody"></tbody></table></div></div>`;
  ['fJob','fPart','fShift','fUser'].forEach(bindMulti);
  function params(){const q=new URLSearchParams();const jobs=getMulti('fJob'),parts=getMulti('fPart'),shifts=getMulti('fShift'),users=getMulti('fUser');if(jobs.length)q.set('job_id',jobs.join(','));if(parts.length)q.set('part_id',parts.join(','));if(shifts.length)q.set('shift',shifts.join(','));if(users.length)q.set('operator_id',users.join(','));if($('#fFrom').value)q.set('date_from',$('#fFrom').value);if($('#fTo').value)q.set('date_to',$('#fTo').value);q.set('record_status',$('#fRecordStatus').value);return q}
  async function load(){const rows=(await api('/api/records?'+params())).records;$('#recordsBody').innerHTML=tableRows(rows,true,true);bindRecordActions(load)}
  $('#loadRecords').onclick=load;$('#recordsPdf').onclick=()=>downloadFile('/api/export/records-pdf?'+params());$('#recordsXls').onclick=()=>downloadFile('/api/export/records-xlsx?'+params());await load();
}

function openPasswordDialog(){
  $('#cpCurrent').value='';$('#cpNew').value='';$('#cpConfirm').value='';$('#passwordDialog').showModal();setTimeout(()=>$('#cpCurrent').focus(),50)
}
$('#changePasswordBtn').onclick=openPasswordDialog;
$('#savePasswordBtn').onclick=async()=>{
  try{
    if($('#cpNew').value!==$('#cpConfirm').value)throw new Error('Nové heslá sa nezhodujú.');
    const r=await fetch('/api/me/change-password',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+localStorage.getItem('dochadzka_token')},body:JSON.stringify({current_password:$('#cpCurrent').value,new_password:$('#cpNew').value})});
    const d=await r.json();if(!r.ok)throw new Error(d.detail||'Zmena hesla zlyhala');
    localStorage.removeItem('dochadzka_token');location.href='/?password=changed';
  }catch(e){toast(e.message,'error')}
};
$('#loginForm').onsubmit=e=>{e.preventDefault();showLogin()};
$('#logoutBtn').onclick=()=>window.miellLogout();
$('#mobileMenu').onclick=()=>$('.sidebar').classList.toggle('open');
(async()=>{$('#todayLabel').textContent=new Date().toLocaleDateString('sk-SK',{weekday:'long',year:'numeric',month:'long',day:'numeric'});try{const d=await api('/api/me');if(d.user){state.user=d.user;showApp()}else showLogin()}catch{showLogin()}})();
