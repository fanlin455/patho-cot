/**
 * Patho-COT 动态背景 · 细胞流体（G 方案，全站统一）
 * 纯 Canvas 2D，零外部依赖可离线。青蓝半透明细胞团缓慢漂移、融合，
 * 呼应病理细胞主题，替代旧版紫色光斑。
 *
 * 约束：低饱和 teal/cyan、慢速、透明度低不抢内容；DPR≤1.5；
 *       标签隐藏自动暂停；prefers-reduced-motion 时只画静态一帧。
 *
 * 用法：window.PathoAnimBG.start() / window.PathoAnimBG.start({el}) / .stop()
 */
(function () {
  'use strict';

  var COLORS = [
    [45, 212, 191],   // teal-400
    [56, 189, 248],   // sky-400
    [59, 130, 246],   // blue-500
    [94, 234, 212]    // teal-300
  ];

  var st = { running: false, raf: 0, canvas: null, ctx: null,
             W: 0, H: 0, cells: [], t0: 0, host: null, frameFn: null,
             starsCanvas: null, starsCtx: null, stars: [], starsRaf: 0, starsRunning: false };

  function rgba(c, a) { return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; }

  function resize() {
    var dpr = Math.min(Number(window.devicePixelRatio) || 1, 1.5);
    var rect = st.host.getBoundingClientRect();
    st.W = st.host === document.body ? window.innerWidth : rect.width;
    st.H = st.host === document.body ? window.innerHeight : rect.height;
    if (!isFinite(st.W) || st.W < 2) st.W = window.innerWidth;
    if (!isFinite(st.H) || st.H < 2) st.H = window.innerHeight;
    st.canvas.width = Math.max(1, Math.floor(st.W * dpr));
    st.canvas.height = Math.max(1, Math.floor(st.H * dpr));
    try { st.ctx.setTransform(dpr, 0, 0, dpr, 0, 0); } catch (e) { st.ctx.setTransform(1, 0, 0, 1, 0, 0); }
    if (st.starsCanvas) {
      st.starsCanvas.width = Math.max(1, Math.floor(st.W * dpr));
      st.starsCanvas.height = Math.max(1, Math.floor(st.H * dpr));
      try { st.starsCtx.setTransform(dpr, 0, 0, dpr, 0, 0); } catch (e) { st.starsCtx.setTransform(1, 0, 0, 1, 0, 0); }
      buildStars();
    }
  }

  function buildCells() {
    var n = 12;
    st.cells = [];
    for (var i = 0; i < n; i++) {
      st.cells.push({
        x: Math.random(), y: Math.random(),
        vx: 0.000012 + (Math.random() - 0.5) * 0.00005,
        vy: (Math.random() - 0.5) * 0.00004,
        r: 0.10 + Math.random() * 0.14,
        c: COLORS[i % COLORS.length],
        ph: Math.random() * 6.2832
      });
    }
  }

  function render(t) {
    var W = st.W, H = st.H, ctx = st.ctx;
    ctx.clearRect(0, 0, W, H);
    ctx.globalCompositeOperation = 'screen';
    for (var i = 0; i < st.cells.length; i++) {
      var c = st.cells[i];
      c.x += c.vx * 16; c.y += c.vy * 16;
      if (c.x < -0.25) c.x = 1.2; if (c.x > 1.25) c.x = -0.2;
      if (c.y < -0.25) c.y = 1.2; if (c.y > 1.25) c.y = -0.2;
      var px = c.x * W, py = c.y * H;
      var pr = c.r * Math.min(W, H) * (1 + 0.08 * Math.sin(t * 0.3 + c.ph));
      var g = ctx.createRadialGradient(px, py, 0, px, py, pr);
      g.addColorStop(0, rgba(c.c, 0.13));
      g.addColorStop(0.6, rgba(c.c, 0.055));
      g.addColorStop(1, rgba(c.c, 0));
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(px, py, pr, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalCompositeOperation = 'source-over';
  }

  function frame(now) {
    if (!st.running) return;
    render((now - st.t0) / 1000);
    st.raf = requestAnimationFrame(frame);
  }

  function onVis() {
    if (document.hidden) { st.running = false; cancelAnimationFrame(st.raf); st.starsRunning = false; cancelAnimationFrame(st.starsRaf); }
    else {
      if (st.canvas) { st.running = true; st.t0 = performance.now(); st.raf = requestAnimationFrame(frame); }
      if (st.starsCanvas) { st.starsRunning = true; st.starsRaf = requestAnimationFrame(starsFrame); }
    }
  }

  // ---------- 星空粒子层 ----------
  function buildStars() {
    st.stars = [];
    var count = Math.min(220, Math.floor(st.W * st.H / 7000));
    for (var i = 0; i < count; i++) {
      st.stars.push({
        x: Math.random() * st.W,
        y: Math.random() * st.H,
        r: Math.random() * 1.4 + 0.3,
        a: Math.random() * 0.6 + 0.15,
        tw: Math.random() * 0.02 + 0.005,
        ph: Math.random() * 6.2832,
        vx: (Math.random() - 0.5) * 0.08,
        vy: (Math.random() - 0.5) * 0.05,
        hue: Math.random() < 0.7 ? [180, 220, 255] : [120, 220, 200]
      });
    }
  }

  function starsRender(t) {
    var ctx = st.starsCtx, W = st.W, H = st.H;
    ctx.clearRect(0, 0, W, H);
    for (var i = 0; i < st.stars.length; i++) {
      var s = st.stars[i];
      s.x += s.vx; s.y += s.vy;
      if (s.x < 0) s.x = W; if (s.x > W) s.x = 0;
      if (s.y < 0) s.y = H; if (s.y > H) s.y = 0;
      var alpha = s.a * (0.5 + 0.5 * Math.sin(t * s.tw * 60 + s.ph));
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + s.hue[0] + ',' + s.hue[1] + ',' + s.hue[2] + ',' + alpha + ')';
      ctx.fill();
    }
  }

  function starsFrame(now) {
    if (!st.starsRunning) return;
    starsRender((now - st.t0) / 1000);
    st.starsRaf = requestAnimationFrame(starsFrame);
  }

  function start(opts) {
    opts = opts || {};
    if (window.__cellFluidRunning) stop();
    window.__cellFluidRunning = true;
    st.host = opts.el || document.querySelector('.bg-container') || document.body;
    var canvas = document.createElement('canvas');
    canvas.id = 'cell-fluid-bg';
    canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:1;opacity:0.55;';
    st.host.appendChild(canvas);
    st.canvas = canvas;
    st.ctx = canvas.getContext('2d');

    // 星空粒子层（位于细胞流体之上，内容之下）
    var stars = document.createElement('canvas');
    stars.id = 'stars-bg';
    stars.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:2;';
    st.host.appendChild(stars);
    st.starsCanvas = stars;
    st.starsCtx = stars.getContext('2d');

    resize();
    buildCells();
    buildStars();
    window.addEventListener('resize', resize);
    document.addEventListener('visibilitychange', onVis);
    var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) {
      render(1.2); starsRender(1.2);
    } else {
      st.running = true;
      st.starsRunning = true;
      st.t0 = performance.now();
      st.raf = requestAnimationFrame(frame);
      st.starsRaf = requestAnimationFrame(starsFrame);
    }
  }

  function stop() {
    st.running = false;
    st.starsRunning = false;
    cancelAnimationFrame(st.raf);
    cancelAnimationFrame(st.starsRaf);
    window.removeEventListener('resize', resize);
    document.removeEventListener('visibilitychange', onVis);
    if (st.canvas && st.canvas.parentNode) st.canvas.parentNode.removeChild(st.canvas);
    if (st.starsCanvas && st.starsCanvas.parentNode) st.starsCanvas.parentNode.removeChild(st.starsCanvas);
    st.canvas = null; st.ctx = null; st.cells = [];
    st.starsCanvas = null; st.starsCtx = null; st.stars = [];
    window.__cellFluidRunning = false;
  }

  window.PathoAnimBG = { start: start, stop: stop };

  // 自动启动（页面含背景容器即生效）
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { start(); });
  else start();
})();
