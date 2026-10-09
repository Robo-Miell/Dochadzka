(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function request(path,body={}){
    const r=await fetch('/quality/api/'+path,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+localStorage.getItem('dochadzka_token')},body:JSON.stringify(body)});
    const d=await r.json();if(!r.ok)throw new Error(d.detail||d.error||'Požiadavka zlyhala');return d;
  }
  window.miellOktorun=function(){
    const view=document.getElementById('view'),result=view.querySelector('.result-card'),select=view.querySelector('#rJob');
    const box=document.createElement('section');box.className='panel oktorun-panel';box.style.marginBottom='18px';view.prepend(box);
    let job=null,form=null,busy=false;
    function gate(allowed){result.hidden=!allowed;result.inert=!allowed;const time=view.querySelector('#normInputWrap');if(time)time.hidden=!allowed}
    gate(false);box.innerHTML='<div class="panel-body">Vyber zákazku. Pred začatím vyplň OKtoRUN.</div>';
    function show(d){
      form=d;gate(d.approved);
      if(d.approved){box.innerHTML=d.passed===false?'<div class="panel-body" role="alert"><b style="color:#b42318">OKtoRUN obsahuje odpoveď NIE. Kontaktuj koordinátora.</b><p>Záznamy môžeš zadávať. Upozornenie pre Project Managera je evidované v systéme.</p></div>':'<div class="panel-body"><b>✓ OKtoRUN vyhovuje.</b> Môžeš zadávať výsledky pre túto zákazku.</div>';return}
      box.innerHTML=`<div class="panel-head"><h3>OKtoRUN - kontrola pred začatím práce</h3></div><div class="panel-body"><p><b>${esc(job.order_number)}</b> · ${esc(d.revision)}</p><p>Vyplň všetky otázky. Pri odpovedi NIE kontaktuj koordinátora. Zadanie záznamu zostane povolené.</p><form id="oktorunForm">${d.questions.map(q=>`<fieldset style="border:1px solid #dce5e0;border-radius:8px;margin:10px 0;padding:12px"><legend>${esc(q.id)}. ${esc(q.text)}</legend><div style="display:flex;gap:24px"><label style="display:flex;flex-direction:row;align-items:center"><input style="width:auto" type="radio" name="ok-${q.id}" value="yes" required> ÁNO</label><label style="display:flex;flex-direction:row;align-items:center"><input style="width:auto" type="radio" name="ok-${q.id}" value="no" required> NIE</label></div></fieldset>`).join('')}<p id="oktorunError" role="alert"></p><button class="btn primary">Vyhodnotiť OKtoRUN</button></form></div>`;
      box.querySelector('form').onsubmit=async e=>{
        e.preventDefault();if(busy)return;busy=true;select.disabled=true;box.querySelector('button').disabled=true;
        const answers=Object.fromEntries(d.questions.map(q=>[q.id,box.querySelector(`input[name="ok-${q.id}"]:checked`).value==='yes']));
        try{
          const r=await request(`jobs/${job.id}/oktorun/submit`,{generation:d.generation,answers});
          if(r.passed)show({...d,approved:true,passed:true});
          else{
            gate(true);box.innerHTML=`<div class="panel-body"><h3 style="color:#b42318">OKtoRUN nevyhovuje</h3><p><b>Kontaktuj koordinátora. Záznam môžeš zadať aj pri odpovedi NIE.</b></p><p>${r.email_pending?'E-mail zatiaľ nebol odoslaný. Systém ho skúsi odoslať znova; kontaktuj koordinátora priamo.':'Project Managerovi zákazky bolo odoslané e-mailové upozornenie.'}</p><p>Po odstránení nedostatkov môžeš vykonať novú kontrolu.</p><button class="btn" id="oktorunRetry">Nedostatky odstránené - vyplniť znova</button><p role="alert" id="oktorunError"></p></div>`;
            box.querySelector('button').onclick=async()=>{if(busy)return;busy=true;select.disabled=true;try{show(await request(`jobs/${job.id}/oktorun/retry`,{generation:form.generation}))}catch(err){box.querySelector('#oktorunError').textContent=err.message}finally{busy=false;select.disabled=false}};
          }
        }catch(err){if(box.querySelector('#oktorunError'))box.querySelector('#oktorunError').textContent=err.message}
        finally{busy=false;select.disabled=false;const b=box.querySelector('button');if(b)b.disabled=false}
      };
    }
    return {async change(j){
      gate(false);job=j;if(!j){box.innerHTML='<div class="panel-body">Vyber zákazku pre OKtoRUN.</div>';return}
      busy=true;select.disabled=true;box.innerHTML='<div class="panel-body">Načítavam OKtoRUN…</div>';
      try{show(await request(`jobs/${j.id}/oktorun/start`))}catch(err){box.innerHTML=`<div class="panel-body">${esc(err.message)} Obnov stránku a skús znova.</div>`}finally{busy=false;select.disabled=false}
    }};
  };
  document.addEventListener('click',async e=>{
    if(!e.target.closest('[data-oktorun-history]'))return;
    const dialog=document.createElement('dialog');dialog.className='modal';dialog.style.maxHeight='85vh';dialog.innerHTML='<div class="panel-body"><button class="btn">Zavrieť</button><h3>História OKtoRUN</h3><div class="oktorun-list">Načítavam…</div></div>';document.body.append(dialog);dialog.querySelector('button').onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();dialog.showModal();
    try{const r=await fetch('/quality/api/oktorun-history',{headers:{Authorization:'Bearer '+localStorage.getItem('dochadzka_token')}});if(!r.ok)throw new Error('História nie je dostupná');const d=await r.json();dialog.querySelector('.oktorun-list').innerHTML=d.checks.map(c=>{const actor=JSON.parse(c.actor),qs=JSON.parse(c.questions),answers=JSON.parse(c.answers);return `<details style="padding:12px 0;border-bottom:1px solid #ddd"><summary>${esc(new Date(c.created_at).toLocaleString('sk-SK'))} · ${esc(c.job_label)} · ${esc(actor.display_name)} · ${c.passed?'VYHOVUJE':'NEVYHOVUJE'}</summary><p>${esc(qs.revision)}</p>${qs.items.map(q=>`<p>${esc(q.id)}. ${esc(q.text)} <b>${answers[q.id]?'ÁNO':'NIE'}</b></p>`).join('')}${!c.passed?`<p>E-mail: ${c.notice_sent_at?'odoslaný':esc(c.notice_error||'čaká na odoslanie')}</p>`:''}</details>`}).join('')||'Zatiaľ nebol vyplnený žiadny formulár.'}catch(err){dialog.querySelector('.oktorun-list').textContent=err.message}
  });
})();
