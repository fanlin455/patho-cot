/**
 * Patho-COT 分步诊断共享流程（六独立页面版）
 * 依赖：页面声明 window.PATHO_STEP (1..6)；六步进度展示在侧边栏 #wizSubnav（wiz-subnav.js）
 * 数据：sessionStorage 存 task_id 与六步完成状态；任务事件存服务端，进页 GET 恢复。
 * 本文件仅承载原单页向导的等价逻辑，不改变任何接口契约。
 */
(function () {
  'use strict';

  var STEP = window.PATHO_STEP;
  var STEP_NAMES = ['', '质量检测', '器官分类', '细胞检测', '病变性质', '亚型提示', 'AI 报告'];
  var SS_KEY = 'pathocot_wizard_v1';

  var state = {
    taskId: null,
    filename: '',
    fileUrl: '',
    description: '',
    steps: {},        // sid(1..5) -> event
    recordId: null,
    report: '',
    running: false
  };

  /* ---------------- 工具函数（原向导等价搬迁） ---------------- */
  function escapeHtml(v) {
    return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }
  function fmtPct(v, d) {
    var n = Number(v);
    return Number.isFinite(n) ? (n * 100).toFixed(d || 1) + '%' : '-';
  }
  function animateCount(el) {
    var target = Number(el.dataset.count);
    if (!Number.isFinite(target)) return;
    var decimals = parseInt(el.dataset.decimals || '0', 10);
    var suffix = el.dataset.suffix || '';
    var dur = 900, start = performance.now();
    (function tick(now) {
      var p = Math.min(1, (now - start) / dur);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = (target * eased).toFixed(decimals) + suffix;
      if (p < 1) requestAnimationFrame(tick);
    })(start);
  }
  function animateCounts(root) {
    Array.prototype.forEach.call(root.querySelectorAll('[data-count]') || [], animateCount);
  }
  document.addEventListener('mousemove', function (e) {
    document.querySelectorAll('.spotlight:hover').forEach(function (card) {
      var r = card.getBoundingClientRect();
      card.style.setProperty('--mx', (e.clientX - r.left) + 'px');
      card.style.setProperty('--my', (e.clientY - r.top) + 'px');
    });
  });

  function cnt(v, d, suffix) {
    var n = Number(v);
    if (!Number.isFinite(n)) return '-';
    return '<span data-count="' + n + '" data-decimals="' + (d || 0) + '" data-suffix="' + (suffix || '') + '">0</span>';
  }
  function barList(items, defaultColor) {
    if (!items || items.length === 0) return '';
    var html = '<div class="space-y-2 max-w-lg mx-auto">';
    items.forEach(function (it) {
      var pct = Math.max(0, Math.min(100, Number(it.prob || 0) * 100));
      var color = it.color || defaultColor || 'bg-blue-500';
      html += '<div class="flex items-center gap-2">' +
        '<span class="w-32 text-sm text-gray-700 truncate" title="' + escapeHtml(it.name) + '">' + escapeHtml(it.name) + '</span>' +
        '<div class="flex-1 bg-gray-200 rounded-full h-2.5"><div class="' + color + ' h-2.5 rounded-full" style="width:' + pct + '%"></div></div>' +
        '<span class="text-xs text-gray-500 w-14 text-right">' + pct.toFixed(2) + '%</span></div>';
    });
    return html + '</div>';
  }

  /* ---------------- 步骤条 ---------------- */
  function setDot(sid, st) {
    var dot = document.getElementById('stepDot' + sid);
    if (!dot) return;
    var node = document.getElementById('stepNode' + sid);
    dot.className = 'w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold transition-all duration-300';
    if (st === 'running') { dot.className += ' bg-blue-600 text-white animate-pulse'; dot.textContent = '...'; }
    else if (st === 'done') { dot.className += ' bg-green-500 text-white'; dot.textContent = '✓'; }
    else if (st === 'error') { dot.className += ' bg-red-500 text-white'; dot.textContent = '!'; }
    else if (st === 'locked') { dot.className += ' bg-gray-200 text-gray-500'; dot.textContent = sid; }
    else { dot.className += ' bg-gray-200 text-gray-500'; dot.textContent = sid; }
    if (node) node.classList.toggle('locked', st === 'locked');
  }
  function refreshStepBar(persist) {
    for (var i = 1; i <= 6; i++) {
      if (i === 6) {
        if (state.report) setDot(6, 'done');
        else if (STEP === 6) setDot(6, state.running ? 'running' : 'locked');
        else setDot(6, 'locked');
        continue;
      }
      var evt = state.steps[i];
      if (evt && evt.status === 'done') setDot(i, 'done');
      else if (evt && evt.status === 'error') setDot(i, 'error');
      else if (STEP === i) setDot(i, state.running ? 'running' : (evt ? 'error' : 'locked'));
      else setDot(i, 'locked');
    }
    document.querySelectorAll('.step-connector').forEach(function (c) {
      var leftStep = Number(c.getAttribute('data-connector'));
      var ev = state.steps[leftStep];
      c.classList.toggle('done', !!(ev && ev.status === 'done'));
    });
    syncSidebar(persist);
  }
  // 把六步完成进度同步到侧边栏子菜单（sessionStorage，供所有页面的 wiz-subnav.js 读取）
  // persist=false 用于任务恢复失败等"内存状态不代表真相"的场景：只刷 UI，不清持久进度
  function syncSidebar(persist) {
    if (persist !== false) {
      try {
        var doneSteps = [];
        for (var i = 1; i <= 5; i++) {
          if (state.steps[i] && state.steps[i].status === 'done') doneSteps.push(i);
        }
        saveSession({ doneSteps: doneSteps, reportDone: state.report ? 1 : 0 });
      } catch (e) {}
    }
    if (window.WizSubnav && typeof window.WizSubnav.refresh === 'function') WizSubnav.refresh();
  }
  // 已完成步骤可点击回看；第1步有任务后可点回
  document.addEventListener('click', function (e) {
    var node = e.target.closest ? e.target.closest('.step-node') : null;
    if (!node) return;
    var sid = Number(node.getAttribute('data-step'));
    if (!sid || node.classList.contains('locked')) return;
    if (state.running) return;
    var canGo = sid === 1 ? !!state.taskId
      : (sid <= 5 ? !!(state.steps[sid] && state.steps[sid].status === 'done') : !!state.report);
    if (canGo) PathoCommon.wizardNavigate('/diagnose/' + sid, sid > STEP ? 'fwd' : 'back');
  });

  /* ---------------- 底部操作按钮 ---------------- */
  function btn(label, action, cls, id) {
    return '<button type="button" ' + (id ? 'id="' + id + '" ' : '') +
      'data-pw="' + action + '" class="goo-dark-btn px-5 py-2.5 text-sm font-semibold ' + (cls || '') + '">' + label + '</button>';
  }
  function renderActions() {
    var el = document.getElementById('stepActions');
    if (!el) return;
    var evt = state.steps[STEP];
    var err = evt && evt.status === 'error';
    var html = '';
    if (STEP === 1) {
      var qc = state.steps[1] && state.steps[1].data;
      if (err) {
        html = btn('重新上传', 'reupload', 'btn-primary') + btn('重新检测', 'rerun', 'btn-ghost');
      } else if (qc) {
        html = qc.is_usable
          ? btn('重新上传', 'reupload', 'btn-ghost') + btn('下一步：器官分类 →', 'next', 'btn-primary')
          : btn('重新上传', 'reupload', 'btn-primary') + btn('继续分析', 'qccontinue', 'btn-warn');
      }
    } else if (STEP >= 2 && STEP <= 5) {
      if (err) {
        html = btn('← 上一步', 'prev', 'btn-ghost') + btn('重新检测', 'rerun', 'btn-primary') + btn('重新上传', 'reupload', 'btn-ghost');
      } else if (evt && evt.status === 'done') {
        var nextLabel = STEP === 5 ? '生成 AI 报告 →' : '下一步：' + STEP_NAMES[STEP + 1] + ' →';
        html = btn('← 上一步', 'prev', 'btn-ghost') +
               (STEP === 3 ? btn('重新检测', 'rerun', 'btn-ghost') : '') +
               btn(nextLabel, 'next', 'btn-primary');
      }
    } else if (STEP === 6) {
      if (state.report) {
        html = btn('← 返回第 5 步', 'prev', 'btn-ghost') +
               btn('查看历史记录', 'history', 'btn-ghost') +
               btn('重新分析新图', 'reupload', 'btn-primary');
      }
    }
    el.innerHTML = html ? '<div class="flex flex-wrap items-center justify-between gap-3">' + html + '</div>' : '';
    el.classList.toggle('hidden', !html);
    attachGooey(el);
  }
  function attachGooey(container) {
    if (window.GooeyNav) {
      try {
        window.GooeyNav.attach(container, function () {
          return Array.prototype.slice.call(container.querySelectorAll('button'));
        }, { radius: '100vw', outset: 8, initial: 0, showOnClickOnly: true });
      } catch (e) {}
    }
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('[data-pw]') : null;
    if (!b || state.running) return;
    var act = b.getAttribute('data-pw');
    if (act === 'prev') PathoCommon.wizardNavigate('/diagnose/' + (STEP - 1), 'back');
    else if (act === 'next') {
      if (STEP === 5) PathoCommon.wizardNavigate('/diagnose/6?run=1', 'fwd');
      else PathoCommon.wizardNavigate('/diagnose/' + (STEP + 1) + '?run=1', 'fwd');
    } else if (act === 'history') window.location.href = '/history';
    else if (act === 'reupload') resetSession();
    else if (act === 'rerun') runStep(true);
    else if (act === 'start') runStep(false);
    else if (act === 'qccontinue') openQcModal();
    else if (act === 'genreport') runReport();
  });

  /* ---------------- 会话存取 ---------------- */
  function loadSession() {
    try { return JSON.parse(sessionStorage.getItem(SS_KEY) || '{}'); } catch (e) { return {}; }
  }
  function saveSession(patch) {
    var s = Object.assign(loadSession(), patch);
    sessionStorage.setItem(SS_KEY, JSON.stringify(s));
    return s;
  }
  function resetSession() {
    sessionStorage.removeItem(SS_KEY);
    if (window.WizSubnav && typeof window.WizSubnav.refresh === 'function') WizSubnav.refresh();
    PathoCommon.wizardNavigate('/diagnose/1', 'back', true);
  }
  window.PathoWizardReset = resetSession;

  function getParam(name) {
    return new URLSearchParams(location.search).get(name);
  }

  /* ---------------- 页面空态/就绪态 ---------------- */
  function showPanel(name) {
    ['uploadCard', 'resultCard', 'emptyState', 'readyCard', 'qcConfirmModal'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.classList.add('hidden');
    });
    var target = document.getElementById(name);
    if (target) target.classList.remove('hidden');
  }
  function readyBody(html) {
    var body = document.getElementById('stepBody');
    if (body) body.innerHTML = html;
  }

  /* ---------------- 分步推理 ---------------- */
  function runStep(isRetry) {
    if (state.running || !state.taskId) return;
    if (STEP < 1 || STEP > 5) return;
    state.running = true;
    showPanel('resultCard');
    readyBody('<div class="py-2">' +
      '<div class="skeleton h-4 w-2/3 mx-auto mb-3"></div>' +
      '<div class="skeleton h-3 w-1/2 mx-auto mb-2"></div>' +
      '<div class="skeleton h-3 w-3/5 mx-auto mb-6"></div>' +
      '<div class="flex items-center justify-center gap-2 text-sm text-gray-500"><div class="spinner"></div><span>正在分析，请稍候...</span></div></div>');
    setDot(STEP, 'running');
    refreshStepBar();
    document.getElementById('stepActions').classList.add('hidden');
    fetch('/api/tasks/' + state.taskId + '/steps/' + STEP, { method: 'POST' })
      .then(function (resp) {
        if (!resp.ok) return resp.json().catch(function () { return {}; }).then(function (j) {
          throw new Error(j.error || ('请求失败 ' + resp.status));
        });
        return resp.json();
      })
      .then(function (data) {
        state.steps[STEP] = data.event;
        if (data.record_id != null) state.recordId = data.record_id;
        if (STEP === 1) {
          fetch('/api/tasks/' + state.taskId + '/warmup', { method: 'POST' }).catch(function () {});
        }
        renderStep(STEP, data.event.data || {});
        if (data.event.status === 'error') renderStepError(STEP, data.event.message || '分析失败');
        renderActions();
      })
      .catch(function (err) {
        state.steps[STEP] = { step_id: STEP, step_name: STEP_NAMES[STEP], status: 'error', data: {}, message: err.message };
        renderStepError(STEP, err.message);
        renderActions();
      })
      .finally(function () { state.running = false; refreshStepBar(); });
  }

  /* ---------------- 各步结果渲染（原向导等价搬迁） ---------------- */
  function renderStep(sid, d) {
    showPanel('resultCard');
    if (sid === 1) {
      var badge = document.getElementById('qcBadge');
      if (badge) badge.innerHTML = d.is_usable
        ? '<span class="px-3 py-1 rounded-full text-sm font-semibold bg-green-100 text-green-700">PASS</span>'
        : '<span class="px-3 py-1 rounded-full text-sm font-semibold bg-red-100 text-red-700">REJECT</span>';
      var reasons = '';
      var msgs = [].concat(d.fail_reasons || []).concat(d.warnings || []);
      if (msgs.length > 0) {
        reasons = '<div class="mt-4 rounded-lg border border-' + (d.is_usable ? 'gray' : 'red') + '-200 bg-' + (d.is_usable ? 'gray' : 'red') + '-50 p-3 text-sm text-' + (d.is_usable ? 'gray' : 'red') + '-700">' + msgs.map(escapeHtml).join('；') + '</div>';
      }
      readyBody(
        '<div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">' +
        '<div><div class="text-3xl font-bold ' + (d.is_usable ? 'text-teal-600' : 'text-red-600') + '">' + cnt(d.usability_score, 2) + '</div><div class="text-xs text-gray-500 mt-1">可用性</div></div>' +
        '<div><div class="text-3xl font-bold text-teal-600">' + cnt(d.focus_score, 1) + '</div><div class="text-xs text-gray-500 mt-1">对焦</div></div>' +
        '<div><div class="text-3xl font-bold text-teal-600">' + cnt(d.stain_score, 1) + '</div><div class="text-xs text-gray-500 mt-1">染色</div></div>' +
        '<div><div class="text-3xl font-bold text-teal-600">' + cnt(d.tissue_ratio != null ? d.tissue_ratio * 100 : null, 1, '%') + '</div><div class="text-xs text-gray-500 mt-1">组织占比</div></div>' +
        '</div>' + reasons);
    } else if (sid === 2) {
      var ob = document.getElementById('organBadge');
      if (ob) {
        ob.textContent = (d.top_organ_cn || d.top_organ || '-') + '（' + fmtPct(d.top_prob, 2) + '）';
        ob.classList.remove('hidden');
      }
      readyBody(
        '<div class="text-center mb-4"><div class="text-2xl font-bold text-blue-700">' + escapeHtml(d.top_organ_cn || d.top_organ || '-') + '</div>' +
        '<div class="text-sm text-gray-500 mt-1">置信度 ' + cnt(d.top_prob != null ? d.top_prob * 100 : null, 2, '%') + '</div></div>' +
        barList((d.top5 || []).map(function (x) { return { name: x.name_cn || x.name, prob: x.prob }; }), 'bg-blue-500') +
        (d.chart_url ? '<img src="' + escapeHtml(d.chart_url) + '" class="mt-4 mx-auto rounded-lg border border-gray-100 max-w-sm w-full" alt="器官分类图">' : ''));
    } else if (sid === 3) {
      var db = document.getElementById('detectBadge');
      var lesion = d.lesion_count || 0;
      if (db) {
        db.textContent = lesion > 0 ? '检出 ' + lesion + ' 个病变细胞' : '未检出病变细胞';
        db.className = 'ml-auto px-3 py-1 rounded-full text-sm font-semibold ' + (lesion > 0 ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700');
        db.classList.remove('hidden');
      }
      readyBody(
        '<div class="grid grid-cols-3 gap-4 text-center mb-4">' +
        '<div><div class="text-3xl font-bold text-red-600">' + cnt(d.lesion_count, 0) + '</div><div class="text-xs text-gray-500 mt-1">病变细胞</div></div>' +
        '<div><div class="text-3xl font-bold text-green-600">' + cnt(d.non_lesion_count, 0) + '</div><div class="text-xs text-gray-500 mt-1">非病变细胞</div></div>' +
        '<div><div class="text-3xl font-bold text-gray-600">' + cnt(d.total_boxes, 0) + '</div><div class="text-xs text-gray-500 mt-1">总检出数</div></div></div>' +
        (d.roi_image_url ? '<img src="' + escapeHtml(d.roi_image_url) + '" class="mx-auto rounded-lg border border-gray-100 max-w-xl w-full" alt="细胞检测标注图">' : ''));
    } else if (sid === 4) {
      var nb = document.getElementById('natureBadge');
      var abnormal = d.top_nature === 'Abnormal';
      if (nb) {
        nb.textContent = (d.top_nature_cn || d.top_nature || '-') + '（' + fmtPct(d.top_prob, 2) + '）';
        nb.className = 'ml-auto px-3 py-1 rounded-full text-sm font-semibold ' + (abnormal ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700');
        nb.classList.remove('hidden');
      }
      readyBody(
        '<div class="text-center mb-4"><div class="text-2xl font-bold ' + (abnormal ? 'text-red-600' : 'text-green-600') + '">' + escapeHtml(d.top_nature_cn || d.top_nature || '-') + '</div>' +
        '<div class="text-sm text-gray-500 mt-1">置信度 ' + cnt(d.top_prob != null ? d.top_prob * 100 : null, 2, '%') + '</div></div>' +
        barList((d.probs || []).map(function (x) { return { name: x.name_cn || x.name, prob: x.prob, color: x.name === 'Abnormal' ? 'bg-red-500' : 'bg-green-500' }; }), '') +
        (d.chart_url ? '<img src="' + escapeHtml(d.chart_url) + '" class="mt-4 mx-auto rounded-lg border border-gray-100 max-w-sm w-full" alt="病变性质图">' : '') +
        (d.anomaly_heatmap_url ? '<div class="mt-4 border-t border-gray-100 pt-3"><div class="text-sm font-semibold text-gray-700 mb-1">扩散异常检测 <span class="text-xs text-gray-400">（实验性参考）</span></div><div class="text-xs text-gray-500 mb-2">重建误差分数 ' + cnt(d.anomaly_score, 4) + '</div><img src="' + escapeHtml(d.anomaly_heatmap_url) + '" class="mx-auto rounded-lg border border-gray-100 max-w-xl w-full" alt="异常热力图"></div>' : ''));
    } else if (sid === 5) {
      var sb = document.getElementById('subtypeBadge');
      if (sb) {
        sb.textContent = (d.top_subtype_cn || d.top_subtype || '-') + '（' + fmtPct(d.top_prob, 2) + '）';
        sb.classList.remove('hidden');
      }
      readyBody(
        '<div class="text-center mb-4"><div class="text-2xl font-bold text-amber-600">' + escapeHtml(d.top_subtype_cn || d.top_subtype || '-') + '</div>' +
        '<div class="text-sm text-gray-500 mt-1">置信度 ' + cnt(d.top_prob != null ? d.top_prob * 100 : null, 2, '%') + '</div></div>' +
        barList((d.top5 || []).map(function (x) { return { name: x.name_cn || x.code || x.name, prob: x.prob }; }), 'bg-amber-500') +
        (d.chart_url ? '<img src="' + escapeHtml(d.chart_url) + '" class="mt-4 mx-auto rounded-lg border border-gray-100 max-w-sm w-full" alt="亚型分类图">' : ''));
    }
    animateCounts(document.getElementById('stepBody'));
  }

  function renderStepError(sid, msg) {
    showPanel('resultCard');
    readyBody('<div class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">' +
      '<div class="font-semibold mb-1">' + escapeHtml(STEP_NAMES[sid]) + '失败</div><div>' + escapeHtml(msg) + '</div></div>');
  }

  /* ---------------- 第1页：上传 ---------------- */
  function setUploadBusy(busy) {
    var btn = document.getElementById('submitBtn');
    if (!btn) return;
    btn.disabled = busy;
    document.getElementById('btnText').textContent = busy ? '上传中' : '开始分析';
    document.getElementById('btnSpinner').classList.toggle('hidden', !busy);
  }
  function createTask(file) {
    setUploadBusy(true);
    var fd = new FormData();
    fd.append('file', file);
    fd.append('description', (document.getElementById('descriptionInput').value || '').trim());
    fetch('/api/tasks', { method: 'POST', body: fd })
      .then(function (resp) {
        if (!resp.ok) throw new Error('上传失败 ' + resp.status);
        return resp.json();
      })
      .then(function (data) {
        state.taskId = data.task_id;
        state.fileUrl = data.file_url;
        state.filename = data.filename || file.name;
        state.description = (document.getElementById('descriptionInput').value || '').trim();
        state.steps = {};
        state.recordId = null;
        state.report = '';
        saveSession({ taskId: state.taskId, description: state.description, qcContinue: 0, doneSteps: [], reportDone: 0 });
        syncSidebar();
        var banner = document.getElementById('qcFailBanner');
        if (banner) banner.classList.add('hidden');
        runStep(false);
      })
      .catch(function (err) { alert('上传失败: ' + err.message); })
      .finally(function () { setUploadBusy(false); });
  }
  function bindUploadUI() {
    var form = document.getElementById('uploadForm');
    if (!form || form.__pwBound) return;
    form.__pwBound = true;
    var input = document.getElementById('imageFile');
    var pick = document.getElementById('pickFileBtn');
    var nameEl = document.getElementById('fileName');
    pick.addEventListener('click', function () { input.click(); });
    input.addEventListener('change', function () {
      var f = input.files && input.files[0];
      if (nameEl) nameEl.textContent = f ? f.name : '未选择文件';
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var file = input.files[0];
      if (!file) { alert('请先选择一张病理图像'); return; }
      createTask(file);
    });
    document.querySelectorAll('.sample-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        var name = b.getAttribute('data-sample');
        setUploadBusy(true);
        fetch('/static/samples/' + name).then(function (r) {
          if (!r.ok) throw new Error('样例加载失败 ' + r.status);
          return r.blob();
        }).then(function (blob) {
          var file = new File([blob], name, { type: blob.type || 'image/png' });
          document.getElementById('descriptionInput').value = '';
          createTask(file);
        }).catch(function (err) { alert('样例加载失败: ' + err.message); })
          .finally(function () { setUploadBusy(false); });
      });
    });
    var scanBtn = document.getElementById('scanBtn');
    if (scanBtn && window.PathoCommon) {
      scanBtn.addEventListener('click', function () {
        PathoCommon.openScanModal({
          onImage: function (d) {
            return fetch(d.url).then(function (r) {
              if (!r.ok) throw new Error('拉取失败 ' + r.status);
              return r.blob();
            }).then(function (blob) {
              var file = new File([blob], d.name, { type: blob.type || 'image/png' });
              var dt = new DataTransfer();
              dt.items.add(file);
              input.files = dt.files;
              input.dispatchEvent(new Event('change'));
            }).catch(function (e) { alert('手机图像加载失败: ' + e.message); });
          }
        });
      });
    }
  }

  /* ---------------- 质检未通过弹窗 ---------------- */
  function openQcModal() { var m = document.getElementById('qcConfirmModal'); if (m) m.classList.remove('hidden'); }
  document.addEventListener('click', function (e) {
    var okBtn = e.target.closest ? e.target.closest('[data-qc="ok"]') : null;
    var noBtn = e.target.closest ? e.target.closest('[data-qc="no"]') : null;
    if (noBtn) { var m0 = document.getElementById('qcConfirmModal'); if (m0) m0.classList.add('hidden'); }
    if (okBtn) {
      var m = document.getElementById('qcConfirmModal'); if (m) m.classList.add('hidden');
      saveSession({ qcContinue: 1 });
      PathoCommon.wizardNavigate('/diagnose/2?run=1', 'fwd');
    }
  });

  /* ---------------- 第6步：AI 报告（SSE，等价搬迁） ---------------- */
  function consumeSSE(response, onEvent) {
    if (!response.ok) throw new Error('请求失败：' + response.status);
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';
    function pump() {
      return reader.read().then(function (r) {
        if (r.done) return;
        buffer += decoder.decode(r.value, { stream: true });
        var lines = buffer.split('\n');
        buffer = lines.pop() || '';
        lines.forEach(function (line) {
          if (!line.startsWith('data: ')) return;
          var content = line.slice(6);
          if (content === '[DONE]' || !content.trim()) return;
          try { onEvent(JSON.parse(content)); } catch (e) { console.warn('SSE 解析失败', e); }
        });
        return pump();
      });
    }
    return pump();
  }
  function renderReport(reportText) {
    state.report = reportText || '';
    var badge = document.getElementById('reportBadge');
    if (badge) { badge.textContent = 'LLM 生成'; badge.classList.remove('hidden'); }
    var cp = document.getElementById('copyReportBtn'); if (cp) cp.classList.remove('hidden');
    var pp = document.getElementById('printReportBtn'); if (pp) pp.classList.remove('hidden');
    var html;
    if (typeof marked !== 'undefined') html = marked.parse(reportText);
    else html = '<p>' + escapeHtml(reportText).replace(/\n\n/g, '</p><p>').replace(/\n/g, '<br>') + '</p>';
    document.getElementById('reportContent').innerHTML = html;
  }
  function runReport() {
    if (state.running) return;
    state.running = true;
    refreshStepBar();
    showPanel('resultCard');
    document.getElementById('reportContent').innerHTML =
      '<p class="text-gray-400 text-center"><span class="animate-pulse">...</span> 正在生成报告...</p>';
    document.getElementById('stepActions').classList.add('hidden');
    var results = [1, 2, 3, 4, 5].map(function (i) { return state.steps[i]; }).filter(Boolean);
    fetch('/api/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description: state.description, results: results, record_id: state.recordId })
    }).then(function (resp) {
      return consumeSSE(resp, function (event) {
        if (event.data && event.data.report) {
          state.report = event.data.report;
          renderReport(event.data.report);
          renderActions();
        } else if (event.status === 'error') {
          document.getElementById('reportContent').innerHTML =
            '<p class="text-red-600 text-center">报告生成失败：' + escapeHtml(event.message || '未知错误') + '</p>' +
            '<p class="text-xs text-gray-400 text-center mt-2">（前五步结果不受影响，已保存到历史记录。安装 Ollama 后可使用 AI 报告功能。）</p>';
          renderActions();
        }
      });
    }).catch(function (err) {
      document.getElementById('reportContent').innerHTML =
        '<p class="text-red-600 text-center">报告生成失败: ' + escapeHtml(err.message) + '</p>';
      renderActions();
    }).finally(function () { state.running = false; refreshStepBar(); });
  }
  function copyReport() {
    var text = state.report || document.getElementById('reportContent').innerText || '';
    var done = function () {
      var btn = document.getElementById('copyReportBtn');
      btn.textContent = '已复制 ✓';
      setTimeout(function () { btn.textContent = '复制报告'; }, 2000);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () {
        var ta = document.createElement('textarea'); ta.value = text;
        document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); } catch (e) {}
        document.body.removeChild(ta); done();
      });
    }
  }

  /* ---------------- 3D 浏览器标签（第3页）懒加载 + 全屏打开 ---------------- */
  function bindExplorerTabs() {
    var tabs = document.querySelectorAll('[data-tab]');
    if (tabs.length) {
      tabs.forEach(function (tab) {
        tab.addEventListener('click', function () {
          tabs.forEach(function (t) { t.classList.remove('tab-active'); });
          tab.classList.add('tab-active');
          var key = tab.getAttribute('data-tab');
          document.querySelectorAll('[data-tabpanel]').forEach(function (p) {
            p.classList.toggle('hidden', p.getAttribute('data-tabpanel') !== key);
          });
          var frame = document.getElementById('explorerFrame');
          if (key === 'explorer' && frame && !frame.src) frame.src = '/explorer?embed=1';
        });
      });
    }

    // ⛶ 全屏打开：优先把 iframe 切到浏览器全屏（必须在点击手势内同步请求）；
    // 不支持全屏 API 或被宿主（如内嵌浏览器）拒绝时，兜底新标签打开独立页
    var fsBtn = document.getElementById('fullExplorerBtn');
    if (fsBtn) {
      fsBtn.addEventListener('click', function (e) {
        e.preventDefault();
        var exTab = document.querySelector('[data-tab="explorer"]');
        var frame = document.getElementById('explorerFrame');
        if (exTab) exTab.click();
        if (!frame) { window.open('/explorer', '_blank', 'noopener'); return; }
        if (!frame.src) frame.src = '/explorer?embed=1';
        var req = frame.requestFullscreen || frame.webkitRequestFullscreen ||
                  frame.webkitEnterFullscreen || frame.msRequestFullscreen;
        var entered = false;
        if (req) {
          try {
            var r = req.call(frame);
            entered = true;
            if (r && typeof r.then === 'function') {
              r.catch(function () {
                if (!document.fullscreenElement && !document.webkitFullscreenElement) {
                  window.open('/explorer', '_blank', 'noopener');
                }
              });
            }
          } catch (err) { entered = false; }
        }
        if (!entered) {
          // 个别宿主（Electron/老内核）全屏 API 不可用：新标签兜底
          window.open('/explorer', '_blank', 'noopener');
        }
      });
    }
  }

  /* ---------------- 初始化 ---------------- */
  function showTaskChip() {
    var chip = document.getElementById('taskChip');
    if (!chip || !state.filename) return;
    chip.classList.remove('hidden');
    chip.innerHTML = '当前任务：<b>' + escapeHtml(state.filename) + '</b>' +
      (state.fileUrl ? ' · <a href="' + state.fileUrl + '" target="_blank" class="underline">查看原图</a>' : '');
  }
  function showEmpty(msg) {
    showPanel('emptyState');
    var b = document.getElementById('emptyBody');
    if (b) b.innerHTML = msg;
    var a = document.getElementById('stepActions'); if (a) a.classList.add('hidden');
  }

  function init() {
    bindUploadUI();
    bindExplorerTabs();
    var cpBtn = document.getElementById('copyReportBtn');
    if (cpBtn) cpBtn.addEventListener('click', copyReport);
    var ppBtn = document.getElementById('printReportBtn');
    if (ppBtn) ppBtn.addEventListener('click', function () { window.print(); });
    refreshStepBar();

    var sess = loadSession();
    if (sess.qcContinue) {
      var banner = document.getElementById('qcFailBanner');
      if (banner && STEP >= 2) banner.classList.remove('hidden');
    }

    // 第1页：无任务即上传态；有任务则恢复质检结果
    if (STEP === 1) {
      if (!sess.taskId) { showPanel('uploadCard'); return; }
      restore(sess.taskId, sess, true);
      return;
    }

    // 第2~6页：必须存在任务
    if (!sess.taskId) {
      showEmpty('尚未开始诊断。请先在第一步上传病理图像。<br><br>' +
        '<a href="/diagnose/1" class="btn-primary inline-block px-5 py-2.5 rounded-lg text-sm font-semibold">前往上传图像</a>');
      refreshStepBar();
      return;
    }
    restore(sess.taskId, sess, false);
  }

  function restore(taskId, sess, isStepOne) {
    fetch('/api/tasks/' + taskId)
      .then(function (r) { if (!r.ok) throw new Error('expired'); return r.json(); })
      .then(function (data) {
        state.taskId = data.task_id;
        state.filename = data.filename || '';
        state.fileUrl = data.file_url || '';
        state.description = data.description || sess.description || '';
        state.steps = data.steps || {};
        state.recordId = data.record_id;
        state.report = data.report || '';
        showTaskChip();
        refreshStepBar();

        if (STEP === 1) {
          if (state.steps[1]) {
            renderStep(1, state.steps[1].data || {});
            if (state.steps[1].status !== 'done') renderStepError(1, state.steps[1].message || '分析失败');
            renderActions();
          } else { showPanel('uploadCard'); }
          return;
        }

        if (STEP <= 5) {
          // 前置步骤未完成：引导回上一步
          var prevEvt = state.steps[STEP - 1];
          if (!prevEvt || prevEvt.status !== 'done') {
            showEmpty('请先完成上一步：<b>' + STEP_NAMES[STEP - 1] + '</b>。<br><br>' +
              '<a href="/diagnose/' + (STEP - 1) + '" class="btn-primary inline-block px-5 py-2.5 rounded-lg text-sm font-semibold">← 返回第 ' + (STEP - 1) + ' 步</a>');
            return;
          }
          var cur = state.steps[STEP];
          if (cur) {
            if (cur.status === 'done') renderStep(STEP, cur.data || {});
            else renderStepError(STEP, cur.message || '分析失败');
            renderActions();
          } else if (getParam('run') === '1') {
            runStep(false);
          } else {
            showPanel('readyCard');
            renderActions();
          }
          return;
        }

        // 第6页 AI 报告
        if (state.report) {
          showPanel('resultCard');
          renderReport(state.report);
          renderActions();
        } else if (getParam('run') === '1') {
          showPanel('resultCard');
          runReport();
        } else {
          showPanel('readyCard');
          renderActions();
        }
      })
      .catch(function () {
        if (STEP === 1) { showPanel('uploadCard'); return; }
        showEmpty('任务已过期（服务重启或会话超时），请重新上传图像。<br><br>' +
          '<a href="/diagnose/1" class="btn-primary inline-block px-5 py-2.5 rounded-lg text-sm font-semibold">重新上传图像</a>');
        refreshStepBar(false);
      });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
