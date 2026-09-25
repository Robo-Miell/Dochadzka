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
    if(window.MiellDownloads?.postMessage){
      window.MiellDownloads.postMessage('/quality'+url);
      return;
    }
    if(window.MiellScanner?.postMessage){
      throw new Error('Na uloženie PDF a Excel reportov aktualizuj Android aplikáciu na verziu 0.6.2 alebo novšiu.');
    }
    toast('Pripravujem report…');
    const r=await fetch('/quality'+url,{headers:{Authorization:'Bearer '+(localStorage.getItem('dochadzka_token')||'')}});
    if(!r.ok){let d={};try{d=await r.json()}catch{};throw new Error(d.error||d.detail||`HTTP ${r.status}`)}
    const blob=await r.blob();
    let name='report';
    const cd=r.headers.get('Content-Disposition')||'';
    const m=cd.match(/filename="?([^";]+)"?/i); if(m) name=m[1];
    const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(a.href),60000);
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
function jobReportFormats(j){return new Set(String(j?.reporting_formats||'').split(',').map(x=>x.trim().toLowerCase()).filter(Boolean))}
function jobReportStatusText(j){
  if(!j?.id)return 'Najprv ulož zákazku.';
  const status=String(j.reporting_last_status||'');
  const when=j.reporting_last_sent_at?` · ${esc(j.reporting_last_sent_at)}`:'';
  if(status==='sent')return `Posledné odoslanie: úspešné${when}`;
  if(status==='skipped')return `Posledné odoslanie: bez dát${when}`;
  if(status==='error')return `Posledné odoslanie: chyba${when}${j.reporting_last_error?` · ${esc(j.reporting_last_error)}`:''}`;
  return 'Zatiaľ nebol odoslaný žiadny report.';
}
function jobReportSummary(j){
  if(!j?.reporting_enabled)return '<span class="badge gray">Off</span>';
  const recipients=String(j.reporting_recipients||'').split(',').map(x=>x.trim()).filter(Boolean).length;
  return `<span class="badge green">${esc(j.reporting_time||'08:00')}</span><div class="smalltext">${recipients===1?'1 príjemca':recipients+' príjemcov'}</div>`;
}
async function sendJobReportNow(id,after=null){
  if(!id)return toast('Najprv ulož zákazku.','error');
  try{
    const d=await api(`/api/jobs/${id}/report/send-now`,{method:'POST',body:'{}'});
    toast(d.skipped?'Report nebol odoslaný – za predchádzajúci deň nie sú údaje.':'Quality report bol odoslaný.');
    if(after)await after();
    return d;
  }catch(e){toast(e.message,'error');return null}
}

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
  if(state.user.role!=='admin'&&!state.jobs.length){
    $('#view').innerHTML='<div class="panel"><div class="panel-body">Nemáš prístup k žiadnej aktívnej zákazke. Požiadaj administrátora, aby skontroloval tvoje pridelené prevádzky a prevádzku zákazky.</div></div>';
    return;
  }
  const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Bratislava',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  $('#view').innerHTML=`<div class="hero-form"><div class="job-select-card"><label>1. Zákazka / Job<select id="rJob"><option value="">— Vyber zákazku —</option>${state.jobs.map(jobOption).join('')}</select></label><div id="jobInfo" class="job-info muted">Po výbere zákazky sa načítajú preddefinované údaje.</div><label>2. Číslo dielu / Item number<select id="rPart" disabled><option value="">— Vyber diel —</option></select></label><div id="partInfo" class="muted smalltext"></div><div class="record-meta"><div><b>Zmena / Shift</b>${shiftSelector(editRecord?.shift||'R')}</div>${state.user.role==='admin'?`<label>Dátum / Date<input id="rDate" type="date" value="${esc(editRecord?.record_date||today)}"></label>`:''}</div>${state.user.role==='admin'&&!editRecord?`<label>Záznam uložiť pod<select id="recordEmployee"><option value="">Ja — ${esc(state.user.display_name)} (admin)</option></select><small id="recordEmployeeHint">Vyber zákazku pre načítanie zamestnancov prevádzky.</small></label>`:''}<div id="normInputWrap"></div><div id="normPreview" class="callout hidden"></div></div><div class="result-card"><div class="grid two"><label>Číslo dodacieho listu / Delivery note number<input id="rDelivery" value="${esc(editRecord?.delivery_note||'')}"><button type="button" class="btn scan-button" data-scan-target="rDelivery">▥ Skenovať etiketu (P / S / Q)</button></label><label class="span2">Poznámka / Note<textarea id="rNote" rows="3">${esc(editRecord?.note||'')}</textarea></label></div><div class="number-grid"><label>Checked<input id="rChecked" class="number-zero" type="number" min="0" value="${editRecord?.checked_items??0}"></label><label>OK<input id="rOK" class="number-zero" type="number" min="0" value="${editRecord?.ok_items??0}"></label><label>NOK<input id="rNOK" class="number-zero" type="number" min="0" value="${editRecord?.nok_items??0}"></label><label>Reworked OK<input id="rRWOK" class="number-zero" type="number" min="0" value="${editRecord?.reworked_ok??0}"></label><label>Reworked NOK<input id="rRWNOK" class="number-zero" type="number" min="0" value="${editRecord?.reworked_nok??0}"></label></div><div class="section-title compact"><div><h4>Druhy chýb / Error types</h4><div id="errorSumInfo" class="muted smalltext">Súčet chýb musí byť rovný NOK.</div></div></div><div id="recordErrors" class="errors-box"></div><div class="save-bar"><button id="saveRecord" class="btn primary wide">${editRecord?'Uložiť zmeny':'Uložiť záznam / Save record'}</button></div></div></div>`;
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
    $('#rPart').disabled=false; $('#rPart').innerHTML='<option value="">— Vyber diel —</option>'+j.parts.map(p=>`<option value="${p.id}" data-item-number="${esc(p.item_number)}">${esc(p.item_number)} — ${esc(p.part_name||'')}</option>`).join('');
    const oldPart=editRecord?.part_id;if(oldPart&&j.id==editRecord.job_id)$('#rPart').value=oldPart;
    if(j.norm_mode==='time') $('#normInputWrap').innerHTML=`<label>Pracovný čas / Working time (HH:MM)<input id="rOperatorTime" placeholder="hh:mm" inputmode="numeric" value="${editRecord?.work_time_seconds?esc(String(Math.floor(editRecord.work_time_seconds/3600)).padStart(2,'0')+':'+String(Math.floor((editRecord.work_time_seconds%3600)/60)).padStart(2,'0')):''}"><small>Zadaj 0120 → 01:20. Dvojbodka sa doplní automaticky.</small></label>`;
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

  $('#jobDialogTitle').textContent=j?'Upraviť zákazku / Edit job':'Nová zákazka / New job';$('#jobId').value=j?.id||'';$('#jobOrder').value=j?.order_number||'';$('#jobBrief').value=j?.brief_description||'';$('#jobNormMode').value=(j?.norm_mode==='time')?'time':'ct';$('#jobNormCT').value=j?.norm_ct_seconds??0;$('#jobActive').checked=j?!!j.active:true;
  $('#jobReportEnabled').checked=!!j?.reporting_enabled;$('#jobReportRecipients').value=j?.reporting_recipients||'';$('#jobReportTime').value=j?.reporting_time||'08:00';const rf=jobReportFormats(j);$('#jobReportPdf').checked=j?rf.has('pdf'):true;$('#jobReportXlsx').checked=j?rf.has('xlsx'):false;$('#jobReportXlsm').checked=j?rf.has('xlsm'):true;$('#jobReportStatus').innerHTML=jobReportStatusText(j);$('#jobReportNow').disabled=!j?.id;$('#jobReportNow').onclick=()=>sendJobReportNow(Number($('#jobId').value),async()=>{const d=await api('/api/jobs/'+$('#jobId').value);const fresh=d.job;$('#jobReportStatus').innerHTML=jobReportStatusText(fresh)});
  $('#partsEditor').innerHTML='';(j?.parts?.length?j.parts:[{}]).forEach(addPartRow);$('#errorsEditor').innerHTML='';(j?.errors?.length?j.errors:['']).forEach(addErrorRow);normToggle();zeroFriendly($('#jobDialog'));$('#jobDialog').showModal()
}
$('#addPartBtn').onclick=()=>addPartRow({});$('#addErrorBtn').onclick=()=>addErrorRow('');$('#jobNormMode').onchange=normToggle;
$('#saveJobBtn').onclick=async()=>{
  const id=$('#jobId').value;const parts=$$('.part-row').map(r=>({item_number:r.querySelector('.part-num').value.trim(),part_name:r.querySelector('.part-name').value.trim(),norm_per_hour:r.querySelector('.part-norm-hour').value.trim()?Number(r.querySelector('.part-norm-hour').value):null})).filter(p=>p.item_number||p.part_name);const errors=$$('.error-name').map(x=>x.value.trim()).filter(Boolean);const reportFormats=[];if($('#jobReportPdf').checked)reportFormats.push('pdf');if($('#jobReportXlsx').checked)reportFormats.push('xlsx');if($('#jobReportXlsm').checked)reportFormats.push('xlsm');const body={location_id:Number($('#jobLocation').value)||null,order_number:$('#jobOrder').value,brief_description:$('#jobBrief').value,norm_mode:$('#jobNormMode').value,norm_ct_seconds:Number($('#jobNormCT').value||0),parts,errors,active:$('#jobActive').checked,reporting_enabled:$('#jobReportEnabled').checked,reporting_recipients:$('#jobReportRecipients').value,reporting_time:$('#jobReportTime').value||'08:00',reporting_formats:reportFormats.join(',')};
  try{await api(id?'/api/jobs/'+id:'/api/jobs',{method:id?'PUT':'POST',body:JSON.stringify(body)});$('#jobDialog').close();toast('Zákazka uložená.');if(state.view==='jobs')renderJobs();else if(state.view==='jobdetail')go('jobdetail',+id||null);else if(state.view==='dashboard')renderDashboard()}catch(e){toast(e.message,'error')}
};

async function archiveJob(id,archive=true,after=null){try{await api(`/api/jobs/${id}/${archive?'archive':'restore'}`,{method:'POST',body:'{}'});toast(archive?'Zákazka bola archivovaná.':'Zákazka bola obnovená.');if(after)await after()}catch(e){toast(e.message,'error')}}
async function deleteJob(id,after=null){if(!confirm('TRVALO vymazať zákazku? Ak obsahuje záznamy, vymažú sa spolu so zákazkou. Túto operáciu nemožno vrátiť.'))return;try{const d=await api(`/api/jobs/${id}?force=1`,{method:'DELETE'});toast(`Zákazka bola vymazaná${d.deleted_records?` vrátane ${d.deleted_records} záznamov`:''}.`);if(after)await after()}catch(e){toast(e.message,'error')}}

async function renderJobs(){
  setTitle('Zákazky / Jobs','Aktívne a archivované zákazky');await loadJobs(true);
  $('#view').innerHTML=`<div class="section-title"><div><h3>Zákazky</h3><div class="muted">Otvor detail zákazky, uprav ju alebo zmeň jej stav.</div></div><button id="newJob" class="btn primary">＋ Nová zákazka</button></div><div class="panel"><div class="panel-body"><div class="toolbar"><label>Stav<select id="jobStatusFilter"><option value="active">Aktívne</option><option value="archived">Archivované</option><option value="all">Všetky</option></select></label><label>Hľadať<input id="jobSearch" placeholder="Order / diel / popis"></label></div></div></div><div class="panel"><div class="table-wrap"><table><thead><tr><th>Order</th><th>Popis</th><th>Norma</th><th>Diely</th><th>Chyby</th><th>Reporting</th><th>Stav</th><th>Akcie</th></tr></thead><tbody id="jobsBody"></tbody></table></div></div>`;
  function draw(){const status=$('#jobStatusFilter').value,q=$('#jobSearch').value.toLowerCase().trim();const jobs=state.jobs.filter(j=>(status==='all'||(status==='active'&&j.active)||(status==='archived'&&!j.active))&&(!q||[j.order_number,j.brief_description,...(j.parts||[]).flatMap(p=>[p.item_number,p.part_name])].join(' ').toLowerCase().includes(q)));$('#jobsBody').innerHTML=jobs.map(j=>`<tr><td><button class="link-btn open-job" data-id="${j.id}"><b>${esc(j.order_number)}</b></button></td><td>${esc(j.brief_description)}</td><td>${esc(normLabel(j))}</td><td>${j.parts.map(p=>`<div><b>${esc(p.item_number)}</b>${p.part_name?' — '+esc(p.part_name):''}${j.norm_mode==='time'&&p.norm_per_hour?` <span class="badge">${fmtNum(p.norm_per_hour,2)} ks/h</span>`:''}</div>`).join('')}</td><td>${j.errors.map(e=>`<span class="chip">${esc(e.name)}</span>`).join('')}</td><td>${jobReportSummary(j)}</td><td><span class="badge ${j.active?'green':'gray'}">${j.active?'Active':'Archived'}</span></td><td class="actions"><button class="btn small edit-job" data-id="${j.id}">Edit</button><button class="btn small ${j.active?'':'primary'} toggle-job" data-id="${j.id}" data-active="${j.active?1:0}">${j.active?'Archive':'Restore'}</button><button class="btn small danger delete-job" data-id="${j.id}">Delete</button></td></tr>`).join('')||'<tr><td colspan="8" class="empty">Žiadne zákazky pre zvolený filter.</td></tr>';
    $$('.open-job').forEach(b=>b.onclick=()=>go('jobdetail',+b.dataset.id));$$('.edit-job').forEach(b=>b.onclick=()=>openJob(state.jobs.find(j=>j.id==b.dataset.id)));$$('.toggle-job').forEach(b=>b.onclick=()=>archiveJob(+b.dataset.id,b.dataset.active==='1',async()=>{await loadJobs(true);draw()}));$$('.delete-job').forEach(b=>b.onclick=()=>deleteJob(+b.dataset.id,async()=>{await loadJobs(true);draw()}));
  }
  $('#newJob').onclick=()=>openJob();$('#jobStatusFilter').onchange=draw;$('#jobSearch').oninput=draw;draw();
}

function devText(r){return r.norm_deviation_pct==null?'':`${Number(r.norm_deviation_pct)>=0?'+':''}${fmtNum(r.norm_deviation_pct,2)}%`}
function tableRows(rows,admin=false,actions=false){
  return rows.map(r=>{const p=r.part_snapshot_obj||{};const norm=r.norm_seconds_per_item==null?'':fmtNum(r.norm_seconds_per_item,2);const status=r.archived?'Archived':'Active';return `<tr class="${r.norm_outside?'norm-outside ':''}${r.archived?'record-archived':''}"><td>${esc(r.record_date)}</td><td><b>${esc(r.shift||'')}</b></td><td><button class="link-btn open-row-job" data-job="${r.job_id}">${esc(r.order_number)}</button></td><td><b>${esc(p.item_number||'')}</b></td><td>${esc(p.part_name||'')}</td><td>${esc(r.delivery_note||'')}</td><td>${r.checked_items}</td><td>${r.ok_items}</td><td>${r.nok_items}</td><td class="record-errors">${recordErrors(r)}</td><td>${r.reworked_ok}</td><td>${r.reworked_nok}</td><td>${r.work_time_seconds?secToHMS(r.work_time_seconds):''}</td><td>${norm}</td><td>${r.norm_target_per_hour!=null?fmtNum(r.norm_target_per_hour,2):''}</td><td>${r.actual_per_hour!=null?fmtNum(r.actual_per_hour,2):''}</td><td>${devText(r)}</td>${admin?`<td>${esc(r.display_name)}</td>`:''}<td>${esc(r.note||'')}</td>${actions&&state.user.role==='admin'?`<td><span class="badge ${r.archived?'gray':'green'}">${status}</span></td><td class="actions record-actions"><button class="btn small edit-record" data-id="${r.id}">Edit</button><button class="btn small toggle-record" data-id="${r.id}" data-archived="${r.archived?1:0}">${r.archived?'Obnoviť záznam':'Archivovať záznam'}</button><button class="btn small danger delete-record" data-id="${r.id}">Vymazať záznam</button><button class="btn small outline archive-job-row" data-job="${r.job_id}" data-active="${r.job_active?1:0}">${r.job_active?'Archivovať zákazku':'Obnoviť zákazku'}</button><button class="btn small danger-outline delete-job-row" data-job="${r.job_id}">Vymazať zákazku</button></td>`:''}</tr>`}).join('')||'<tr><td colspan="30" class="empty">Žiadne záznamy</td></tr>'
}
function bindOpenJobs(){$$('.open-row-job').forEach(b=>b.onclick=()=>go('jobdetail',+b.dataset.job))}
function bindRecordActions(reload){bindOpenJobs();if(state.user.role!=='admin')return;$$('.edit-record').forEach(b=>b.onclick=()=>go('new',{recordId:+b.dataset.id}));$$('.toggle-record').forEach(b=>b.onclick=async()=>{try{await api(`/api/records/${b.dataset.id}/${b.dataset.archived==='1'?'restore':'archive'}`,{method:'POST',body:'{}'});toast(b.dataset.archived==='1'?'Záznam obnovený.':'Záznam archivovaný.');await reload()}catch(e){toast(e.message,'error')}});$$('.delete-record').forEach(b=>b.onclick=async()=>{if(!confirm('Trvalo vymazať tento záznam?'))return;try{await api('/api/records/'+b.dataset.id,{method:'DELETE'});toast('Záznam vymazaný.');await reload()}catch(e){toast(e.message,'error')}});$$('.archive-job-row').forEach(b=>b.onclick=()=>archiveJob(+b.dataset.job,b.dataset.active==='1',reload));$$('.delete-job-row').forEach(b=>b.onclick=()=>deleteJob(+b.dataset.job,reload))}
function pdfDownload(params){downloadFile('/api/export/pdf?'+params.toString())}

async function renderJobDetail(id){
  if(state.user.role!=='admin')return renderOperatorJobDetail(id);
  setTitle('Zákazka / Job detail','Sumár, záznamy a exporty');const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Bratislava',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());$('#view').innerHTML='<div class="panel"><div class="panel-body">Načítavam…</div></div>';
  async function load(){
    const oldFrom=$('#jdFrom')?.value||'',oldTo=$('#jdTo')?.value||'';const qs=new URLSearchParams();if(oldFrom)qs.set('date_from',oldFrom);if(oldTo)qs.set('date_to',oldTo);const d=await api(`/api/jobs/${id}/summary?`+qs);const j=d.job,t=d.totals;
    $('#view').innerHTML=`<div class="job-hero"><div><button class="link-btn" id="backJobs">← Zákazky</button><div class="job-title-line"><h2>${esc(j.order_number)}</h2><span class="badge ${j.active?'green':'gray'}">${j.active?'Active':'Archived'}</span></div><p>${esc(j.brief_description)}</p><div class="chips"><span class="chip">Norm: ${esc(normLabel(j))}</span>${j.parts.map(p=>`<span class="chip">${esc(p.item_number)} — ${esc(p.part_name||'')}${j.norm_mode==='time'&&p.norm_per_hour?` · ${fmtNum(p.norm_per_hour,2)} ks/h`:''}</span>`).join('')}</div></div><div class="job-hero-actions"><button id="jobNewRecord" class="btn primary" ${j.active?'':'disabled'}>＋ Nový záznam</button><button id="jobEdit" class="btn">Edit job</button><button id="jobArchive" class="btn">${j.active?'Archive':'Restore'}</button><button id="jobDelete" class="btn danger">Delete</button></div></div><div class="panel"><div class="panel-head"><h3>Automatický reporting</h3></div><div class="panel-body"><div class="reporting-detail"><div>${j.reporting_enabled?`<span class="badge green">Zapnuté · ${esc(j.reporting_time||'08:00')}</span>`:'<span class="badge gray">Vypnuté</span>'}<div class="smalltext">${esc(j.reporting_recipients||'Bez príjemcov')}</div><div class="smalltext">${jobReportStatusText(j)}</div></div><button id="jdSendNow" class="btn">Odoslať report teraz</button></div></div></div><div class="panel"><div class="panel-body"><div class="toolbar"><label>Od / From<input id="jdFrom" type="date" value="${esc(oldFrom)}"></label><label>Do / To<input id="jdTo" type="date" value="${esc(oldTo)}"></label><button id="jdLoad" class="btn">Načítať</button><button id="jdPdf" class="btn primary">PDF report</button><button id="jdXlsx" class="btn">XLS report</button><label>Daily XLSM date<input id="jdDay" type="date" value="${today}"></label><button id="jdXlsm" class="btn">XLSM podľa šablóny</button></div></div></div><div class="kpis">${kpi('Checked',t.checked_items)}${kpi('OK',t.ok_items)}${kpi('NOK',t.nok_items)}${kpi('NOK rate',t.nok_rate+'%')}${kpi('Records',t.record_count)}</div><div class="panel"><div class="panel-head"><h3>Druhy chýb / Error types</h3></div><div class="panel-body chips">${j.errors.length?j.errors.map(e=>`<span class="chip">${esc(e.name)}</span>`).join(''):'<span class="muted">None</span>'}</div></div><div class="panel"><div class="table-wrap"><table><thead>${recordHeader(true,true)}</thead><tbody>${tableRows(d.records,true,true)}</tbody></table></div></div>`;
    $('#backJobs').onclick=()=>go('jobs');$('#jobNewRecord').onclick=()=>j.active&&go('new',id);$('#jobEdit').onclick=()=>openJob(j);$('#jobArchive').onclick=()=>archiveJob(id,!!j.active,load);$('#jobDelete').onclick=()=>deleteJob(id,()=>go('jobs'));$('#jdSendNow').onclick=()=>sendJobReportNow(id,load);$('#jdLoad').onclick=load;
    const params=()=>{const q=new URLSearchParams({job_id:id});if($('#jdFrom').value)q.set('date_from',$('#jdFrom').value);if($('#jdTo').value)q.set('date_to',$('#jdTo').value);return q};
    $('#jdPdf').onclick=()=>downloadFile('/api/export/pdf?'+params());$('#jdXlsx').onclick=()=>downloadFile('/api/export/xlsx?'+params());$('#jdXlsm').onclick=()=>downloadFile(`/api/export/daily-xlsm?job_id=${id}&date=${encodeURIComponent($('#jdDay').value)}`);bindRecordActions(load);addAnalyticsButton(id);
  }
  await load();
  addAnalyticsButton(id);
}

function addAnalyticsButton(id){
  if(state.view!=='jobdetail'||$('#openAnalytics'))return;
  const button=document.createElement('button');button.id='openAnalytics';button.className='btn primary';button.textContent='Analytický report · TOTAL / 30 dní';
  button.onclick=()=>renderAnalytics(id);$('#view').prepend(button);
}

async function renderAnalytics(id,partId=''){
  state.view='analytics';setTitle('Analytický report','TOTAL, posledných 30 dní, Pareto a vývoj');
  $('#view').innerHTML='<div class="panel"><div class="panel-body">Načítavam analytický report…</div></div>';
  try{
    const d=await api(`/api/jobs/${id}/analytics?`+new URLSearchParams(partId?{part_id:partId}:{}));
    if(state.view!=='analytics')return;
    const number=v=>Number(v).toLocaleString('sk-SK'),date=v=>v?v.split('-').reverse().join('.'):'—';
    const row=(label,r,cls='')=>`<tr class="${cls}"><td>${esc(label)}</td><td>${number(r.checked)}</td><td>${number(r.ok)}</td><td>${number(r.nok)}</td><td>${r.rate==null?'—':Number(r.rate).toLocaleString('sk-SK',{minimumFractionDigits:2,maximumFractionDigits:2})+' %'}</td>${d.errors.map(e=>`<td>${number(r.errors[e]||0)}</td>`).join('')}</tr>`;
    const plot=(key,title)=>`<section class="panel"><div class="panel-head"><h3>${title}</h3></div><div class="panel-body analytics-chart" role="img" aria-label="${title}">${d.charts[key]}</div></section>`;
    $('#view').innerHTML=`<button id="analyticsBack" class="btn">← Detail zákazky</button><div class="panel"><div class="panel-body"><h2>${esc(d.order)}</h2><p>${esc(d.description)}</p><p>${esc(d.location)} · ${esc(d.scope)}</p><div class="toolbar"><label>Diel<select id="analyticsPart"><option value="">Všetky diely</option>${d.parts.map(p=>`<option value="${p.id}" ${p.id===d.part_id?'selected':''}>${esc(p.item_number)}</option>`).join('')}</select></label><button id="analyticsPdf" class="btn primary">PDF s grafmi</button><button id="analyticsXlsx" class="btn">Excel s grafmi</button></div><p class="muted">TOTAL od ${date(d.first)} · Denné riadky ${date(d.start)} – ${date(d.as_of)} · Bez archivovaných záznamov</p></div></div><div class="panel"><div class="panel-head"><h3>Výsledky kontroly</h3></div><div class="table-wrap"><table class="analytics-table"><thead><tr><th>Dátum</th><th>Checked</th><th>OK</th><th>NOK</th><th>NOK rate</th>${d.errors.map(e=>`<th>${esc(e)}</th>`).join('')}</tr></thead><tbody>${row('TOTAL',d.total,'analytics-total')}${d.days.map(r=>row(date(r.date),r)).join('')}${row('Súčet 30 dní',d.recent,'analytics-total')}</tbody></table></div></div><p class="muted">Pareto: stĺpce = počet chýb, krivka = kumulovaný podiel, prerušovaná čiara = 80 %. Pri viac než 8 chybách sa menšie zlúčia do „Ostatné chyby“.</p>${plot('pareto_total','Pareto TOTAL')}${plot('pareto_recent','Pareto za posledných 30 dní')}${plot('volume','Denný Checked – posledných 30 dní')}${plot('rate','Denný NOK % – posledných 30 dní')}${plot('cumulative','Kumulovaný Checked – po mesiacoch')}`;
    $('#analyticsBack').onclick=()=>go('jobdetail',id);$('#analyticsPart').onchange=e=>renderAnalytics(id,e.target.value);
    const params=new URLSearchParams({job_id:id,analytics:'1'});if(partId)params.set('part_id',partId);
    $('#analyticsPdf').onclick=()=>downloadFile('/api/export/pdf?'+params);$('#analyticsXlsx').onclick=()=>downloadFile('/api/export/xlsx?'+params);
  }catch(e){
    if(state.view!=='analytics')return;
    $('#view').innerHTML=`<div class="panel"><div class="panel-body"><p role="alert">${esc(e.message)}</p><button class="btn" id="analyticsRetry">Skúsiť znova</button><button class="btn" id="analyticsBack">Späť</button></div></div>`;
    $('#analyticsRetry').onclick=()=>renderAnalytics(id,partId);$('#analyticsBack').onclick=()=>go('jobdetail',id);
  }
}

async function renderOperatorJobDetail(id){
  setTitle('Zákazka / Job detail','Moje záznamy, súhrn a exporty');
  $('#view').innerHTML='<div class="panel"><div class="panel-body">Načítavam…</div></div>';
  const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Bratislava',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  async function load(){
    const from=$('#opFrom')?.value||'',to=$('#opTo')?.value||'',day=$('#opDay')?.value||today;
    const params=new URLSearchParams({job_id:id});if(from)params.set('date_from',from);if(to)params.set('date_to',to);
    try{
      // /records enforces the authenticated operator's ownership on the server.
      const [jobData,recordData]=await Promise.all([api(`/api/jobs/${id}`),api('/api/records?'+params)]);
      if(state.view!=='jobdetail')return;
      const j=jobData.job,rows=recordData.records;
      if(!j)throw new Error('Zákazka neexistuje.');
      const totals=rows.reduce((t,r)=>({checked:t.checked+Number(r.checked_items||0),ok:t.ok+Number(r.ok_items||0),nok:t.nok+Number(r.nok_items||0)}),{checked:0,ok:0,nok:0});
      $('#view').innerHTML=`<div class="job-hero"><div><button class="link-btn" id="opBack">← Moje záznamy</button><h2>${esc(j.order_number)}</h2><p>${esc(j.brief_description)}</p><div class="muted">Zobrazené sú iba tvoje záznamy. Úpravy vykonáva administrátor.</div></div></div><div class="panel"><div class="panel-body"><div class="toolbar"><label>Od / From<input id="opFrom" type="date" value="${esc(from)}"></label><label>Do / To<input id="opTo" type="date" value="${esc(to)}"></label><button id="opLoad" class="btn">Načítať</button><button id="opPdf" class="btn primary">PDF report</button><label>Dátum XLSM<input id="opDay" type="date" value="${esc(day)}"></label><button id="opXlsm" class="btn">XLSM podľa šablóny</button></div></div></div><div class="kpis">${kpi('Checked',totals.checked)}${kpi('OK',totals.ok)}${kpi('NOK',totals.nok)}${kpi('NOK rate',(totals.checked?(totals.nok/totals.checked*100).toFixed(2):'0')+'%')}${kpi('Records',rows.length)}</div><div class="panel"><div class="table-wrap"><table><thead>${recordHeader(false,false)}</thead><tbody>${tableRows(rows,false,false)}</tbody></table></div></div>`;
      $('#opBack').onclick=()=>go('mine');$('#opLoad').onclick=load;
      $('#opPdf').onclick=()=>{const q=new URLSearchParams({job_id:id});if($('#opFrom').value)q.set('date_from',$('#opFrom').value);if($('#opTo').value)q.set('date_to',$('#opTo').value);downloadFile('/api/export/pdf?'+q)};
      $('#opXlsm').onclick=()=>downloadFile(`/api/export/daily-xlsm?job_id=${id}&date=${encodeURIComponent($('#opDay').value)}`);
      bindOpenJobs();
      addAnalyticsButton(id);
    }catch(e){
      if(state.view!=='jobdetail')return;
      $('#view').innerHTML=`<div class="panel"><div class="panel-body"><p role="alert">Detail sa nepodarilo načítať: ${esc(e.message)}</p><button id="opRetry" class="btn primary">Skúsiť znova</button><button id="opBack" class="btn">Moje záznamy</button></div></div>`;
      $('#opRetry').onclick=load;$('#opBack').onclick=()=>go('mine');
    }
  }
  await load();
}

function recordHeader(admin=true,actions=true){return `<tr><th>Date</th><th>Shift</th><th>Order</th><th>Item number</th><th>Part name</th><th>Delivery note</th><th>Checked</th><th>OK</th><th>NOK</th><th>Chyby / ks</th><th>R.OK</th><th>R.NOK</th><th>Working time</th><th>Norm s/item</th><th>Target/h</th><th>Actual/h</th><th>Deviation</th>${admin?'<th>Operator</th>':''}<th>Note</th>${actions?'<th>Status</th><th>Actions</th>':''}</tr>`}

async function renderMyRecords(){
  setTitle('Moje záznamy / My records','História operátora, číslo dielu a export');await loadJobs(false);const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Bratislava',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());const rows=(await api('/api/records')).records;
  $('#view').innerHTML=`<div class="panel"><div class="panel-head"><h3>Report</h3></div><div class="panel-body"><label>Hľadať v mojich záznamoch<input id="mySearch" type="search" placeholder="Časť textu, diel, dodací list, chyba…"></label><div class="toolbar"><label>Zákazka<select id="myPdfJob"><option value="">— Select —</option>${state.jobs.map(jobOption).join('')}</select></label><label>Dátum<input id="myPdfDate" type="date" value="${today}"></label><button id="myPdf" class="btn primary">PDF report</button><button id="myXlsm" class="btn">XLSM podľa šablóny</button></div><div class="muted smalltext">Report obsahuje iba tvoje záznamy.</div></div></div><div class="panel"><div class="table-wrap"><table><thead>${recordHeader(false,false)}</thead><tbody id="myRecordsBody">${tableRows(rows,false,false)}</tbody></table></div></div>`;
  let timer,requestId=0;$('#mySearch').oninput=()=>{clearTimeout(timer);const id=++requestId;timer=setTimeout(async()=>{try{const data=await api('/api/records?'+new URLSearchParams({search:$('#mySearch').value}));if(id!==requestId||!$('#myRecordsBody'))return;$('#myRecordsBody').innerHTML=tableRows(data.records,false,false);bindOpenJobs()}catch(e){toast(e.message,'error')}},250)};
  bindOpenJobs();$('#myPdf').onclick=()=>{if(!$('#myPdfJob').value)return toast('Vyber zákazku.','error');downloadFile('/api/export/pdf?'+new URLSearchParams({job_id:$('#myPdfJob').value,date:$('#myPdfDate').value}))};$('#myXlsm').onclick=()=>{if(!$('#myPdfJob').value)return toast('Vyber zákazku.','error');downloadFile(`/api/export/daily-xlsm?job_id=${encodeURIComponent($('#myPdfJob').value)}&date=${encodeURIComponent($('#myPdfDate').value)}`)};
}

function searchText(v){return String(v??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase()}
function maskWorkTime(v){const text=String(v).replace(/[^0-9:]/g,'');if(text.includes(':')){const [hours,...minutes]=text.split(':');return hours.slice(0,2)+':'+minutes.join('').slice(0,2)}const digits=text.slice(0,4);return digits.length>2?digits.slice(0,2)+':'+digits.slice(2):digits}
function normalizeWorkTime(v){const m=String(v).trim().match(/^(\d+):([0-5]?\d)$/);return m?m[1].padStart(2,'0')+':'+m[2].padStart(2,'0'):v}
function recordErrors(r){const counts=r.error_counts_obj||{};return (r.job_snapshot_obj?.errors||[]).filter(e=>Number(counts[String(e.id)])>0).map(e=>esc(e.name)+' — '+esc(counts[String(e.id)])+' ks').join('<br>')||'—'}
function multiSelectMarkup(id,label,options){return `<div class="multi-field"><label class="field-label" for="${id}Input">${esc(label)}</label><div class="multi-select direct-multi" id="${id}"><div class="multi-input-wrap"><input id="${id}Input" class="multi-direct-input" type="text" placeholder="Všetky" autocomplete="off" aria-expanded="false" aria-controls="${id}Options"><span aria-hidden="true">▾</span></div><div class="multi-popover" id="${id}Options" hidden><div class="multi-options">${options.map(o=>`<label><input type="checkbox" value="${esc(o.value)}"><span>${esc(o.label)}</span></label>`).join('')||'<div class="muted">Žiadne možnosti</div>'}</div></div></div></div>`}
function closeMulti(d){const input=d.querySelector('.multi-direct-input');if(!input)return;d.querySelector('.multi-popover').hidden=true;input.setAttribute('aria-expanded','false');input.value='';d.querySelectorAll('.multi-options label').forEach(l=>l.hidden=false)}
function bindMulti(id){const d=$('#'+id);if(!d)return;const input=d.querySelector('.multi-direct-input');const upd=()=>{const c=[...d.querySelectorAll('input:checked')];input.placeholder=c.length?`${c.length} vybrané`:'Všetky'};const open=()=>{document.querySelectorAll('.direct-multi').forEach(other=>{if(other!==d)closeMulti(other)});d.querySelector('.multi-popover').hidden=false;input.setAttribute('aria-expanded','true')};d.querySelectorAll('input[type=checkbox]').forEach(x=>x.onchange=upd);input.onfocus=open;input.onclick=open;input.oninput=()=>{open();const q=searchText(input.value);d.querySelectorAll('.multi-options label').forEach(l=>l.hidden=!searchText(l.textContent).includes(q))};d.onkeydown=e=>{if(e.key==='Escape'){input.focus();closeMulti(d)}else if(e.key==='ArrowDown'&&e.target===input){e.preventDefault();open();[...d.querySelectorAll('.multi-options label')].find(l=>!l.hidden)?.querySelector('input').focus()}};d.addEventListener('focusout',e=>{if(!d.contains(e.relatedTarget))closeMulti(d)});upd()}

function getMulti(id){return [...$('#'+id).querySelectorAll('input:checked')].map(x=>x.value)}

async function renderRecords(){
  setTitle('Záznamy / Records','Viacnásobné filtre, reporty, archivácia a editácia');await Promise.all([loadJobs(true),loadUsers()]);
  const partOptions=[];const seen=new Set();for(const j of state.jobs)for(const p of j.parts||[]){if(!seen.has(p.id)){seen.add(p.id);partOptions.push({value:p.id,label:`${p.item_number}${p.part_name?' — '+p.part_name:''}`})}}
  $('#view').innerHTML=`<div class="panel"><div class="panel-body"><div class="records-filters">${multiSelectMarkup('fJob','Zákazka / Job',state.jobs.map(j=>({value:j.id,label:`${j.order_number}${j.active?'':' [ARCHIVED]'}`})))}${multiSelectMarkup('fPart','Číslo dielu / Item',partOptions)}${multiSelectMarkup('fShift','Zmena / Shift',[{value:'R',label:'R. – Ranná'},{value:'P',label:'P. – Poobedná'},{value:'N',label:'N. – Nočná'}])}${multiSelectMarkup('fUser','Používateľ / User',state.users.map(u=>({value:u.id,label:u.display_name})))}<label>Hľadať v záznamoch<input id="fSearch" type="search" placeholder="Časť textu, diel, dodací list, chyba…"></label><label>Od / From<input id="fFrom" type="date"></label><label>Do / To<input id="fTo" type="date"></label><label>Stav záznamu<select id="fRecordStatus"><option value="active">Aktívne</option><option value="archived">Archivované</option><option value="all">Všetky</option></select></label></div><div class="report-actions"><button id="loadRecords" class="btn primary">Načítať</button><button id="recordsPdf" class="btn primary">PDF report</button><button id="recordsXls" class="btn">XLS report</button></div><div class="muted smalltext">V roletových filtroch môžeš označiť viac zákaziek, dielov, zmien aj používateľov. Červený riadok = výkon mimo ±10 % hodinovej normy.</div></div></div><div class="panel"><div class="table-wrap"><table><thead>${recordHeader(true,true)}</thead><tbody id="recordsBody"></tbody></table></div></div>`;
  ['fJob','fPart','fShift','fUser'].forEach(bindMulti);
  function params(){const q=new URLSearchParams();const jobs=getMulti('fJob'),parts=getMulti('fPart'),shifts=getMulti('fShift'),users=getMulti('fUser');if(jobs.length)q.set('job_id',jobs.join(','));if(parts.length)q.set('part_id',parts.join(','));if(shifts.length)q.set('shift',shifts.join(','));if(users.length)q.set('operator_id',users.join(','));if($('#fFrom').value)q.set('date_from',$('#fFrom').value);if($('#fTo').value)q.set('date_to',$('#fTo').value);q.set('record_status',$('#fRecordStatus').value);if($('#fSearch').value.trim())q.set('search',$('#fSearch').value.trim());return q}
  let requestId=0;async function load(){const id=++requestId;const rows=(await api('/api/records?'+params())).records;if(id!==requestId||!$('#recordsBody'))return;$('#recordsBody').innerHTML=tableRows(rows,true,true);bindRecordActions(load)}
  let searchTimer;$('#fSearch').oninput=()=>{++requestId;clearTimeout(searchTimer);searchTimer=setTimeout(()=>load().catch(e=>toast(e.message,'error')),250)};$('#loadRecords').onclick=()=>load().catch(e=>toast(e.message,'error'));$('#recordsPdf').onclick=()=>downloadFile('/api/export/records-pdf?'+params());$('#recordsXls').onclick=()=>downloadFile('/api/export/records-xlsx?'+params());await load();
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

document.addEventListener('focusout',event=>{if(event.target.id==='rOperatorTime'){event.target.value=normalizeWorkTime(event.target.value);event.target.dispatchEvent(new Event('input',{bubbles:true}))}});

document.addEventListener('pointerdown',event=>{document.querySelectorAll('.direct-multi').forEach(d=>{if(!d.contains(event.target))closeMulti(d)})});
document.addEventListener('input',event=>{const input=event.target;if(input.id!=='rOperatorTime')return;const previous=input.value;const caret=input.selectionStart;const formatted=maskWorkTime(previous);if(formatted!==previous){input.value=formatted;if(caret!==null){const pos=Math.max(0,caret+formatted.length-previous.length);input.setSelectionRange(pos,pos)}}},true);
