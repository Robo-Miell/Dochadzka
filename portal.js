const el=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const today=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Bratislava',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const number=v=>Number(v||0).toLocaleString('sk-SK',{maximumFractionDigits:2});
let me=null, locations=[], shifts=[];
async function api(path,options={}){
  const r=await fetch(path,{...options,headers:{'Content-Type':'application/json',Authorization:'Bearer '+(localStorage.getItem('dochadzka_token')||''),...options.headers}});
  let d={};try{d=await r.json()}catch{}
  if(!r.ok){if(r.status===401 && path!='/api/auth/login'){localStorage.removeItem('dochadzka_token');showLogin()}throw new Error(typeof d.detail==='string'?d.detail:'Požiadavka zlyhala. Skontroluj zadané hodnoty.')}
  return d;
}
function showLogin(){el('moduleChooser').hidden=true;el('loginPanel').hidden=false;el('workspace').hidden=true}
function period(){return new URLSearchParams({date_from:el('dateFrom').value,date_to:el('dateTo').value})}
function notify(message,error=false){el('message').textContent=message;el('message').className=error?'danger-text':''}
async function loadSummary(){
  const d=await api('/api/unified/summary?'+period()), t=d.totals;
  const cards=[['Schválená práca',number(t.approved_hours)+' h','Dochádzka'],['Čaká na schválenie',number(d.pending_records),number(t.pending_hours)+' h práce'],['Checked',number(t.checked),'Kontrolované kusy'],['NOK',number(t.nok),t.checked?number(t.nok/t.checked*100)+' % z kontroly':'0 % z kontroly'],['Mimo normy',number(t.outside_norm),'Záznamy mimo tolerancie ±10 %']];
  el('metrics').innerHTML=cards.map(c=>`<div class="card metric"><span>${c[0]}</span><b>${c[1]}</b><small>${c[2]}</small></div>`).join('');
  el('periodLabel').textContent=d.date_from+' — '+d.date_to;
  el('peopleBody').innerHTML=d.people.map(p=>`<tr><td><strong>${esc(p.name)}</strong></td><td>${number(p.approved_hours)}</td><td>${number(p.pending_hours)}</td><td>${number(p.operator_hours)}</td><td>${number(p.ct_hours)}</td><td>${number(p.checked)}</td><td>${number(p.ok)}</td><td>${number(p.nok)}</td><td class="${p.outside_norm?'danger-text':''}">${number(p.outside_norm)}</td></tr>`).join('')||'<tr><td colspan="9">Žiadne záznamy.</td></tr>';
}
async function loadAttendance(){
  const rows=await api('/api/attendance?'+period());
  el('attendanceList').innerHTML=rows.map(r=>`<article class="attendance-item"><div class="section-title"><strong>${esc(r.work_date)} · ${esc(r.type)}</strong><span class="badge ${esc(r.status)}">${({approved:'Schválené',pending:'Čaká',rejected:'Zamietnuté'})[r.status]}</span></div><p>${esc(r.location_name)} · ${esc(r.time_from||'—')} – ${esc(r.time_to||'—')} · ${number(r.hours)} h${r.km?' · '+number(r.km)+' km':''}</p><p>${esc(r.note)}</p>${r.status==='pending'?`<button class="delete-attendance" data-id="${r.id}">Vymazať čakajúci záznam</button>`:''}</article>`).join('')||'<p>V tomto období nemáš žiadnu dochádzku.</p>';
  document.querySelectorAll('.delete-attendance').forEach(b=>b.onclick=async()=>{if(!confirm('Vymazať tento dochádzkový záznam?'))return;try{await api('/api/attendance/'+b.dataset.id,{method:'DELETE'});await reload()}catch(e){notify(e.message,true)}});
}
function locationChanged(){
  const id=Number(el('workLocation').value), location=locations.find(l=>l.id===id);
  el('kmLabel').hidden=!location?.km_enabled;
  if(!location?.km_enabled)el('workKm').value='0';
  el('workShift').innerHTML='<option value="">Vlastný čas</option>'+shifts.filter(s=>s.location_id===id).map(s=>`<option value="${s.id}">${esc(s.name)} · ${esc(s.time_from)}–${esc(s.time_to)}</option>`).join('');
}
async function reload(){
  try{notify('');await loadSummary();if(me.role!=='admin')await loadAttendance()}catch(e){notify(e.message,true)}
}
async function enter(){
  me=await api('/api/me');el('loginPanel').hidden=true;el('workspace').hidden=false;el('userName').textContent=me.name;
  const admin=me.role==='admin';el('employeesLink').hidden=!admin;
  el('attendanceLink').href=admin?'/admin':'/?view=attendance';el('attendanceAction').href=admin?'/admin':'/?view=attendance';el('attendanceAction').textContent=admin?'Spravovať dochádzku':'Zadať dochádzku';
  if(admin&&!['overview','attendance'].includes(new URLSearchParams(location.search).get('view'))){el('workspace').hidden=true;el('moduleChooser').hidden=false;el('chooserUser').textContent=me.name+' · ADMIN';return}
  if(new URLSearchParams(location.search).get('next')==='quality'){location.replace('/quality/');return}
  if(new URLSearchParams(location.search).get('view')==='attendance'&&admin){location.replace('/admin');return}
  if(!admin){
    el('employeeAttendance').hidden=false;
    [locations,shifts]=await Promise.all([api('/api/locations'),api('/api/shifts')]);
    el('workLocation').innerHTML=locations.map(l=>`<option value="${l.id}">${esc(l.name)}</option>`).join('');
    el('saveAttendance').disabled=!locations.length;
    if(!locations.length)el('attendanceMessage').textContent='Administrátor ti musí priradiť prevádzku pred zadaním dochádzky.';
    el('workDate').value=today();locationChanged();
  }
  await reload();
  if(new URLSearchParams(location.search).get('view')==='attendance')el('employeeAttendance').scrollIntoView({behavior:'smooth'});
}
el('dateFrom').value=el('dateTo').value=today();
el('loginForm').onsubmit=async e=>{e.preventDefault();el('loginError').textContent='';el('loginButton').disabled=true;try{const d=await api('/api/auth/login',{method:'POST',body:JSON.stringify({login:el('loginName').value.trim(),password:el('loginPassword').value})});localStorage.setItem('dochadzka_token',d.access_token);el('loginPassword').value='';await enter()}catch(err){el('loginError').textContent=err.message}finally{el('loginButton').disabled=false}};
el('periodForm').onsubmit=e=>{e.preventDefault();reload()};
el('todayButton').onclick=()=>{el('dateFrom').value=el('dateTo').value=today();reload()};
el('monthButton').onclick=()=>{el('dateTo').value=today();el('dateFrom').value=today().slice(0,8)+'01';reload()};
el('logout').onclick=()=>window.miellLogout();
el('workLocation').onchange=locationChanged;
el('workType').onchange=()=>{const work=el('workType').value==='Práca';el('workTimes').hidden=!work;el('workShift').disabled=!work};
el('workShift').onchange=()=>{const s=shifts.find(x=>x.id===Number(el('workShift').value));if(s){el('timeFrom').value=s.time_from;el('timeTo').value=s.time_to;el('breakMinutes').value=s.break_minutes;el('deductBreak').checked=s.deduct_break}};
el('attendanceForm').onsubmit=async e=>{
  e.preventDefault();el('saveAttendance').disabled=true;el('attendanceMessage').textContent='';
  try{const work=el('workType').value==='Práca';await api('/api/attendance',{method:'POST',body:JSON.stringify({work_date:el('workDate').value,location_id:Number(el('workLocation').value),type:el('workType').value,time_from:work?el('timeFrom').value:null,time_to:work?el('timeTo').value:null,break_minutes:work?Number(el('breakMinutes').value):0,deduct_break:work&&el('deductBreak').checked,km:work?Number(el('workKm').value):0,note:el('workNote').value,billing_confirmed:el('billingConfirmed').checked})});el('billingConfirmed').checked=false;el('workNote').value='';el('attendanceMessage').textContent='Dochádzka bola odoslaná na schválenie.';await reload()}catch(err){el('attendanceMessage').textContent=err.message}finally{el('saveAttendance').disabled=false}
};
el('myPdf').onclick=async()=>{try{const d=await api('/api/my/export-link?'+period());const a=document.createElement('a');a.href=d.url;a.download='dochadzka.pdf';a.click()}catch(e){notify(e.message,true)}};
el('passwordButton').onclick=()=>{el('passwordForm').reset();el('passwordMessage').textContent='';el('passwordDialog').showModal()};
el('closePassword').onclick=()=>el('passwordDialog').close();
el('passwordForm').onsubmit=async e=>{e.preventDefault();try{if(el('newPassword').value!==el('confirmPassword').value)throw new Error('Nové heslá sa nezhodujú.');await api('/api/me/change-password',{method:'POST',body:JSON.stringify({current_password:el('currentPassword').value,new_password:el('newPassword').value})});localStorage.removeItem('dochadzka_token');location.href='/?password=changed'}catch(err){el('passwordMessage').textContent=err.message}};
if(new URLSearchParams(location.search).get('password')==='changed')el('loginError').textContent='Heslo bolo zmenené. Prihlás sa novým heslom.';
if(localStorage.getItem('dochadzka_token'))enter().catch(e=>{showLogin();el('loginError').textContent=e.message});else showLogin();
