/**
 * 原版细胞场背景（移植自智析病理系统）
 * 紫/粉染色细胞团缓慢漂移、融合
 */
(function () {
  'use strict';

  var layer, field = null;

  function injectStyle(css) {
    var s = document.createElement('style');
    s.textContent = css;
    document.head.appendChild(s);
  }

  injectStyle([
    '#patho-bg { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }',
    '#patho-bg canvas { display: block; width: 100%; height: 100%; mix-blend-mode: screen; opacity: .85; }'
  ].join('\n'));

  function makeCanvas() {
    var c = document.createElement('canvas');
    var ctx = c.getContext('2d');
    function resize() {
      var dpr = window.devicePixelRatio || 1;
      c.width = Math.floor(window.innerWidth * dpr);
      c.height = Math.floor(window.innerHeight * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();
    window.addEventListener('resize', resize);
    return { canvas: c, ctx: ctx };
  }

  function cellField() {
    var mc = makeCanvas();
    var ctx = mc.ctx, W = 0, H = 0;
    var cells = [], N = 13;
    for (var i = 0; i < N; i++) {
      cells.push({
        x: Math.random(), y: Math.random(),
        r: 0.10 + Math.random() * 0.17,
        vx: (Math.random() - 0.5) * 0.0006,
        vy: (Math.random() - 0.5) * 0.0006,
        hue: i % 2 === 0 ? 268 : 322,
        sat: 72 + Math.random() * 20,
        lit: 52 + Math.random() * 12
      });
    }
    var running = false, raf = 0;

    function step() {
      W = window.innerWidth; H = window.innerHeight;
      ctx.clearRect(0, 0, W, H);
      for (var i = 0; i < cells.length; i++) {
        var c = cells[i];
        c.x += c.vx; c.y += c.vy;
        if (c.x < -0.2 || c.x > 1.2) c.vx *= -1;
        if (c.y < -0.2 || c.y > 1.2) c.vy *= -1;
        var px = c.x * W, py = c.y * H, pr = c.r * Math.min(W, H);
        var g = ctx.createRadialGradient(px, py, 0, px, py, pr);
        g.addColorStop(0, 'hsla(' + c.hue + ',' + c.sat + '%,' + c.lit + '%,0.50)');
        g.addColorStop(0.62, 'hsla(' + c.hue + ',' + c.sat + '%,' + c.lit + '%,0.38)');
        g.addColorStop(0.85, 'hsla(' + c.hue + ',' + c.sat + '%,' + (c.lit + 6) + '%,0.16)');
        g.addColorStop(1, 'hsla(' + c.hue + ',' + c.sat + '%,' + (c.lit + 10) + '%,0)');
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(px, py, pr, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    return {
      root: mc.canvas,
      start: function () { running = true; (function loop() { if (!running) return; step(); raf = requestAnimationFrame(loop); })(); },
      stop: function () { running = false; cancelAnimationFrame(raf); }
    };
  }

  function init() {
    if (layer) return;
    layer = document.createElement('div');
    layer.id = 'patho-bg';
    field = cellField();
    layer.appendChild(field.root);
    document.body.appendChild(layer);
    field.start();
  }

  // 暂停/恢复（粘液导航动画期间临时停掉，避免双重全屏 canvas 抢帧）
  function setPaused(paused) {
    if (!field) return;
    if (paused) field.stop();
    else field.start();
  }

  window.PathoBG = { activate: init, setPaused: setPaused };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
