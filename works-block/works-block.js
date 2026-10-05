/* {AI}-шница — запуск блока: линза + появление текста + наложение на первый экран. */
(function () {
  var canvas = document.getElementById('ws-lens');
  if (canvas && window.initLens) {
    var opts = Object.assign({}, window.AISHNITSA_LENS || {}, {
      onPick: function (i) {
        var ids = window.AISHNITSA_WORK_IDS || [];
        var id = ids[i] || ('w' + String(i + 1).padStart(2, '0'));
        location.href = '/explore?work=' + encodeURIComponent(id);
      }
    });
    initLens(canvas, window.AISHNITSA_WORKS || [], opts);
  }

  var io = new IntersectionObserver(function (es) {
    es.forEach(function (e) {
      if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
    });
  }, { threshold: 0.2 });
  document.querySelectorAll('.reveal').forEach(function (el, i) {
    el.style.transitionDelay = (i * 0.08) + 's';
    io.observe(el);
  });

  var hero = document.querySelector('.ws-hero'), sec = document.querySelector('.ws');
  if (!hero || !sec) return;
  /* С блоком #models герой просто продолжается фоном — без сжатия/затемнения */
  if (document.getElementById('models')) return;
  var dim = hero.querySelector('.ws-hero-dim');
  if (!dim) { dim = document.createElement('div'); dim.className = 'ws-hero-dim'; hero.appendChild(dim); }
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches, tick = false;
  function upd() {
    tick = false;
    var p = Math.max(0, Math.min(1, 1 - sec.getBoundingClientRect().top / innerHeight));
    if (!reduce) hero.style.transform = 'scale(' + (1 - p * 0.06).toFixed(4) + ') translateY(' + (-p * 40).toFixed(1) + 'px)';
    hero.style.borderRadius = (p * 32).toFixed(1) + 'px';
    dim.style.opacity = (p * 0.55).toFixed(3);
  }
  addEventListener('scroll', function () { if (!tick) { tick = true; requestAnimationFrame(upd); } }, { passive: true });
  addEventListener('resize', upd); upd();
})();
