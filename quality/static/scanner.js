(() => {
  let pending = null;
  function parseLabel(raw) {
    const fields = {}, conflicts = new Set();
    for (const code of (Array.isArray(raw) ? raw : [raw])) {
      if (typeof code !== 'string') continue;
      for (const line of code.split(/[\r\n\t\x1d\x1e;]+/)) {
        const match = /^([PSQ])(.+)$/.exec(line.trim());
        if (!match) continue;
        const [, prefix, value] = match;
        if (fields[prefix] !== undefined && fields[prefix] !== value) conflicts.add(prefix);
        fields[prefix] = value;
      }
    }
    for (const key of conflicts) delete fields[key];
    return {fields, conflicts:[...conflicts]};
  }
  window.miellParseLabel = parseLabel;
  function apply(value) {
    const field = pending;
    pending = null;
    if (!field?.isConnected || value == null) return;
    const {fields, conflicts} = parseLabel(value);
    const errors = conflicts.map(k => `Etiketa obsahuje rôzne hodnoty s prefixom ${k}. Naskenuj iba jednu etiketu.`);
    const set = (el, text) => {
      el.value = text;
      el.dispatchEvent(new Event('input', {bubbles:true}));
      el.dispatchEvent(new Event('change', {bubbles:true}));
    };
    if (fields.P !== undefined) {
      const part = document.getElementById('rPart');
      const matches = [...(part?.options || [])].filter(o => o.dataset.itemNumber === fields.P);
      if (part && !part.disabled && matches.length === 1) set(part, matches[0].value);
      else errors.push(`Diel ${fields.P} nie je jednoznačne dostupný vo vybranej zákazke. Vyber zákazku a správny diel ručne.`);
    }
    if (fields.S !== undefined) set(field, fields.S);
    if (fields.Q !== undefined) {
      if (/^\d+$/.test(fields.Q) && Number.isSafeInteger(Number(fields.Q))) {
        set(document.getElementById('rChecked'), String(Number(fields.Q)));
      } else errors.push('Hodnota Q musí byť celé nezáporné číslo. Checked zostalo nezmenené.');
    }
    if (!Object.keys(fields).length && !conflicts.length) errors.push('Nenašiel sa prefix P, S ani Q. Hodnoty zostali nezmenené.');
    if (errors.length) alert(errors.join('\n'));
  }
  window.miellBarcodeResult = apply;

  async function scan(field) {
    if (pending) return;
    pending = field;
    if (window.MiellScanner?.postMessage) {
      try { window.MiellScanner.postMessage(field.id); }
      catch { pending = null; alert('Skener sa nepodarilo otvoriť. Číslo môžeš zadať ručne.'); }
      return;
    }
    if (!window.BarcodeDetector || !navigator.mediaDevices?.getUserMedia) {
      pending = null;
      alert('Tento prehliadač nepodporuje skenovanie. Použi novú Android aplikáciu MIELL alebo číslo zadaj ručne.');
      return;
    }
    const dialog = document.createElement('dialog');
    dialog.className = 'barcode-dialog';
    dialog.innerHTML = '<h3>Skenovať etiketu</h3><p>Postupne nasnímaj kódy jednej etikety: P – diel, S – dodací list, Q – Checked.</p><video autoplay muted playsinline></video><p class="barcode-status" role="status">Spúšťam fotoaparát…</p><div class="barcode-actions"><button type="button" class="btn primary barcode-use" hidden>Použiť hodnoty</button><button type="button" class="btn barcode-retry" hidden>Skenovať znova</button><button type="button" class="btn barcode-cancel">Zrušiť</button></div>';
    document.body.append(dialog);
    const video = dialog.querySelector('video');
    const status = dialog.querySelector('.barcode-status');
    const use = dialog.querySelector('.barcode-use');
    const retry = dialog.querySelector('.barcode-retry');
    let stream, timer, closed = false;
    let value = new Set();
    const stop = () => { clearTimeout(timer); stream?.getTracks().forEach(t => t.stop()); };
    const close = () => { closed = true; stop(); pending = null; dialog.remove(); document.removeEventListener('visibilitychange', visibility); };
    const visibility = () => { if (document.hidden) dialog.close(); };
    document.addEventListener('visibilitychange', visibility);
    dialog.addEventListener('close', close, {once:true});
    dialog.querySelector('.barcode-cancel').onclick = () => dialog.close();
    use.onclick = () => { apply([...value]); dialog.close(); };
    retry.onclick = () => { stop(); value = new Set(); use.hidden = retry.hidden = true; start(); };
    dialog.showModal();
    async function start() {
      retry.hidden = true;
      try {
        status.textContent = 'Povoľ fotoaparát a namier ho na kód.';
        stream = await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}}, audio:false});
        if (closed) { stop(); return; }
        video.hidden = false;
        video.srcObject = stream;
        await video.play();
        const detector = new BarcodeDetector();
        async function detect() {
          if (closed) return;
          try {
            const codes = [...new Set((await detector.detect(video)).map(c => c.rawValue).filter(Boolean))];
            if (closed) return;
            codes.forEach(code => {
              if (Object.keys(parseLabel(code).fields).length) value.add(code);
            });
            const parsed = parseLabel([...value]);
            status.textContent = Object.entries(parsed.fields).map(([k,v])=>`${k}: ${v}`).join(' | ') || 'Hľadám kódy P, S, Q…';
            if (parsed.conflicts.length) status.textContent += ' — Rôzne hodnoty rovnakého prefixu. Skenuj znova jednu etiketu.';
            use.hidden = value.size === 0 || parsed.conflicts.length > 0;
            retry.hidden = value.size === 0;
            timer = setTimeout(detect, 180);
          } catch { fail(); }
        }
        detect();
      } catch { fail(); }
    }
    function fail() {
      stop();
      if (closed) return;
      status.textContent = 'Fotoaparát alebo skener nie je dostupný. Skontroluj povolenie kamery. Číslo môžeš zadať ručne.';
      retry.hidden = false;
    }
    start();
  }
  document.addEventListener('click', e => {
    const button = e.target.closest('[data-scan-target]');
    if (!button) return;
    const field = document.getElementById(button.dataset.scanTarget);
    if (field && field.id === 'rDelivery') { e.preventDefault(); scan(field); }
  });
})();
