(()=>{
const box=document.getElementById('presencePanel');if(!box)return;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let busy=false,loading=false,state=null;
async function api(path,body){const r=await fetch('/api/presence/'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',Authorization:'Bearer '+localStorage.getItem('dochadzka_token')},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.detail||'Prítomnosť sa nedá načítať');return d}
const time=s=>new Date(s).toLocaleString('sk-SK',{timeZone:'Europe/Bratislava'});
async function refresh(){
 if(loading||busy||!localStorage.getItem('dochadzka_token')||document.hidden)return;loading=true;
 try{
  if(box.dataset.admin==='1'){
   const d=await api('overview');box.innerHTML='<h3>Aktuálne v práci</h3><p>Stav podľa príchodov a odchodov · aktualizácia každých 30 sekúnd</p>'+d.locations.map(l=>`<section style="margin:12px 0;padding:12px;border:1px solid #dce5e0;border-radius:10px"><strong>${esc(l.name)} · ${l.people.length}</strong>${l.people.map(p=>`<p>${esc(p.name)} (${esc(p.personal_number)}) — od ${time(p.started_at)} ${p.overdue?' · ⚠ Viac než 12 hodín':''}${!p.email_configured?' · E-mail nie je nastavený':''}</p>`).join('')||'<p>Nikto nie je prihlásený v práci.</p>'}</section>`).join('');
  }else{
   state=await api('me');const r=await fetch('/api/locations',{headers:{Authorization:'Bearer '+localStorage.getItem('dochadzka_token')}});if(!r.ok)throw Error('Prevádzky sa nedajú načítať');const locations=await r.json();
   const selected=box.querySelector('select')?.value;
   box.innerHTML=`<h3>Moja prítomnosť</h3><p>${state.present?'V práci: '+esc(state.location_name)+' · od '+time(state.started_at):'Momentálne nie si označený ako prítomný.'}</p>${state.present?'':`<label>Prevádzka<select id="presenceLocation">${locations.map(l=>`<option value="${l.id}" ${String(l.id)===selected?'selected':''}>${esc(l.name)}</option>`).join('')}</select></label>`}<button class="primary" id="presenceAction" ${!state.present&&!locations.length?'disabled':''}>${state.present?'Odchod z práce':'Príchod do práce'}</button><p class="hint">Samostatná evidencia prítomnosti. Výkaz dochádzky vyplň ako doteraz.${state.email_configured?'':' Pre pripomienku po 12 hodinách musí admin doplniť tvoj e-mail.'}</p>`;
   box.querySelector('button').onclick=async()=>{busy=true;box.querySelector('button').disabled=true;try{await api(state.present?'check-out':'check-in',state.present?{presence_key:state.presence_key}:{location_id:Number(box.querySelector('select').value)})}catch(e){alert(e.message)}finally{busy=false;await refresh()}};
  }
 }catch(e){box.innerHTML=`<p role="alert">${esc(e.message)}</p><button id="presenceRetry">Obnoviť prítomnosť</button>`;box.querySelector('button').onclick=refresh}finally{loading=false}
}
window.miellPresenceRefresh=refresh;refresh();setInterval(refresh,30000);document.addEventListener('visibilitychange',refresh);
})();
