/**
 * React Bits 风格效果库 v2（原生 JS 实现，高质量还原）
 * 紫红色调，优雅风格
 * 包含：Aurora极光背景、GridScan扫描、GooeyNav粘液导航（熔化级）、
 *       SpotlightCard聚光灯卡片、PageTransition页面过渡、CountUp数字动画
 */

// ============================================================
// 1. Aurora 极光背景（紫红色调）
// ============================================================
(function () {
  'use strict';

  var Aurora = {
    canvas: null, ctx: null, width: 0, height: 0,
    time: 0, running: false, raf: 0, blobs: [],
    config: {
      colors: ['#0d9488', '#06b6d4', '#0891b2', '#06b6d4'],
      speed: 0.5,
      blend: 0.18,
      count: 6
    }
  };

  function hexToRgb(hex) {
    var r = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return r ? { r: parseInt(r[1], 16), g: parseInt(r[2], 16), b: parseInt(r[3], 16) } : { r: 0, g: 0, b: 0 };
  }

  function initAurora(canvas, config) {
    Aurora.canvas = canvas;
    Aurora.ctx = canvas.getContext('2d');
    if (config) Object.assign(Aurora.config, config);
    resize();
    createBlobs();
    window.addEventListener('resize', resize);
  }

  function resize() {
    var dpr = window.devicePixelRatio || 1;
    var parent = Aurora.canvas.parentElement;
    var rect = parent ? parent.getBoundingClientRect() : { width: window.innerWidth, height: window.innerHeight };
    Aurora.width = rect.width;
    Aurora.height = rect.height;
    Aurora.canvas.width = Aurora.width * dpr;
    Aurora.canvas.height = Aurora.height * dpr;
    Aurora.canvas.style.width = Aurora.width + 'px';
    Aurora.canvas.style.height = Aurora.height + 'px';
    Aurora.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function createBlobs() {
    Aurora.blobs = [];
    for (var i = 0; i < Aurora.config.count; i++) {
      Aurora.blobs.push({
        x: Math.random(), y: Math.random(),
        vx: (Math.random() - 0.5) * 0.0006,
        vy: (Math.random() - 0.5) * 0.0006,
        r: 0.28 + Math.random() * 0.35,
        color: Aurora.config.colors[i % Aurora.config.colors.length],
        phase: Math.random() * Math.PI * 2,
        wobbleSpeed: 0.25 + Math.random() * 0.4,
        wobbleAmount: 0.08 + Math.random() * 0.1
      });
    }
  }

  function renderAurora() {
    if (!Aurora.running) return;
    Aurora.time += 0.016 * Aurora.config.speed;
    var ctx = Aurora.ctx, w = Aurora.width, h = Aurora.height;
    ctx.clearRect(0, 0, w, h);
    ctx.globalCompositeOperation = 'lighter';

    for (var i = 0; i < Aurora.blobs.length; i++) {
      var b = Aurora.blobs[i];
      b.x += b.vx; b.y += b.vy;
      if (b.x < -0.2 || b.x > 1.2) b.vx *= -1;
      if (b.y < -0.2 || b.y > 1.2) b.vy *= -1;

      var wobbleX = Math.sin(Aurora.time * b.wobbleSpeed + b.phase) * b.wobbleAmount;
      var wobbleY = Math.cos(Aurora.time * b.wobbleSpeed * 0.7 + b.phase) * b.wobbleAmount * 0.7;
      var px = (b.x + wobbleX) * w;
      var py = (b.y + wobbleY) * h;
      var pr = b.r * Math.min(w, h) * (1 + Math.sin(Aurora.time * 0.4 + b.phase) * 0.12);

      var rgb = hexToRgb(b.color);
      var grad = ctx.createRadialGradient(px, py, 0, px, py, pr);
      grad.addColorStop(0, 'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',' + (0.5 * Aurora.config.blend + 0.18) + ')');
      grad.addColorStop(0.4, 'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',' + (0.3 * Aurora.config.blend + 0.08) + ')');
      grad.addColorStop(0.7, 'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',' + (0.12 * Aurora.config.blend) + ')');
      grad.addColorStop(1, 'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',0)');

      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(px, py, pr, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalCompositeOperation = 'source-over';
    Aurora.raf = requestAnimationFrame(renderAurora);
  }

  Aurora.start = function () { if (Aurora.running) return; Aurora.running = true; renderAurora(); };
  Aurora.stop = function () { Aurora.running = false; cancelAnimationFrame(Aurora.raf); };
  Aurora.init = initAurora;
  window.RBAurora = Aurora;

  document.addEventListener('DOMContentLoaded', function () {
    var canvas = document.getElementById('aurora-bg');
    if (canvas) { initAurora(canvas); Aurora.start(); }
  });
})();


// ============================================================
// 2. Grid Scan 扫描线（紫红色调）
// ============================================================
(function () {
  'use strict';
  var GridScan = {
    canvas: null, ctx: null, width: 0, height: 0,
    time: 0, scanPos: 0, running: false, raf: 0,
    config: {
      lineColor: 'rgba(45,212,191,0.06)',
      scanColor: 'rgba(6,182,212,0.35)',
      gridSize: 44,
      scanSpeed: 0.25,
      scanWidth: 70,
      jitter: 1.5,
      chromatic: true
    }
  };

  function init(canvas, config) {
    GridScan.canvas = canvas;
    GridScan.ctx = canvas.getContext('2d');
    if (config) Object.assign(GridScan.config, config);
    resize();
    window.addEventListener('resize', resize);
  }

  function resize() {
    var dpr = window.devicePixelRatio || 1;
    var parent = GridScan.canvas.parentElement;
    var rect = parent ? parent.getBoundingClientRect() : { width: window.innerWidth, height: window.innerHeight };
    GridScan.width = rect.width;
    GridScan.height = rect.height;
    GridScan.canvas.width = GridScan.width * dpr;
    GridScan.canvas.height = GridScan.height * dpr;
    GridScan.canvas.style.width = GridScan.width + 'px';
    GridScan.canvas.style.height = GridScan.height + 'px';
    GridScan.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function render() {
    if (!GridScan.running) return;
    GridScan.time += 0.016;
    var ctx = GridScan.ctx, w = GridScan.width, h = GridScan.height, cfg = GridScan.config;
    ctx.clearRect(0, 0, w, h);

    ctx.strokeStyle = cfg.lineColor;
    ctx.lineWidth = 1;
    var gs = cfg.gridSize;
    for (var x = 0; x <= w; x += gs) {
      var jx = Math.sin(GridScan.time * 1.8 + x * 0.01) * cfg.jitter;
      ctx.beginPath();
      ctx.moveTo(x + jx, 0);
      ctx.lineTo(x + jx, h);
      ctx.stroke();
    }
    for (var y = 0; y <= h; y += gs) {
      var jy = Math.cos(GridScan.time * 1.3 + y * 0.01) * cfg.jitter;
      ctx.beginPath();
      ctx.moveTo(0, y + jy);
      ctx.lineTo(w, y + jy);
      ctx.stroke();
    }

    GridScan.scanPos = (GridScan.scanPos + cfg.scanSpeed) % (h + cfg.scanWidth * 2) - cfg.scanWidth;
    var scanY = GridScan.scanPos;
    var grad = ctx.createLinearGradient(0, scanY - cfg.scanWidth, 0, scanY + cfg.scanWidth);
    grad.addColorStop(0, 'rgba(6,182,212,0)');
    grad.addColorStop(0.4, 'rgba(6,182,212,0.04)');
    grad.addColorStop(0.5, cfg.scanColor);
    grad.addColorStop(0.6, 'rgba(6,182,212,0.04)');
    grad.addColorStop(1, 'rgba(6,182,212,0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, scanY - cfg.scanWidth, w, cfg.scanWidth * 2);

    if (cfg.chromatic) {
      ctx.globalCompositeOperation = 'screen';
      ctx.fillStyle = 'rgba(45,212,191,0.05)';
      ctx.fillRect(0, scanY - cfg.scanWidth * 0.5 - 2, w, cfg.scanWidth * 0.8);
      ctx.fillStyle = 'rgba(56,189,248,0.05)';
      ctx.fillRect(0, scanY - cfg.scanWidth * 0.5 + 2, w, cfg.scanWidth * 0.8);
      ctx.globalCompositeOperation = 'source-over';
    }

    GridScan.raf = requestAnimationFrame(render);
  }

  GridScan.start = function () { if (GridScan.running) return; GridScan.running = true; render(); };
  GridScan.stop = function () { GridScan.running = false; cancelAnimationFrame(GridScan.raf); };
  GridScan.init = init;
  window.RBGridScan = GridScan;

  document.addEventListener('DOMContentLoaded', function () {
    var canvas = document.getElementById('gridscan-bg');
    if (canvas) { init(canvas); GridScan.start(); }
  });
})();


// ============================================================
// 3. GooeyNav 粘液导航（严格对齐 React Bits 原版参数）
//    Pill Color: #f4f4f5 | Particles: 15 | Spread: 56px
//    Animation: 600ms | TimeVariance: 300ms | Gooeyness: 0.5 | Wobble: 0.5
// ============================================================
(function () {
  'use strict';

  function GooeyNav(container, options) {
    this.container = typeof container === 'string' ? document.querySelector(container) : container;
    this.options = Object.assign({
      pillColor: '#10333d',
      particleCount: 22,
      animationTime: 600,
      timeVariance: 300,
      particleDistances: [130, 10],
      particleR: 100,
      colors: [1, 2, 3, 1, 2, 3, 1, 4]
    }, options || {});

    this.items = this.container.querySelectorAll('.nav-item');
    this.activeIndex = 0;
    this.animating = false;
    this.particles = [];
    // SVG 滤镜参数（会被 localStorage 覆盖）
    this._lastStdDev = (options && options.stdDev) || 6;
    this._lastAlphaAmp = (options && options.alphaAmp) || 14;
    this._lastAlphaOff = (options && options.alphaOff) || -7;
    this._init();
  }

  // 注入 goo SVG 滤镜（对齐 React Bits 原版参数）
  // 性能：使用 userSpaceOnUse 精确限定滤镜作用区域，避免对整个导航容器做高斯模糊
  GooeyNav.prototype._ensureGooFilter = function () {
    var existing = document.getElementById('rb-goo-filter');
    if (existing) { this._filterEl = existing; return; }
    var stdDev = 10;
    var alphaAmp = 19;
    var alphaOff = -9;
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', '0');
    svg.setAttribute('height', '0');
    svg.style.position = 'absolute';
    svg.innerHTML = '<defs><filter id="rb-goo-filter" filterUnits="userSpaceOnUse" x="-200" y="-200" width="900" height="900">' +
      '<feGaussianBlur in="SourceGraphic" stdDeviation="' + stdDev + '" result="blur"/>' +
      '<feColorMatrix in="blur" mode="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 ' + alphaAmp + ' ' + alphaOff + '" result="goo"/>' +
      '<feComposite in="SourceGraphic" in2="goo" operator="atop"/>' +
      '</filter></defs>';
    document.body.appendChild(svg);
    this._filterEl = svg.querySelector('#rb-goo-filter');
  };

  // 把滤镜重绘区域收紧到目标矩形（容器坐标系）+ 外扩 padding
  GooeyNav.prototype._setFilterRegion = function (x, y, w, h, pad) {
    if (!this._filterEl) return;
    pad = pad || 110;
    this._filterEl.setAttribute('x', String(Math.round(x - pad)));
    this._filterEl.setAttribute('y', String(Math.round(y - pad)));
    this._filterEl.setAttribute('width', String(Math.round(w + pad * 2)));
    this._filterEl.setAttribute('height', String(Math.round(h + pad * 2)));
  };

  // 动画开始/结束事件：通知页面暂停重型背景（Aurora/细胞场），保证粘液动画 60fps
  GooeyNav.prototype._emitAnim = function (on) {
    try { window.dispatchEvent(new CustomEvent('rb-goo-anim', { detail: { on: !!on } })); } catch (e) {}
  };

  // 清除本组激活态（另一组导航被点击时调用）：药丸淡出，避免双胶囊并存
  GooeyNav.prototype.clearActive = function () {
    if (this.activeIndex === -1) return;
    this.activeIndex = -1;
    this.animating = false;
    var self = this;
    this.items.forEach(function (it) { it.classList.remove('active'); });
    this.pill.style.transition = 'opacity .18s ease';
    this.pill.style.opacity = '0';
    setTimeout(function () { self.pill.style.transition = ''; }, 200);
    this.trailBlobs.forEach(function (tb) { tb.el.style.opacity = '0'; tb.size = 0; });
  };

  GooeyNav.prototype._init = function () {
    var self = this;

    // 导航项层级：在 goo 层之上
    this.items.forEach(function (item) {
      item.style.position = 'relative';
      item.style.zIndex = '3';
      item.style.whiteSpace = 'nowrap';
      var svg = item.querySelector('svg');
      if (svg) { svg.style.flexShrink = '0'; svg.style.minWidth = '18px'; }
      var badge = item.querySelector('.nav-badge');
      if (badge) badge.style.flexShrink = '0';
    });

    // 清理旧指示块
    var old = this.container.querySelectorAll('.nav-indicator, #navIndicator');
    old.forEach(function (el) { el.remove(); });

    // goo 容器（滤镜只作用于此层内的药丸和液滴）
    this.gooWrapper = document.createElement('div');
    this.gooWrapper.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:1;overflow:visible;filter:url(#rb-goo-filter);will-change:transform;';
    this.container.appendChild(this.gooWrapper);
    this._ensureGooFilter();

    // 药丸层
    this.blobLayer = document.createElement('div');
    this.blobLayer.style.cssText = 'position:absolute;inset:0;overflow:visible;';
    this.gooWrapper.appendChild(this.blobLayer);

    // 主药丸（白色 #f4f4f5）—— 纯 transform 动画，避免 filter 区域每帧重排
    this.pill = document.createElement('div');
    this.pill.style.cssText = [
      'position:absolute',
      'border-radius:12px',
      'background:' + this.options.pillColor,
      'box-shadow:0 3px 14px rgba(0,0,0,0.45), 0 0 0 1px rgba(45,212,191,0.35), 0 0 14px rgba(45,212,191,0.18) inset',
      'transform-origin:0 0',
      'will-change:transform'
    ].join(';');
    this.blobLayer.appendChild(this.pill);

    // 熔化拖尾块（跟随药丸，制造液体拉伸）—— 纯 transform 动画
    this.trailBlobs = [];
    for (var i = 0; i < 4; i++) {
      var tb = document.createElement('div');
      tb.style.cssText = 'position:absolute;border-radius:50%;background:' + this.options.pillColor + ';pointer-events:none;transform-origin:0 0;left:0;top:0;';
      this.blobLayer.appendChild(tb);
      this.trailBlobs.push({ el: tb, x: 0, y: 0, size: 0, base: 0 });
    }

    // 液滴层（点击时从药丸分裂出来）
    this.dropletLayer = document.createElement('div');
    this.dropletLayer.style.cssText = 'position:absolute;inset:0;overflow:visible;';
    this.gooWrapper.appendChild(this.dropletLayer);

    for (var i = 0; i < this.options.particleCount; i++) {
      var d = document.createElement('div');
      d.style.cssText = 'position:absolute;left:0;top:0;border-radius:50%;pointer-events:none;opacity:0;transform-origin:0 0;background:' + this.options.pillColor + ';will-change:transform,opacity;backface-visibility:hidden;';
      this.dropletLayer.appendChild(d);
      this.particles.push({
        el: d, x: 0, y: 0, targetX: 0, targetY: 0,
        midX: 0, midY: 0, size: 0, startTime: 0, duration: 0
      });
    }

    // 点击事件
    this.items.forEach(function (item, index) {
      item.addEventListener('click', function (e) {
        if (item.tagName === 'A') {
          e.preventDefault();
          var href = item.getAttribute('href');
          self.goTo(index, function () {
            if (href && href !== '#') {
              if (window.RBPageTransition) RBPageTransition.go(href);
              else window.location.href = href;
            }
          });
        } else {
          self.goTo(index);
        }
      });
    });

    // 初始化：本组无激活项时隐藏药丸（避免双组导航出现两个胶囊并存）
    var active = this.container.querySelector('.nav-item.active');
    if (active) {
      this.activeIndex = Array.prototype.indexOf.call(this.items, active);
      this._positionPill(this.activeIndex, true);
    } else {
      this.activeIndex = -1;
      this.pill.style.opacity = '0';
      this.trailBlobs.forEach(function (tb) { tb.el.style.opacity = '0'; });
    }
    this._animateTrail();

    // 窗口尺寸变化时重定位并唤醒拖尾
    window.addEventListener('resize', function () {
      if (self.activeIndex < 0) return;
      self._positionPill(self.activeIndex, true);
    });
  };

  // 定位药丸
  GooeyNav.prototype._positionPill = function (index, instant) {
    var item = this.items[index];
    if (!item) return;
    var cr = this.container.getBoundingClientRect();
    var ir = item.getBoundingClientRect();
    var x = ir.left - cr.left;
    var y = ir.top - cr.top;
    var w = ir.width;
    var h = ir.height;

    if (instant) {
      this.pill.style.transform = 'translate(' + x + 'px,' + y + 'px)';
      this.pill.style.width = w + 'px';
      this.pill.style.height = h + 'px';
      this.pill.style.opacity = '1';
      this.trailBlobs.forEach(function (tb) {
        tb.x = x + w / 2; tb.y = y + h / 2;
        tb.size = Math.min(w, h) * 0.7;
      });
      this._setFilterRegion(x, y, w, h);
      this._wakeTrail && this._wakeTrail();
    } else {
      this._tX = x; this._tY = y; this._tW = w; this._tH = h;
      this._animStart = performance.now();
      var m = this.pill.style.transform.match(/translate\(([^,]+),\s*([^)]+)/);
      this._fX = m ? parseFloat(m[1]) : x;
      this._fY = m ? parseFloat(m[2]) : y;
      this._fW = parseFloat(this.pill.style.width) || w;
      this._fH = parseFloat(this.pill.style.height) || h;
      this._animatePill();
    }
  };

  // 药丸位移动画（到达目标时轻微挤压回弹，模拟液体落地）
  // 性能：宽高在动画起始一次写好，过程中只改 transform（GPU 合成，不触发重排）
  GooeyNav.prototype._animatePill = function () {
    var self = this;
    var dur = this.options.animationTime;

    // 目标尺寸一次写好，动画用 scale 比例过渡
    this.pill.style.width = this._tW + 'px';
    this.pill.style.height = this._tH + 'px';

    function step(now) {
      var t = Math.min((now - self._animStart) / dur, 1);
      var ease = 1 - Math.pow(1 - t, 3);

      var x = self._fX + (self._tX - self._fX) * ease;
      var y = self._fY + (self._tY - self._fY) * ease;
      var w = self._fW + (self._tW - self._fW) * ease;
      var h = self._fH + (self._tH - self._fH) * ease;

      // 落地挤压回弹（更快安定，避免拖沓感）
      var squish = 1;
      if (t > 0.75) {
        var wt = (t - 0.75) / 0.25;
        squish = 1 + Math.sin(wt * Math.PI * 2) * 0.03 * (1 - wt);
      }

      var sx = (w / self._tW) / squish;
      var sy = (h / self._tH) * squish;
      self.pill.style.transform = 'translate(' + x + 'px,' + y + 'px) scale(' + sx + ',' + sy + ')';

      if (t < 1) requestAnimationFrame(step);
      else self.pill.style.transform = 'translate(' + self._tX + 'px,' + self._tY + 'px) scale(1,1)';
    }
    requestAnimationFrame(step);
  };

  // 拖尾熔化循环（收敛后自动休眠，切换/缩放时唤醒；纯 transform 写入）
  GooeyNav.prototype._animateTrail = function () {
    var self = this;
    var calm = 0;
    var lastTs = 0;
    self._trailAwake = true;

    function loop() {
      if (!self._trailAwake) return;   // 已休眠：完全停止 rAF
      var item = self.items[self.activeIndex];
      if (item) {
        var cr = self.container.getBoundingClientRect();
        var ir = item.getBoundingClientRect();
        var tx = ir.left - cr.left + ir.width / 2;
        var ty = ir.top - cr.top + ir.height / 2;
        var ts = Math.min(ir.width, ir.height) * 0.7;

        // 目标尺寸变化时重设基准尺寸（一次性 width/height 写入）
        if (ts !== lastTs) {
          lastTs = ts;
          self.trailBlobs.forEach(function (tb) {
            tb.el.style.width = ts + 'px';
            tb.el.style.height = ts + 'px';
          });
        }

        var maxDelta = 0;
        self.trailBlobs.forEach(function (tb, i) {
          var k = 0.18 - i * 0.03;
          tb.x += (tx - tb.x) * k;
          tb.y += (ty - tb.y) * k;
          tb.size += (ts - tb.size) * k;
          var d = Math.abs(tx - tb.x) + Math.abs(ty - tb.y) + Math.abs(ts - tb.size);
          if (d > maxDelta) maxDelta = d;
          var s = ts > 0 ? tb.size / ts : 1;
          tb.el.style.transform = 'translate(' + (tb.x - tb.size / 2) + 'px,' + (tb.y - tb.size / 2) + 'px) scale(' + s + ')';
          tb.el.style.opacity = (0.85 - i * 0.18).toFixed(2);
        });

        // 全部收敛后计数，连续 20 帧静止则休眠（此后零开销）
        if (maxDelta < 0.4) { if (++calm > 20) { self._trailAwake = false; return; } }
        else calm = 0;
      }
      requestAnimationFrame(loop);
    }
    loop();
  };

  // 唤醒拖尾循环
  GooeyNav.prototype._wakeTrail = function () {
    if (this._trailAwake) return;
    this._animateTrail();
  };

  GooeyNav.prototype.goTo = function (index, callback) {
    if (index === this.activeIndex || this.animating) return;
    this.animating = true;
    var self = this;
    var fromItem = this.activeIndex >= 0 ? this.items[this.activeIndex] : null;
    var toItem = this.items[index];
    var cr = this.container.getBoundingClientRect();
    var tr = toItem.getBoundingClientRect();

    // 无起点（本组之前无激活项）：药丸直接在目标处弹入，粒子原地爆发，不跨组飞行
    if (!fromItem) {
      this._positionPill(index, true);
      this.pill.style.opacity = '1';
      var pillEl = this.pill;
      var baseTf = pillEl.style.transform;
      pillEl.style.transition = 'transform .22s cubic-bezier(0.34,1.56,0.64,1)';
      pillEl.style.transform = baseTf + ' scale(0.6)';
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          pillEl.style.transform = baseTf;
        });
      });
      setTimeout(function () { pillEl.style.transition = ''; }, 260);
      var tcx = tr.left - cr.left + tr.width / 2, tcy = tr.top - cr.top + tr.height / 2;
      this._setFilterRegion(tr.left - cr.left, tr.top - cr.top, tr.width, tr.height);
      this._emitAnim(true);
      this._burstDroplets(tcx, tcy, tcx, tcy, tr, tr);
      setTimeout(function () { self._emitAnim(false); }, 320);
      toItem.classList.add('active');
      this.activeIndex = index;
      this.animating = false;
      if (callback) setTimeout(callback, this.options.animationTime * 0.4);
      return;
    }

    var fr = fromItem.getBoundingClientRect();

    var fromCx = fr.left - cr.left + fr.width / 2;
    var fromCy = fr.top - cr.top + fr.height / 2;
    var toCx = tr.left - cr.left + tr.width / 2;
    var toCy = tr.top - cr.top + tr.height / 2;

    // 药丸分裂为液滴，流向目标
    this._wakeTrail();
    // 滤镜区域收紧到「起点+终点」并集（覆盖整条运动走廊），暂停重型背景防卡顿
    this._setFilterRegion(
      Math.min(fr.left - cr.left, tr.left - cr.left),
      Math.min(fr.top - cr.top, tr.top - cr.top),
      Math.max(fr.width, tr.width),
      (Math.max(fr.top, tr.top) - Math.min(fr.top, tr.top)) + Math.max(fr.height, tr.height)
    );
    this._emitAnim(true);
    var self0 = this, toRect = tr, containerRect = cr;
    setTimeout(function () {
      self0._emitAnim(false);
      self0._setFilterRegion(toRect.left - containerRect.left, toRect.top - containerRect.top, toRect.width, toRect.height);
    }, this.options.animationTime * 0.75 + 60);
    this._burstDroplets(fromCx, fromCy, toCx, toCy, fr, tr);
    this._positionPill(index, false);

    // 55% 时切换激活态（药丸已到位）
    setTimeout(function () {
      fromItem.classList.remove('active');
      toItem.classList.add('active');
      self.activeIndex = index;
      self.animating = false;
    }, this.options.animationTime * 0.55);

    // 药丸即将到位即触发页面跳转（兼顾效果展示与响应速度）
    if (callback) {
      setTimeout(callback, this.options.animationTime * 0.55);
    }
  };

  // 液滴喷发（对齐 React Bits：particleDistances=[90,10], particleR=100）
  GooeyNav.prototype._burstDroplets = function (fx, fy, tx, ty, fr, tr) {
    var self = this;
    var distances = this.options.particleDistances; // [outer, inner]
    var outer = distances[0], inner = distances[1];
    var rFactor = this.options.particleR / 100;      // 半径因子
    var dirX = tx - fx, dirY = ty - fy;
    var len = Math.sqrt(dirX * dirX + dirY * dirY) || 1;
    var nx = -dirY / len, ny = dirX / len;           // 垂直方向单位向量

    for (var i = 0; i < this.particles.length; i++) {
      (function (p, idx) {
        // 扩散距离：在内侧~外侧之间随机，正负方向各半
        var sign = Math.random() < 0.5 ? -1 : 1;
        var off = sign * (inner + Math.random() * (outer - inner));
        var pFromX = fx + nx * off * 0.3;
        var pFromY = fy + ny * off * 0.3;
        var pToX = tx + nx * off * 0.4;
        var pToY = ty + ny * off * 0.4;

        // 控制点（弧线中间向外凸，制造旋转感）
        var midX = (fx + tx) / 2 + nx * off;
        var midY = (fy + ty) / 2 + ny * off;

        p.x = pFromX; p.y = pFromY;
        // 粒子大小：受 particleR 因子影响
        p.size = (8 + Math.random() * 10) * rFactor;
        p.targetX = pToX; p.targetY = pToY;
        p.midX = midX; p.midY = midY;
        p.startTime = performance.now() + idx * (self.options.timeVariance / self.options.particleCount);
        p.duration = self.options.animationTime + (Math.random() - 0.5) * self.options.timeVariance;

        p.el.style.width = p.size + 'px';
        p.el.style.height = p.size + 'px';
        p.el.style.transform = 'translate(' + (p.x - p.size / 2) + 'px,' + (p.y - p.size / 2) + 'px) scale(1)';
        p.el.style.opacity = '1';

        self._animateDroplet(p);
      })(this.particles[i], i);
    }
  };

  GooeyNav.prototype._animateDroplet = function (p) {
    function step(now) {
      var elapsed = now - p.startTime;
      if (elapsed < 0) { requestAnimationFrame(step); return; }
      var t = Math.min(elapsed / p.duration, 1);
      var ease = 1 - Math.pow(1 - t, 3);

      // 二次贝塞尔
      var omt = 1 - ease;
      var x = omt * omt * p.x + 2 * omt * ease * p.midX + ease * ease * p.targetX;
      var y = omt * omt * p.y + 2 * omt * ease * p.midY + ease * ease * p.targetY;

      // 大小：出发时大→中间小→汇聚时大（纯 transform，不重排）
      var scale = t < 0.25 ? 1 + (t / 0.25) * 0.5 : (t > 0.7 ? 0.6 + ((t - 0.7) / 0.3) * 1.0 : 1.1 - (t - 0.25) / 0.45 * 0.5);
      var opacity = t < 0.08 ? t / 0.08 : (t > 0.9 ? (1 - t) / 0.1 : 1);

      p.el.style.transform = 'translate(' + (x - p.size * scale / 2) + 'px,' + (y - p.size * scale / 2) + 'px) scale(' + scale + ')';
      p.el.style.opacity = opacity;

      if (t < 1) requestAnimationFrame(step);
      else p.el.style.opacity = '0';
    }
    requestAnimationFrame(step);
  };

  window.RBGooeyNav = GooeyNav;
})();

// 给 RBGooeyNav 加一个重建 SVG 滤镜的方法 + 让 _ensureGooFilter 读实例保存的值
(function patchGooeyFilterRebuild() {
  if (!window.RBGooeyNav) return;
  var origEnsure = window.RBGooeyNav.prototype._ensureGooFilter;
  window.RBGooeyNav.prototype._ensureGooFilter = function () {
    origEnsure.call(this);
    // 用实例保存的值覆盖默认值
    var blur = this._filterEl.querySelector('feGaussianBlur');
    var cm = this._filterEl.querySelector('feColorMatrix');
    if (blur) blur.setAttribute('stdDeviation', String(this._lastStdDev || 10));
    if (cm) cm.setAttribute('values',
      '1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 ' + (this._lastAlphaAmp || 19) + ' ' + (this._lastAlphaOff || -9));
  };
  window.RBGooeyNav.prototype._rebuildFilter = function () {
    if (!this._filterEl) return;
    var blur = this._filterEl.querySelector('feGaussianBlur');
    var cm = this._filterEl.querySelector('feColorMatrix');
    if (blur) blur.setAttribute('stdDeviation', String(this._lastStdDev || 10));
    if (cm) cm.setAttribute('values',
      '1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 ' + (this._lastAlphaAmp || 19) + ' ' + (this._lastAlphaOff || -9));
  };
})();

/* ============ 自动初始化侧边栏粘液导航 ============
 * 所有子页面都是独立 HTML（不 extends base.html），
 * 各自都 <script src="/static/assets/rb-effects.js"> 一次。
 * 这里用 requestAnimationFrame 延迟一帧后尝试初始化，
 * 比 DOMContentLoaded 更可靠（即使事件已触发也会执行）。
 */
(function initGooeyNav() {
  try {
    // 避免与 base.html 同步 IIFE 重复初始化
    if (window.__gooSidebar) return;

    var mainNav = document.getElementById('mainNav');
    var dataNav = document.getElementById('dataNav');
    var homeNav = document.getElementById('homeNav');
    var sysNav = document.getElementById('sysNav');
    if (!mainNav && !dataNav && !homeNav && !sysNav) {
      // DOM 可能还没解析到 sidebar，下一帧再试
      requestAnimationFrame(initGooeyNav);
      return;
    }
    if (typeof window.RBGooeyNav !== 'function') {
      requestAnimationFrame(initGooeyNav);
      return;
    }

    // 参数严格对齐 React Bits Gooey Nav 原版（https://reactbits.dev/components/gooey-nav）
    // 先给默认值，再从 localStorage 里读用户之前调的
    var DEFAULTS = {
      pillColor: '#10333d', particleCount: 22, animationTime: 600,
      timeVariance: 300, particleDistances: [130, 10], particleR: 100,
      colors: [1, 2, 3, 1, 2, 3, 1, 4],
      // SVG 滤镜参数（调参面板也会持久化）
      stdDev: 6, alphaAmp: 14, alphaOff: -7
    };
    var saved = null;
    try { saved = JSON.parse(localStorage.getItem('__gooParams')); } catch (e) {}
    var opts = Object.assign({}, DEFAULTS, saved || {});
    // 侧边栏深色化后，强制使用深青玻璃胶囊（忽略历史缓存中的白色）
    opts.pillColor = '#10333d';
    // particleDistances 要单独合并（数组）
    if (saved && saved.particleDistances) opts.particleDistances = saved.particleDistances;

    var gooMain = null, gooData = null, gooHome = null, gooSys = null;
    if (homeNav) gooHome = new RBGooeyNav('#homeNav', opts);
    if (mainNav) gooMain = new RBGooeyNav('#mainNav', opts);
    if (dataNav) gooData = new RBGooeyNav('#dataNav', opts);
    if (sysNav) gooSys = new RBGooeyNav('#sysNav', opts);
    // 构造函数已从 opts 读 stdDev/alphaAmp/alphaOff 写入 this._lastXxx
    // patch 的 _ensureGooFilter 会用实例保存的值覆盖 SVG 滤镜参数

    // 多组互斥：点击任一组时其他组药丸立即淡出
    var gooGroups = [
      { nav: homeNav, goo: gooHome },
      { nav: mainNav, goo: gooMain },
      { nav: dataNav, goo: gooData },
      { nav: sysNav, goo: gooSys }
    ].filter(function (g) { return g.nav && g.goo; });
    gooGroups.forEach(function (self) {
      self.nav.addEventListener('click', function () {
        gooGroups.forEach(function (other) {
          if (other !== self) other.goo.clearActive();
        });
      });
    });

    // 暴露 setter，**同时持久化到 localStorage**
    window.__gooSetParam = function (key, val) {
      var current = null;
      try { current = JSON.parse(localStorage.getItem('__gooParams') || '{}'); } catch (e) { current = {}; }
      current[key] = val;
      localStorage.setItem('__gooParams', JSON.stringify(current));
      [gooHome, gooMain, gooData, gooSys].forEach(function (g) {
        if (!g || !g.options) return;
        if (key === 'stdDev') { g._lastStdDev = val; g._rebuildFilter(); }
        else if (key === 'alphaAmp') { g._lastAlphaAmp = val; g._rebuildFilter(); }
        else { g.options[key] = val; }
      });
    };
    // 粒子扩散单独持久化（数组）
    window.__gooSetDistances = function (outer) {
      var current = null;
      try { current = JSON.parse(localStorage.getItem('__gooParams') || '{}'); } catch (e) { current = {}; }
      current.particleDistances = [outer, 10];
      localStorage.setItem('__gooParams', JSON.stringify(current));
      [gooHome, gooMain, gooData, gooSys].forEach(function (g) {
        if (!g || !g.options) return;
        g.options.particleDistances = [outer, 10];
      });
    };

    window.__gooSidebar = { home: gooHome, main: gooMain, data: gooData, sys: gooSys };
    console.log('[Gooey] initialized OK, main items:', gooMain ? gooMain.items.length : 0);
  } catch (e) {
    console.error('[Gooey] init FAILED:', e.message, e.stack);
  }
})();

// ============================================================
// 3.5 粘液动画期间的全局性能调度
//     暂停 Aurora/细胞场全屏 canvas + 临时去掉侧边栏 backdrop-filter
//     （backdrop-filter 每帧重新模糊全屏背景，是导航卡顿的主因）
// ============================================================
(function () {
  'use strict';
  var st = document.createElement('style');
  st.textContent =
    '.rb-goo-anim aside, .rb-goo-anim .sidebar { ' +
    'backdrop-filter: none !important; -webkit-backdrop-filter: none !important; ' +
    'background-color: rgba(8,16,30,0.92) !important; }';
  document.head.appendChild(st);

  window.addEventListener('rb-goo-anim', function (e) {
    var on = e.detail && e.detail.on;
    document.body.classList.toggle('rb-goo-anim', !!on);
    try {
      if (on) {
        if (window.RBAurora && RBAurora.stop) RBAurora.stop();
        if (window.PathoBG && PathoBG.setPaused) PathoBG.setPaused(true);
      } else {
        if (window.RBAurora && RBAurora.start) RBAurora.start();
        if (window.PathoBG && PathoBG.setPaused) PathoBG.setPaused(false);
      }
    } catch (err) {}
  });
})();


// ============================================================
// 4. Spotlight Card 聚光灯卡片
// ============================================================
(function () {
  'use strict';
  function SpotlightCard(card, options) {
    this.card = typeof card === 'string' ? document.querySelector(card) : card;
    this.options = Object.assign({
      color: 'rgba(6,182,212,0.22)',
      size: 320,
      intensity: 1,
      borderGlow: true
    }, options || {});
    this._init();
  }

  SpotlightCard.prototype._init = function () {
    var self = this;
    this.spotlight = document.createElement('div');
    this.spotlight.style.cssText = [
      'position:absolute', 'inset:0', 'border-radius:inherit',
      'pointer-events:none', 'opacity:0', 'transition:opacity .3s ease', 'z-index:1'
    ].join(';');
    this.card.style.position = 'relative';
    this.card.style.overflow = 'hidden';
    this.card.appendChild(this.spotlight);

    this.card.addEventListener('mouseenter', function () { self.spotlight.style.opacity = self.options.intensity; });
    this.card.addEventListener('mouseleave', function () { self.spotlight.style.opacity = '0'; self.card.style.boxShadow = ''; });

    this.card.addEventListener('mousemove', function (e) {
      var rect = self.card.getBoundingClientRect();
      var x = e.clientX - rect.left, y = e.clientY - rect.top;
      var size = self.options.size;
      self.spotlight.style.background = 'radial-gradient(circle at ' + x + 'px ' + y + 'px, ' +
        self.options.color + ' 0%, rgba(6,182,212,0.06) ' + (size * 0.4) + 'px, transparent ' + size + 'px)';
      if (self.options.borderGlow) {
        self.card.style.boxShadow = '0 0 24px rgba(6,182,212,0.2), inset 0 0 24px rgba(6,182,212,0.04)';
      }
    });
  };
  window.RBSpotlightCard = SpotlightCard;
})();


// ============================================================
// 5. PageTransition 页面过渡动画
// ============================================================
(function () {
  'use strict';

  var PageTransition = {
    overlay: null,
    duration: 240,
    initialized: false,

    init: function () {
      if (this.initialized) return;
      this.initialized = true;

      // 创建过渡遮罩（不覆盖侧边栏，让 gooey 导航效果保持可见）
      this.overlay = document.createElement('div');
      this.overlay.id = 'page-transition-overlay';
      this.overlay.style.cssText = [
        'position:fixed', 'top:0', 'right:0', 'bottom:0', 'left:240px',
        'z-index:99999',
        'background:linear-gradient(160deg,#0a1422,#070d18,#0b1a28)',
        'pointer-events:none', 'opacity:0',
        'transition:opacity ' + this.duration + 'ms cubic-bezier(0.4,0,0.2,1)',
        'display:flex', 'align-items:center', 'justify-content:center'
      ].join(';');

      // 加载指示器
      var loader = document.createElement('div');
      loader.style.cssText = [
        'width:48px', 'height:48px', 'border-radius:50%',
        'border:3px solid rgba(255,255,255,0.2)',
        'border-top-color:white',
        'animation:rb-spin 0.8s linear infinite',
        'opacity:0', 'transition:opacity 0.3s ease'
      ].join(';');
      this.overlay.appendChild(loader);
      this.loader = loader;

      // 注入动画样式
      var style = document.createElement('style');
      style.textContent = '@keyframes rb-spin{to{transform:rotate(360deg)}}';
      document.head.appendChild(style);

      document.body.appendChild(this.overlay);
    },

    go: function (url) {
      this.init();
      var self = this;
      this.overlay.style.opacity = '1';
      this.loader.style.opacity = '1';
      setTimeout(function () {
        window.location.href = url;
      }, this.duration);
    },

    enter: function () {
      // 页面加载时从遮罩淡出
      this.init();
      var self = this;
      // 先显示遮罩
      this.overlay.style.opacity = '1';
      this.overlay.style.transition = 'none';
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          self.overlay.style.transition = 'opacity ' + self.duration + 'ms cubic-bezier(0.4,0,0.2,1)';
          self.overlay.style.opacity = '0';
          self.loader.style.opacity = '0';
        });
      });
    }
  };

  window.RBPageTransition = PageTransition;

  // 页面进入时执行淡出
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { PageTransition.enter(); });
  } else {
    PageTransition.enter();
  }
})();


// ============================================================
// 6. CountUp 数字计数动画
// ============================================================
(function () {
  'use strict';
  function countUp(el, target, duration) {
    duration = duration || 1500;
    var startTime = null;
    function step(timestamp) {
      if (!startTime) startTime = timestamp;
      var progress = Math.min((timestamp - startTime) / duration, 1);
      var easeOutExpo = 1 - Math.pow(2, -10 * progress);
      var current = target * easeOutExpo;
      var display = target % 1 === 0 ? Math.floor(current).toLocaleString() : current.toFixed(1);
      el.textContent = display;
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  window.RBCountUp = countUp;
})();
