// Keep horizontal navigation reachable above long record tables.
(() => {
  const view = document.getElementById('view');
  if (!view) return;
  let current = null;
  function attach() {
    const body = view.querySelector('#recordsBody, #myRecordsBody');
    const wrap = body?.closest('.table-wrap');
    if (current?.wrap === wrap) return;
    if (current) { current.observer.disconnect(); current.bar.remove(); current = null; }
    if (!wrap) return;
    wrap.classList.add('records-scroll-area');
    wrap.tabIndex = 0;
    wrap.setAttribute('aria-label', 'Tabuľka záznamov – posúvaj šípkami alebo posuvnou lištou');
    const bar = document.createElement('div');
    bar.className = 'records-scroll-controls';
    bar.innerHTML = '<span>Posun tabuľky</span><button type="button" aria-label="Posunúť tabuľku doľava">◀</button><input type="range" min="0" max="0" value="0" step="1" aria-label="Vodorovný posun tabuľky"><button type="button" aria-label="Posunúť tabuľku doprava">▶</button>';
    wrap.before(bar);
    const slider = bar.querySelector('input');
    const buttons = bar.querySelectorAll('button');
    function update() {
      const max = Math.max(0, wrap.scrollWidth - wrap.clientWidth);
      slider.max = String(max);
      slider.value = String(wrap.scrollLeft);
      slider.disabled = max === 0;
      buttons[0].disabled = wrap.scrollLeft <= 0;
      buttons[1].disabled = wrap.scrollLeft >= max - 1;
    }
    slider.oninput = () => { wrap.scrollLeft = Number(slider.value); update(); };
    buttons[0].onclick = () => { wrap.scrollLeft -= Math.max(200, wrap.clientWidth * .7); };
    buttons[1].onclick = () => { wrap.scrollLeft += Math.max(200, wrap.clientWidth * .7); };
    wrap.addEventListener('scroll', update, {passive:true});
    const observer = new ResizeObserver(update);
    observer.observe(wrap);
    observer.observe(wrap.querySelector('table'));
    current = {wrap, bar, observer};
    update();
  }
  new MutationObserver(attach).observe(view, {childList:true, subtree:true});
  attach();
})();
