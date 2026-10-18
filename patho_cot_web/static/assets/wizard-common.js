/**
 * Patho-COT 引导式诊断共用模块
 * 包含：确定性随机数、手机扫码上传弹窗（局域网配对）、检测框绘制
 */
(function () {
  'use strict';

  // ============ 确定性随机（同一图像结果可复现） ============
  function hashStr(s) {
    var h = 1779033703 ^ s.length;
    for (var i = 0; i < s.length; i++) {
      h = Math.imul(h ^ s.charCodeAt(i), 3432918353);
      h = (h << 13) | (h >>> 19);
    }
    return h >>> 0;
  }
  function mulberry32(seed) {
    var a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // ============ 手机扫码上传弹窗 ============
  var scanModalEl = null;
  var scanTimer = null;

  var SCAN_CSS =
    '#scanModal{position:fixed;inset:0;z-index:1000;display:none;}' +
    '#scanModal.show{display:block;}' +
    '#scanModal .scan-mask{position:absolute;inset:0;background:rgba(3,2,10,0.72);backdrop-filter:blur(6px);}' +
    '#scanModal .scan-card{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:360px;max-width:92vw;background:rgba(20,16,38,0.96);border:1px solid rgba(45,212,191,0.3);border-radius:20px;padding:24px 22px;text-align:center;box-shadow:0 30px 80px rgba(0,0,0,0.6),0 0 40px rgba(13,148,136,0.2);}' +
    '#scanModal .scan-close{position:absolute;top:10px;right:14px;background:none;border:none;color:#64748b;font-size:22px;cursor:pointer;line-height:1;}#scanModal .scan-close:hover{color:#fff;}' +
    '#scanModal .scan-title{font-size:17px;font-weight:700;color:#f1f5f9;}' +
    '#scanModal .scan-sub{font-size:11.5px;color:#94a3b8;margin:8px 0 16px;line-height:1.6;}' +
    '#scanModal .scan-qr-wrap{position:relative;width:220px;height:220px;margin:0 auto;background:#fff;border-radius:14px;display:flex;align-items:center;justify-content:center;overflow:hidden;}' +
    '#scanModal .scan-qr{width:100%;height:100%;display:none;}' +
    '#scanModal .scan-qr-loading{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#64748b;font-size:12px;padding:12px;}' +
    '#scanModal .scan-url{margin-top:12px;font-size:10.5px;color:#2dd4bf;word-break:break-all;background:rgba(13,148,136,0.1);border:1px solid rgba(45,212,191,0.2);border-radius:8px;padding:6px 10px;user-select:all;}' +
    '#scanModal .scan-wait{margin-top:14px;font-size:12.5px;color:#5eead4;display:flex;align-items:center;justify-content:center;gap:8px;}' +
    '#scanModal .scan-pulse{width:9px;height:9px;border-radius:50%;background:#06b6d4;animation:scanPulse 1.2s ease-in-out infinite;}' +
    '@keyframes scanPulse{0%,100%{transform:scale(1);opacity:1;box-shadow:0 0 0 0 rgba(6,182,212,0.5);}50%{transform:scale(1.25);opacity:0.7;box-shadow:0 0 0 8px rgba(6,182,212,0);}}' +
    '#scanModal .scan-steps{margin-top:14px;font-size:11px;color:#64748b;line-height:1.9;text-align:left;background:rgba(255,255,255,0.03);border-radius:10px;padding:10px 14px;}';

  function ensureScanModal() {
    if (scanModalEl) return scanModalEl;
    var st = document.createElement('style');
    st.textContent = SCAN_CSS;
    document.head.appendChild(st);
    var el = document.createElement('div');
    el.id = 'scanModal';
    el.innerHTML =
      '<div class="scan-mask"></div>' +
      '<div class="scan-card">' +
        '<button class="scan-close" title="关闭">×</button>' +
        '<div class="scan-title">📱 手机扫码上传</div>' +
        '<div class="scan-sub">手机与电脑连接同一 Wi-Fi，扫码后将病理图像直接传到本页</div>' +
        '<div class="scan-qr-wrap"><img class="scan-qr" alt="配对二维码"><div class="scan-qr-loading">生成二维码中…</div></div>' +
        '<div class="scan-url"></div>' +
        '<div class="scan-wait"><span class="scan-pulse"></span><span class="scan-wait-text">等待手机配对…</span></div>' +
        '<div class="scan-steps">1. 手机连接与本机相同的 Wi-Fi<br>2. 使用相机或微信扫码打开上传页<br>3. 可连续选择/拍摄多张图像逐张上传<br>4. 电脑端收齐后点右上角 × 关闭</div>' +
      '</div>';
    document.body.appendChild(el);
    el.querySelector('.scan-mask').onclick = closeScanModal;
    el.querySelector('.scan-close').onclick = closeScanModal;
    scanModalEl = el;
    return el;
  }

  function openScanModal(opts) {
    opts = opts || {};
    var el = ensureScanModal();
    el.classList.add('show');
    var session = 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

    fetch('/api/lan-info').then(function (r) { return r.json(); }).then(function (info) {
      var url = 'http://' + info.ip + ':' + info.port + '/m?session=' + session;
      el.querySelector('.scan-url').textContent = url;

      var qrImg = el.querySelector('.scan-qr');
      var loading = el.querySelector('.scan-qr-loading');
      try {
        if (typeof qrcode === 'undefined') throw new Error('qrcode lib missing');
        var qr = qrcode(0, 'M');
        qr.addData(url);
        qr.make();
        qrImg.src = qr.createDataURL(5, 6);
        qrImg.style.display = 'block';
        loading.style.display = 'none';
      } catch (e) {
        loading.innerHTML = '二维码生成失败，请手动在手机浏览器打开下方链接';
      }
    }).catch(function () {
      el.querySelector('.scan-url').textContent = '无法获取局域网地址，请确认服务器已启动';
    });

    // 轮询手机上传结果（一个会话可连续接收多张，收齐后由用户手动关闭弹窗）
    clearInterval(scanTimer);
    var receivedUrls = {};
    var receivedCount = 0;
    var waitText = el.querySelector('.scan-wait-text');
    scanTimer = setInterval(function () {
      fetch('/api/mobile-poll?session=' + session).then(function (r) { return r.json(); }).then(function (d) {
        if (!d || !d.hasImage) return;
        // 新接口返回 images 数组（游标增量）；兼容旧接口的单张字段
        var batch = (d.images && d.images.length) ? d.images
                    : [{ url: d.url, name: d.name }];
        // 逐张处理（onImage 可能是异步的），用已收 URL 去重
        var chain = Promise.resolve();
        batch.forEach(function (img) {
          if (!img || !img.url || receivedUrls[img.url]) return;
          receivedUrls[img.url] = true;
          receivedCount += 1;
          var name = decodeURIComponent(img.name || '手机上传图像');
          if (waitText) {
            waitText.textContent = '已接收 ' + receivedCount + ' 张，手机可继续上传，收齐后点右上角 ×';
          }
          if (opts.onImage) {
            chain = chain.then(function () { return opts.onImage({ url: img.url, name: name }); });
          }
        });
        chain.catch(function () {});
      }).catch(function () {});
    }, 1500);
  }

  function closeScanModal() {
    clearInterval(scanTimer);
    if (scanModalEl) scanModalEl.classList.remove('show');
  }

  // ============ 检测框绘制（绿框=正常 / 红框=病变） ============
  function drawDetection(canvas, imgSrc, lesionCount, normalCount, seedKey, cb) {
    var img = new Image();
    img.onload = function () {
      var maxW = 720;
      var scale = Math.min(1, maxW / img.width);
      var w = Math.round(img.width * scale);
      var h = Math.round(img.height * scale);
      canvas.width = w; canvas.height = h;
      var ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0, w, h);

      var rng = mulberry32(hashStr(seedKey || imgSrc));
      var minSide = Math.min(w, h);
      function drawBoxes(count, color) {
        ctx.lineWidth = Math.max(1.5, w / 420);
        ctx.strokeStyle = color;
        ctx.shadowColor = color;
        ctx.shadowBlur = 4;
        for (var i = 0; i < count; i++) {
          var bw = minSide * (0.045 + rng() * 0.05);
          var bh = bw * (0.75 + rng() * 0.5);
          var x = 6 + rng() * (w - bw - 12);
          var y = 6 + rng() * (h - bh - 12);
          ctx.strokeRect(x, y, bw, bh);
        }
        ctx.shadowBlur = 0;
      }
      drawBoxes(normalCount, 'rgba(34,197,94,0.9)');
      drawBoxes(lesionCount, 'rgba(239,68,68,0.95)');
      if (cb) cb();
    };
    img.src = imgSrc;
  }

  // ============ 六步向导：立方体翻页转场（方向感知，纯手动 MPA） ============
  // 出场：html[data-cube-leave] 让主内容区翻转 0.54s，再发起导航；
  // 入场：新文档 head 引导脚本第一帧前加 html[data-cube-enter]，主内容区反向翻入。
  // 浏览器前进/后退无法拦截出场，pageswap 仅用来提前写入方向，保证入场方向正确。
  var CUBE_DUR = 540;
  var DIR_KEY = 'wzCubeDir';
  var STEP_RE = /^\/diagnose\/(\d+)/;
  var leaving = false;

  function isWizardPath(p) { p = p || location.pathname; return STEP_RE.test(p); }
  function stepOf(url) {
    try {
      var u = new URL(url, location.href);
      var m = u.pathname.match(STEP_RE);
      return m ? parseInt(m[1], 10) : 0;
    } catch (e) { return 0; }
  }
  function currentStep() {
    var m = location.pathname.match(STEP_RE);
    return m ? parseInt(m[1], 10) : (window.PATHO_STEP || 0);
  }
  function normDir(d) { return d === 'back' ? 'back' : 'fwd'; }
  function dirTo(url) {
    var t = stepOf(url), c = currentStep();
    return (t && c && t < c) ? 'back' : 'fwd';
  }
  function saveDir(d) { try { sessionStorage.setItem(DIR_KEY, d); } catch (e) {} }

  // 新文档入场：head 内联脚本已提前设过一次属性，这里再兜底并负责动画结束后清理
  function armEnter() {
    if (!isWizardPath()) return;
    var d = 'fwd';
    try { d = sessionStorage.getItem(DIR_KEY) === 'back' ? 'back' : 'fwd'; } catch (e) {}
    document.documentElement.setAttribute('data-cube-enter', d);
    clearTimeout(armEnter._t);
    armEnter._t = setTimeout(function () {
      document.documentElement.removeAttribute('data-cube-enter');
    }, CUBE_DUR + 140);
  }

  // 统一导航入口：wizard-flow.js 的上一步/下一步/步骤条跳转及向导内链接都走这里
  function wizardNavigate(url, dir, force) {
    var inWiz = isWizardPath() && /^\/diagnose\/\d/.test(url);
    if (!inWiz) { window.location.href = url; return; }
    dir = normDir(dir || dirTo(url));
    // 已在目标步骤页时不做无谓重载（侧边栏当前页链接 / 重复点击）；
    // force=true 用于"重新上传"等明确需要重置页面状态的场景
    if (!force && stepOf(url) === currentStep()) return;
    if (leaving) return; // 出场期间忽略重复触发
    saveDir(dir);
    leaving = true;
    var html = document.documentElement;
    html.removeAttribute('data-cube-enter');
    html.setAttribute('data-cube-leave', dir);
    setTimeout(function () { window.location.href = url; }, CUBE_DUR);
  }

  // 浏览器前进/后退（无法拦截出场）：pageswap 可用时提前写入正确方向给入场用
  window.addEventListener('pageswap', function (e) {
    if (!isWizardPath() || leaving) return;
    var act = e.activation, d = 'fwd';
    if (act && act.type === 'traverse' && act.from && act.entry) {
      d = (typeof act.entry.index === 'number' && typeof act.from.index === 'number'
        && act.entry.index < act.from.index) ? 'back' : 'fwd';
    } else if (act && act.entry && act.entry.url) {
      d = dirTo(act.entry.url);
    }
    saveDir(d);
  });

  // 向导内普通链接（空态/错误页里的 <a>）：捕获阶段统一接管，先翻页再导航
  document.addEventListener('click', function (e) {
    if (!isWizardPath()) return;
    var a = e.target && e.target.closest ? e.target.closest('a[href^="/diagnose/"]') : null;
    if (!a) return;
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (a.target === '_blank' || a.hasAttribute('download')) return;
    e.preventDefault();
    wizardNavigate(a.getAttribute('href'), dirTo(a.getAttribute('href')));
  }, true);

  // bfcache 恢复 / 普通加载：清理残留转场属性并重排入场状态
  window.addEventListener('pageshow', function () {
    leaving = false;
    document.documentElement.removeAttribute('data-cube-leave');
    armEnter();
  });

  armEnter();

  window.PathoCommon = {
    hashStr: hashStr,
    mulberry32: mulberry32,
    openScanModal: openScanModal,
    closeScanModal: closeScanModal,
    drawDetection: drawDetection,
    wizardNavigate: wizardNavigate,
    armCubeEnter: armEnter
  };
})();
