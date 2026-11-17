(function () {
  'use strict';
  // motyw jasny/ciemny
  var root = document.documentElement;
  try {
    var saved = localStorage.getItem('danzinger-theme');
    if (saved === 'dark') root.setAttribute('data-theme', 'dark');
  } catch (e) {}
  var toggle = document.getElementById('theme-toggle');
  if (toggle) {
    toggle.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      if (next === 'dark') root.setAttribute('data-theme', 'dark'); else root.removeAttribute('data-theme');
      try { localStorage.setItem('danzinger-theme', next); } catch (e) {}
    });
  }

  // podgląd skanu w modalu
  var modal = document.getElementById('scan-modal');
  var img = document.getElementById('scan-modal-img');
  var titleEl = document.getElementById('scan-modal-title');
  var link = document.getElementById('scan-modal-link');
  var caption = document.getElementById('scan-modal-caption');
  var pages = [], current = 0, baseCaption = '';

  function showPage() {
    var p = pages[current];
    img.src = '/skan/' + p;
    img.alt = 'Skan strony ' + p;
    link.href = '/skan/' + p;
    titleEl.textContent = baseCaption || ('Skan strony ' + p);
    caption.textContent = pages.length > 1
      ? ('Skan ' + p + ' · strona ' + (current + 1) + ' z ' + pages.length)
      : ('Skan ' + p);
  }
  function openScan(pageList, captionText) {
    pages = pageList.map(function (p) { return parseInt(p, 10); }).filter(function (n) { return n > 0; });
    if (!pages.length) return;
    current = 0;
    baseCaption = captionText || '';
    showPage();
    if (typeof modal.showModal === 'function') { modal.showModal(); } else { modal.setAttribute('open', ''); }
  }
  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest('.scan-open');
    if (!btn) return;
    ev.preventDefault();
    openScan((btn.dataset.pages || '').split(','), btn.dataset.title || '');
  });
  var closeBtn = modal && modal.querySelector('.scan-modal-close');
  if (closeBtn) closeBtn.addEventListener('click', function () { modal.close(); });
  if (modal) modal.addEventListener('click', function (ev) { if (ev.target === modal) modal.close(); });
  if (modal) modal.addEventListener('keydown', function (ev) {
    if (ev.key === 'ArrowLeft' && current > 0) { current -= 1; showPage(); }
    else if (ev.key === 'ArrowRight' && current < pages.length - 1) { current += 1; showPage(); }
  });
})();
