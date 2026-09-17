(() => {
  let pending = null;
  function apply(value) {
    const field = pending;
    pending = null;
    if (!field?.isConnected || typeof value !== 'string' || !value.length) return;
    field.value = value;
    field.dispatchEvent(new Event('input', {bubbles: true}));
    field.dispatchEvent(new Event('change', {bubbles: true}));
    field.focus();
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
    dialog.innerHTML = '<h3>Skenovať dodací list</h3><p>Namier fotoaparát na jeden čiarový alebo QR kód.</p><video autoplay muted playsinline></video><p class="barcode-status" role="status">Spúšťam fotoaparát…</p><div class="barcode-actions"><button type="button" class="btn primary barcode-use" hidden>Použiť číslo</button><button type="button" class="btn barcode-retry" hidden>Skenovať znova</button><button type="button" class="btn barcode-cancel">Zrušiť</button></div>';
    document.body.append(dialog);
    const video = dialog.querySelector('video');
    const status = dialog.querySelector('.barcode-status');
    const use = dialog.querySelector('.barcode-use');
    const retry = dialog.querySelector('.barcode-retry');
    let stream, timer, value, closed = false;
    const stop = () => { clearTimeout(timer); stream?.getTracks().forEach(t => t.stop()); };
    const close = () => { closed = true; stop(); pending = null; dialog.remove(); document.removeEventListener('visibilitychange', visibility); };
    const visibility = () => { if (document.hidden) dialog.close(); };
    document.addEventListener('visibilitychange', visibility);
    dialog.addEventListener('close', close, {once:true});
    dialog.querySelector('.barcode-cancel').onclick = () => dialog.close();
    use.onclick = () => { apply(value); dialog.close(); };
    retry.onclick = () => { value = null; use.hidden = retry.hidden = true; start(); };
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
            if (codes.length === 1) {
              value = codes[0]; stop(); video.hidden = true;
              status.textContent = 'Načítané číslo: ' + value;
              use.hidden = retry.hidden = false;
              return;
            }
            status.textContent = codes.length > 1 ? 'V zábere je viac kódov. Namier na jeden.' : 'Hľadám čiarový kód…';
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
