(() => {
  const labels={work_date:'Dátum',record_date:'Dátum',user_id:'Zamestnanec (ID)',location_id:'Prevádzka (ID)',job_id:'Zákazka (ID)',part_id:'Diel (ID)',type:'Typ',time_from:'Od',time_to:'Do',break_minutes:'Prestávka (min)',deduct_break:'Odpočet prestávky',km:'Kilometre',status:'Stav',note:'Poznámka',billing_confirmed:'Potvrdená fakturácia',billing_confirmed_at:'Čas potvrdenia',checked_items:'Checked',ok_items:'OK',nok_items:'NOK',reworked_ok:'Reworked OK',reworked_nok:'Reworked NOK',delivery_note:'Dodací list',error_counts:'Chyby a počty',shift:'Zmena',work_time_seconds:'Pracovný čas (s)',norm_seconds_per_item:'Norma (s/ks)',archived:'Archivované',job_snapshot:'Údaje zákazky',part_snapshot:'Údaje dielu',created_at:'Vytvorené'};
  const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function value(v){if(v===true)return 'Áno';if(v===false)return 'Nie';if(v==='approved')return 'Schválené';if(v==='pending')return 'Čaká';if(v==='rejected')return 'Zamietnuté';return typeof v==='object'&&v!==null?JSON.stringify(v):v??'—'}
  function historyValue(key, snapshot){
    if(key!=='error_counts')return value(snapshot[key]);
    if(snapshot[key]==null)return '—';
    function object(raw){try{return typeof raw==='string'?JSON.parse(raw):raw||{}}catch{return {}}}
    const counts=object(snapshot.error_counts), job=object(snapshot.job_snapshot);
    const names=new Map((Array.isArray(job.errors)?job.errors:[]).map(error=>[String(error.id),error.name]));
    return Object.entries(counts).map(([id,count])=>`${names.get(id)||'Neznáma chyba (ID '+id+')'}: ${count} ks`).join('\n')||'Žiadne chyby';
  }
  const dialog=document.createElement('dialog');dialog.style.cssText='width:min(1050px,96vw);max-height:85vh;border:1px solid #dce5e0;border-radius:14px;padding:20px;color:#172124;background:white';document.body.append(dialog);
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-history-module]');if(!button)return;
    const module=button.dataset.historyModule,id=button.dataset.historyId;
    dialog.innerHTML='<button type="button" style="float:right" data-history-close>Zavrieť ×</button><h3>História zmien'+(id?' — záznam #'+esc(id):' — najnovších 500 zmien')+'</h3><p>Sleduje zmeny od zavedenia histórie. Staršie úpravy nie sú spätne dostupné.</p><div data-history-content>Načítavam…</div>';
    dialog.querySelector('[data-history-close]').onclick=()=>dialog.close();dialog.showModal();
    const content=dialog.querySelector('[data-history-content]');
    try{
      const endpoint=module==='quality'?'/quality/api/record-history':'/api/attendance-history';
      const response=await fetch(endpoint+(id?'?record_id='+encodeURIComponent(id):''),{headers:{Authorization:'Bearer '+localStorage.getItem('dochadzka_token')}});
      if(!response.ok)throw new Error('Históriu sa nepodarilo načítať ('+response.status+').');
      const data=await response.json();
      content.innerHTML=data.history.map(row=>{
        const keys=[...new Set([...Object.keys(row.before),...Object.keys(row.after)])].filter(k=>k!=='id'&&JSON.stringify(row.before[k])!==JSON.stringify(row.after[k]));
        return `<section style="border-top:1px solid #dce5e0;padding:14px 0"><b>${esc(new Date(row.at).toLocaleString('sk-SK',{timeZone:'Europe/Bratislava'}))} · ${esc(row.actor.name)} (${esc(row.actor.login)})</b><p>Záznam #${esc(row.record_id)} · ${esc(({create:'Vytvorenie',update:'Úprava / zmena stavu',archive:'Archivácia',restore:'Obnovenie',delete:'Vymazanie'})[row.action]||row.action)}</p><div style="overflow:auto"><table style="min-width:550px;width:100%;table-layout:fixed"><thead><tr><th>Pole</th><th>Pôvodná hodnota</th><th>Nová hodnota</th></tr></thead><tbody>${keys.map(k=>`<tr><td style="white-space:normal">${esc(labels[k]||k)}</td><td style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(historyValue(k,row.before))}</td><td style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(historyValue(k,row.after))}</td></tr>`).join('')}</tbody></table></div></section>`;
      }).join('')||'<p>Zatiaľ nie sú zaznamenané žiadne zmeny.</p>';
    }catch(error){content.textContent=error.message}
  });
})();
