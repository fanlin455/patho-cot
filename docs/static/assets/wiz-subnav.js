/**
 * Patho-COT 侧边栏六步子菜单（分步诊断展开项）
 * 依赖：侧边栏"分步诊断"导航后存在 #wizSubnav，内含 6 个 .wz-sub[data-step]
 * 数据：sessionStorage pathocot_wizard_v1
 *   - taskId    上传后存在 → 展开子菜单
 *   - doneSteps 已完成步骤数组（1..5）
 *   - reportDone 第 6 步报告已生成
 * 导航：向导页内走 PathoCommon.wizardNavigate（立方体翻页），其他页直接跳转
 */
(function () {
  'use strict';

  var SS_KEY = 'pathocot_wizard_v1';

  /* ---------- 样式（注入一次，所有页面共享） ---------- */
  var CSS =
    '.wiz-subnav{max-height:0;overflow:hidden;opacity:0;transition:max-height .38s cubic-bezier(.4,0,.2,1),opacity .28s ease;padding:0 10px;}' +
    '.wiz-subnav.is-open{max-height:340px;opacity:1;padding:2px 10px 6px;}' +
    '.wz-sub{position:relative;display:flex;align-items:center;gap:10px;padding:7px 12px 7px 30px;margin:1px 0;border-radius:9px;cursor:pointer;' +
      'font-size:12.5px;color:#7c90a6;text-decoration:none;user-select:none;transition:background .2s ease,color .2s ease;}' +
    '.wz-sub::before{content:"";position:absolute;left:17px;top:0;bottom:50%;width:1px;background:rgba(148,163,184,.22);}' +
    '.wz-sub::after{content:"";position:absolute;left:17px;top:50%;width:9px;height:1px;background:rgba(148,163,184,.22);}' +
    '.wz-sub .wz-dot{flex-shrink:0;width:19px;height:19px;border-radius:50%;display:flex;align-items:center;justify-content:center;' +
      'font-size:10px;font-weight:700;background:rgba(148,163,184,.16);color:#93a7ba;transition:all .25s ease;}' +
    '.wz-sub .wz-name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}' +
    '.wz-sub:not(.is-locked):hover{background:rgba(45,212,191,.10);color:#cbd5e1;}' +
    '.wz-sub:not(.is-locked):hover .wz-dot{background:rgba(45,212,191,.28);color:#5eead4;}' +
    '.wz-sub.is-done .wz-dot{background:rgba(34,197,94,.22);color:#4ade80;}' +
    '.wz-sub.is-current{color:#67e8f9;font-weight:700;background:rgba(6,182,212,.14);}' +
    '.wz-sub.is-current .wz-dot{background:linear-gradient(135deg,#0d9488,#0891b2);color:#fff;box-shadow:0 0 12px rgba(45,212,191,.55);}' +
    '.wz-sub.is-current::before{background:rgba(45,212,191,.5);}' +
    '.wz-sub.is-locked{cursor:not-allowed;color:#4b5d70;}' +
    '.wz-sub.is-locked .wz-dot{background:rgba(100,116,139,.12);color:#55667a;}' +
    '/* 分步诊断父项展开箭头 */' +
    '#wizNavParent .wz-caret{margin-left:auto;flex-shrink:0;font-size:9px;color:#64748b;transition:transform .3s ease;}' +
    '#wizNavParent.is-expanded .wz-caret{transform:rotate(180deg);color:#5eead4;}' +
    '@media (max-width:900px){.wiz-subnav.is-open{max-height:300px;}}';
  var styleEl = document.createElement('style');
  styleEl.setAttribute('data-wiz-subnav', '1');
  styleEl.textContent = CSS;
  document.head.appendChild(styleEl);

  /* ---------- 状态读取 ---------- */
  function readSession() {
    try { return JSON.parse(sessionStorage.getItem(SS_KEY) || '{}'); }
    catch (e) { return {}; }
  }
  function currentStep() {
    var m = location.pathname.match(/^\/diagnose\/(\d)/);
    return m ? parseInt(m[1], 10) : 0;
  }

  /* ---------- 渲染 ---------- */
  function refresh() {
    var box = document.getElementById('wizSubnav');
    if (!box) return;
    var s = readSession();
    var started = !!s.taskId;
    var cur = currentStep();

    box.classList.toggle('is-open', started);

    var parent = document.getElementById('wizNavParent');
    if (parent) parent.classList.toggle('is-expanded', started);

    var doneMap = {};
    (s.doneSteps || []).forEach(function (i) { doneMap[i] = true; });
    if (s.reportDone) doneMap[6] = true;

    for (var i = 1; i <= 6; i++) {
      var item = box.querySelector('[data-step="' + i + '"]');
      if (!item) continue;
      var isDone = !!doneMap[i];
      var isCurrent = cur === i;
      var unlocked = isDone || isCurrent || (i === 1 && started);
      item.classList.toggle('is-done', isDone);
      item.classList.toggle('is-current', isCurrent);
      item.classList.toggle('is-locked', !unlocked);
      var dot = item.querySelector('.wz-dot');
      if (dot) dot.textContent = isDone ? '✓' : String(i);
      item.setAttribute('aria-disabled', unlocked ? 'false' : 'true');
      item.title = unlocked ? '' : '请先完成前面的步骤';
    }
  }

  /* ---------- 点击：权限校验 + 立方体导航 ---------- */
  document.addEventListener('click', function (e) {
    var item = e.target && e.target.closest ? e.target.closest('#wizSubnav .wz-sub') : null;
    if (!item) return;
    e.preventDefault();
    e.stopPropagation();
    if (item.classList.contains('is-locked')) return;

    var sid = parseInt(item.getAttribute('data-step'), 10);
    var cur = currentStep();
    if (sid === cur) return;

    if (window.PathoCommon && typeof window.PathoCommon.wizardNavigate === 'function') {
      PathoCommon.wizardNavigate('/diagnose/' + sid, sid > cur ? 'fwd' : 'back');
    } else {
      window.location.href = '/diagnose/' + sid;
    }
  });

  window.WizSubnav = { refresh: refresh, readSession: readSession };
  refresh();
})();
