/*
 * {AI}-шница — лента работ под вогнутой линзой (WebGL).
 *
 *   initLens(canvasElement, works, options) → функция destroy()
 *
 * works — массив путей к файлам: картинки (.jpg .png .webp .avif) и видео (.mp4 .webm).
 *         Видео играют внутри ленты без звука, по кругу.
 * options (все необязательные):
 *   k0, k1      — форма линзы: k1 < 0 — вогнутая (по умолчанию 1.14 и −0.36), k1 > 0 — выпуклая
 *   speed       — скорость полёта (0.018), hoverSpeed — при наведении (0.005)
 *   axis        — направление: 'x' горизонтально (по умолчанию), 'y' вертикально
 *   cols, rows  — сетка (4 × 3), gap — зазор (30), radius — скругление карточек (34)
 *   tileRatio   — высота карточки к ширине (0.74)
 *   bg          — цвет фона [r, g, b] (по умолчанию [18, 17, 19])
 *   onPick(i)   — клик по карточке: i — номер работы в массиве works (например, открыть её в витрине)
 *
 * Важно: видео и картинки должны отдаваться с того же сайта (или с CORS-заголовком),
 * иначе браузер не даст WebGL их читать. Открывать страницу нужно через сервер,
 * не двойным кликом: python3 -m http.server 8000.
 */
function initLens(canvas, works, opts) {
  opts = opts || {};
  var BG = opts.bg || [18, 17, 19];
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var COLS = opts.cols || 4, ROWS = opts.rows || 3, W = 2048, GAP = opts.gap || 30, RAD = opts.radius || 34;
  var colW = (W - GAP * COLS) / COLS, tileH = Math.round(colW * (opts.tileRatio || 0.74)), rowH = tileH + GAP, H = rowH * ROWS;
  var K0 = opts.k0 != null ? opts.k0 : 1.14, K1 = opts.k1 != null ? opts.k1 : -0.36;
  var SPEED = opts.speed != null ? opts.speed : 0.018, HOVER = opts.hoverSpeed != null ? opts.hoverSpeed : 0.005;
  var AXIS_X = String(opts.axis == null ? 'x' : opts.axis).toLowerCase() !== 'y';
  var state = { off: 0, vel: 0, last: 0, raf: 0, alive: true, lastY: window.scrollY, hover: false, visible: true };
  var media = [], idx = [], hasVideo = false, lastP = 1, lastX0 = 1, atlas, actx, gl, prog, uni = {}, tex, ctx2d, vio;

  function isVideo(src) { return /^data:video\//i.test(src) || /\.(mp4|webm|mov|m4v)(\?|#|$)/i.test(src); }
  function load(src) {
    return new Promise(function (res) {
      if (isVideo(src)) {
        var v = document.createElement('video');
        v.muted = true; v.loop = true; v.playsInline = true; v.autoplay = true; v.preload = 'auto';
        if (!/^data:/.test(src)) v.crossOrigin = 'anonymous'; v.setAttribute('muted', ''); v.setAttribute('playsinline', '');
        v.onloadeddata = function () { v.play().catch(function () {}); res(v); };
        v.onerror = function () { res(null); };
        v.src = src; v.load();
      } else {
        var i = new Image(); if (!/^data:/.test(src)) i.crossOrigin = 'anonymous';
        i.onload = function () { res(i); }; i.onerror = function () { res(null); }; i.src = src;
      }
    });
  }
  function dims(m) { return m.videoWidth ? [m.videoWidth, m.videoHeight] : [m.naturalWidth || m.width, m.naturalHeight || m.height]; }
  function rr(c, x, y, w, h, r) { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); }

  // порядок: все работы по кругу, со сдвигом в каждом ряду, чтобы соседи не повторялись
  function slot(r, k) { return (r * COLS + k + r * 2) % media.length; }
  function pick(r, k) { return media[slot(r, k)]; }

  function drawAtlas() {
    var c = actx;
    c.fillStyle = 'rgb(' + BG.join(',') + ')'; c.fillRect(0, 0, W, H);
    for (var r = 0; r < ROWS; r++) for (var k = 0; k < COLS; k++) {
      var m = pick(r, k), x = GAP / 2 + k * (colW + GAP), y = GAP / 2 + r * rowH;
      c.save(); rr(c, x, y, colW, tileH, RAD); c.clip();
      c.fillStyle = '#232225'; c.fillRect(x, y, colW, tileH);
      if (m) {
        var d = dims(m);
        if (d[0] && d[1]) {
          var s = Math.max(colW / d[0], tileH / d[1]), iw = d[0] * s, ih = d[1] * s;
          c.drawImage(m, x + (colW - iw) / 2, y + (tileH - ih) / 2, iw, ih);
        }
      }
      c.restore();
    }
  }

  var VS = 'attribute vec2 a;varying vec2 v;void main(){v=a*0.5+0.5;gl_Position=vec4(a,0.0,1.0);}';
  /* axis=1 — горизонтальный скролл (off по X), axis=0 — вертикальный (off по Y) */
  var FS = [
    'precision highp float;varying vec2 v;uniform sampler2D t;uniform vec2 res;uniform float off,X0,P,k0,k1,axis;uniform vec3 bg;',
    'vec3 samp(vec2 p){',
    'float tx,ty;',
    /* По X: скролл; по Y: cover — атлас заполняет высоту экрана (без пустых полей на мобиле) */
    'if(axis>0.5){tx=fract((p.x-off)/(2.0*X0));float yh=max(P,1.0);ty=p.y/yh+0.5;if(ty<0.0||ty>1.0)return bg;}',
    'else{tx=p.x/(2.0*X0)+0.5;if(tx<0.0||tx>1.0)return bg;ty=fract((p.y-off)/P);}',
    'return texture2D(t,vec2(tx,ty)).rgb;}',
    'void main(){float asp=res.x/res.y;vec2 p=(vec2(v.x,1.0-v.y)-0.5)*vec2(asp,1.0);float r2=dot(p,p);',
    'vec2 q=p*(k0+k1*r2);float ca=0.006*r2;',
    'vec3 c=vec3(samp(q*(1.0+ca)).r,samp(q).g,samp(q*(1.0-ca)).b);gl_FragColor=vec4(c,1.0);}'
  ].join('');

  function sh(type, src) { var s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; }
  function upload() { gl.bindTexture(gl.TEXTURE_2D, tex); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, atlas); }
  function setupGL() {
    gl = canvas.getContext('webgl', { antialias: false, premultipliedAlpha: false });
    if (!gl) return false;
    prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return false;
    gl.useProgram(prog);
    var b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    var loc = gl.getAttribLocation(prog, 'a'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    try { upload(); } catch (e) { console.warn('[lens] файлы недоступны для WebGL (откройте через сервер / проверьте CORS) — показываю без линзы'); return false; }
    ['res', 'off', 'X0', 'P', 'k0', 'k1', 'bg', 'axis'].forEach(function (n) { uni[n] = gl.getUniformLocation(prog, n); });
    gl.uniform3f(uni.bg, BG[0] / 255, BG[1] / 255, BG[2] / 255);
    gl.uniform1f(uni.k0, K0); gl.uniform1f(uni.k1, K1);
    gl.uniform1f(uni.axis, AXIS_X ? 1 : 0);
    return true;
  }

  function size() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    return [w, h];
  }

  var vidTick = 0;
  function frame(ts) {
    if (!state.alive) return;
    if (!state.visible) { state.last = 0; state.raf = 0; return; }
    var dt = state.last ? Math.min(0.05, (ts - state.last) / 1000) : 0; state.last = ts;
    state.off += dt * (reduce ? 0 : (state.hover ? HOVER : SPEED)) + state.vel; state.vel *= 0.9;
    var wh = size(), asp = wh[0] / wh[1], X0 = asp * 0.5 * 0.94, P = (H / W) * 2 * X0; lastP = P; lastX0 = X0;
    var period = AXIS_X ? (2 * X0) : P;
    if (hasVideo && (vidTick++ & 1) === 0) { drawAtlas(); if (gl && prog) upload(); }   // видео — ~30 кадров/с
    if (gl && prog) {
      gl.viewport(0, 0, wh[0], wh[1]);
      gl.uniform2f(uni.res, wh[0], wh[1]); gl.uniform1f(uni.off, state.off % period);
      gl.uniform1f(uni.X0, X0); gl.uniform1f(uni.P, P);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    } else if (ctx2d) {
      ctx2d.fillStyle = 'rgb(' + BG.join(',') + ')'; ctx2d.fillRect(0, 0, wh[0], wh[1]);
      if (AXIS_X) {
        var scaleX = wh[1] / H, pw = W * scaleX, x = ((state.off / period) * pw) % pw;
        var drawH = wh[1], drawW = pw, dy = 0;
        if (drawW < wh[0]) { /* cover width */ scaleX = wh[0] / W; pw = wh[0]; drawH = H * scaleX; dy = (wh[1] - drawH) / 2; x = ((state.off / period) * pw) % pw; }
        for (var xx = x - pw; xx < wh[0]; xx += pw) ctx2d.drawImage(atlas, xx, dy, pw, drawH > 0 ? Math.min(drawH, wh[1]) : wh[1]);
      } else {
        var scale = wh[0] / W, ph = H * scale, y = ((state.off / P) * ph) % ph;
        for (var yy = y - ph; yy < wh[1]; yy += ph) ctx2d.drawImage(atlas, 0, yy, wh[0], ph);
      }
    }
    if (!reduce || hasVideo || Math.abs(state.vel) > 0.0001) state.raf = requestAnimationFrame(frame);
  }
  function start() { if (!state.raf && atlas) state.raf = requestAnimationFrame(frame); }

  function onScroll() { var y = window.scrollY, d = y - state.lastY; state.lastY = y; if (!reduce) { state.vel += Math.max(-0.02, Math.min(0.02, d * 0.00035)); start(); } }
  function onEnter() { state.hover = true; } function onLeave() { state.hover = false; }

  // клик по карточке → opts.onPick(номер работы в массиве works)
  function hit(ev) {
    var rc = canvas.getBoundingClientRect(), asp = rc.width / rc.height;
    var px = ((ev.clientX - rc.left) / rc.width - 0.5) * asp, py = (ev.clientY - rc.top) / rc.height - 0.5;
    var r2 = px * px + py * py, f = ctx2d ? 1 : K0 + K1 * r2, qx = px * f, qy = py * f;
    var tx, ty, period = AXIS_X ? (2 * lastX0) : lastP;
    if (AXIS_X) {
      tx = ((qx - state.off % period) / period) % 1; if (tx < 0) tx += 1;
      var yh = Math.max(lastP, 1);
      ty = qy / yh + 0.5; if (ty < 0 || ty > 1) return -1;
    } else {
      tx = qx / (2 * lastX0) + 0.5; if (tx < 0 || tx > 1) return -1;
      ty = ((qy - state.off % lastP) / lastP) % 1; if (ty < 0) ty += 1;
    }
    var X = tx * W, Y = ty * H;
    var k = Math.floor((X - GAP / 2) / (colW + GAP)), r = Math.floor((Y - GAP / 2) / rowH);
    if (k < 0 || k >= COLS || r < 0 || r >= ROWS) return -1;
    var lx = X - GAP / 2 - k * (colW + GAP), ly = Y - GAP / 2 - r * rowH;
    if (lx > colW || ly > tileH) return -1;
    return idx[slot(r, k)];
  }
  function onClick(ev) { if (!opts.onPick || !media.length) return; var i = hit(ev); if (i >= 0) opts.onPick(i); }
  function onMove(ev) { if (opts.onPick && media.length) canvas.style.cursor = hit(ev) >= 0 ? 'pointer' : 'default'; }
  canvas.addEventListener('click', onClick); canvas.addEventListener('pointermove', onMove);
  window.addEventListener('scroll', onScroll, { passive: true });
  canvas.addEventListener('pointerenter', onEnter); canvas.addEventListener('pointerleave', onLeave);
  if ('IntersectionObserver' in window) {
    vio = new IntersectionObserver(function (es) {
      state.visible = es[0].isIntersecting;
      media.forEach(function (m) { if (m && m.tagName === 'VIDEO') { if (state.visible) m.play().catch(function () {}); else m.pause(); } });
      if (state.visible) start();
    }, { rootMargin: '100px' });
    vio.observe(canvas);
  }

  Promise.all((works || []).map(load)).then(function (list) {
    if (!state.alive) return;
    idx = []; media = [];
    list.forEach(function (m, i) { if (m) { media.push(m); idx.push(i); } });
    if (!media.length) return;
    hasVideo = media.some(function (m) { return m.tagName === 'VIDEO'; });
    atlas = document.createElement('canvas'); atlas.width = W; atlas.height = H; actx = atlas.getContext('2d');
    drawAtlas();
    if (!setupGL()) {
      gl = null; prog = null;
      var fresh = canvas.cloneNode(false); canvas.replaceWith(fresh);   // у канваса уже есть WebGL-контекст — берём чистый
      canvas.removeEventListener('pointerenter', onEnter); canvas.removeEventListener('pointerleave', onLeave);
      if (vio) { vio.unobserve(canvas); vio.observe(fresh); }
      canvas = fresh; canvas.addEventListener('pointerenter', onEnter); canvas.addEventListener('pointerleave', onLeave);
      canvas.addEventListener('click', onClick); canvas.addEventListener('pointermove', onMove);
      ctx2d = canvas.getContext('2d');
    }
    start();
  });

  return function destroy() {
    state.alive = false; cancelAnimationFrame(state.raf);
    window.removeEventListener('scroll', onScroll);
    canvas.removeEventListener('pointerenter', onEnter); canvas.removeEventListener('pointerleave', onLeave);
    canvas.removeEventListener('click', onClick); canvas.removeEventListener('pointermove', onMove);
    if (vio) vio.disconnect();
    media.forEach(function (m) { if (m && m.tagName === 'VIDEO') { m.pause(); m.removeAttribute('src'); m.load(); } });
  };
}
