/* ============================================================
   Patho-COT 全站可视化改版 · 共享图表工具
   - Chart.js 深色主题默认配置
   - 病理相关模拟数据生成器
   - 通用图表工厂
   ============================================================ */
(function (global) {
    'use strict';

    // ---------- 配色板 ----------
    var COLORS = {
        teal: '#2dd4bf', cyan: '#06b6d4', blue: '#38bdf8', sky: '#22d3ee',
        green: '#4ade80', emerald: '#10b981', amber: '#fbbf24', orange: '#fb923c',
        purple: '#a78bfa', pink: '#f472b6', red: '#f87171', slate: '#64748b'
    };
    var PALETTE = [COLORS.teal, COLORS.cyan, COLORS.blue, COLORS.sky, COLORS.green,
                   COLORS.amber, COLORS.purple, COLORS.pink, COLORS.orange, COLORS.red];

    // ---------- 通用深色主题 ----------
    function darkScales(extra) {
        var base = {
            x: { ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.05)' } },
            y: { ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.05)' } }
        };
        if (extra) Object.assign(base, extra);
        return base;
    }

    function darkLegend(opts) {
        return Object.assign({
            display: true, position: 'top', align: 'end',
            labels: { color: '#94a3b8', font: { size: 10 }, boxWidth: 10, usePointStyle: true, pointStyle: 'circle', padding: 10 }
        }, opts || {});
    }

    function darkTooltip() {
        return {
            backgroundColor: 'rgba(8,15,30,0.95)',
            titleColor: '#f1f5f9',
            bodyColor: '#cbd5e1',
            borderColor: 'rgba(45,212,191,0.3)',
            borderWidth: 1,
            cornerRadius: 8,
            padding: 10
        };
    }

    // 统一深色配置混入
    function darkOptions(overrides) {
        var opts = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: darkLegend(),
                tooltip: darkTooltip()
            },
            scales: darkScales()
        };
        if (overrides) mergeDeep(opts, overrides);
        return opts;
    }

    function mergeDeep(target, src) {
        for (var k in src) {
            if (src[k] && typeof src[k] === 'object' && !Array.isArray(src[k]) && target[k] && typeof target[k] === 'object') {
                mergeDeep(target[k], src[k]);
            } else {
                target[k] = src[k];
            }
        }
        return target;
    }

    // ---------- 渐变工厂 ----------
    function makeGradient(ctx, chartArea, top, bottom) {
        if (!chartArea) return top;
        var g = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
        g.addColorStop(0, bottom);
        g.addColorStop(1, top);
        return g;
    }

    // ---------- 图表工厂 ----------
    function makeChart(type, canvasId, data, opts) {
        var el = document.getElementById(canvasId);
        if (!el) return null;
        var ctx = el.getContext('2d');
        var merged = darkOptions(opts || {});
        return new Chart(ctx, { type: type, data: data, options: merged });
    }

    // ---------- 模拟数据生成器 ----------
    function rand(min, max) { return Math.random() * (max - min) + min; }
    function randInt(min, max) { return Math.floor(rand(min, max + 1)); }

    var ORGANS = ['结肠', '胃', '肺', '肝', '乳腺', '前列腺', '肾', '皮肤', '脑', '胰腺'];
    var SUBTYPES = ['腺癌', '鳞癌', '小细胞癌', '大细胞癌', '肉瘤', '淋巴瘤', '黑色素瘤', '神经内分泌', '间质瘤'];
    var NATURES = ['Normal', 'Abnormal'];

    var mock = {
        organs: function () {
            return ORGANS.map(function (o, i) {
                return { name: o, value: Math.round(rand(40, 320) - i * 12) };
            }).filter(function (o) { return o.value > 0; });
        },
        organLabels: function () { return ORGANS.slice(0, 8); },
        subtypeLabels: function () { return SUBTYPES.slice(0, 7); },
        trend: function (days, base, amp) {
            days = days || 30; base = base || 100; amp = amp || 30;
            var arr = [];
            for (var i = 0; i < days; i++) {
                arr.push(Math.round(base + Math.sin(i / 3) * amp * 0.6 + rand(-amp * 0.4, amp * 0.4) + i * 0.5));
            }
            return arr;
        },
        labels: function (days, suffix) {
            days = days || 30; suffix = suffix || '日';
            return Array.from({ length: days }, function (_, i) { return (i + 1) + suffix; });
        },
        nature: function () {
            var n = randInt(120, 260);
            var abnormal = Math.round(n * rand(0.28, 0.52));
            return [
                { name: 'Normal', value: n - abnormal },
                { name: 'Abnormal', value: abnormal }
            ];
        },
        subtype: function () {
            return SUBTYPES.slice(0, 7).map(function (s) {
                return { name: s, value: randInt(10, 95) };
            });
        },
        cells: function () {
            return ['肿瘤细胞', '炎症细胞', '上皮细胞', '软组织细胞', '坏死细胞'].map(function (c) {
                return { name: c, value: randInt(20, 280) };
            });
        }
    };

    // ---------- 通用图表快速构建 ----------
    var builders = {
        // 折线 + 渐变填充
        line: function (id, labels, datasets) {
            return makeChart('line', id, {
                labels: labels,
                datasets: datasets.map(function (d, i) {
                    return {
                        label: d.label,
                        data: d.data,
                        borderColor: d.color || PALETTE[i],
                        backgroundColor: hexToRgba(d.color || PALETTE[i], 0.15),
                        fill: d.fill !== false,
                        tension: 0.35,
                        pointRadius: 0,
                        pointHoverRadius: 5,
                        borderWidth: 2
                    };
                })
            });
        },
        bar: function (id, labels, datasets, opts) {
            return makeChart('bar', id, {
                labels: labels,
                datasets: datasets.map(function (d, i) {
                    return {
                        label: d.label,
                        data: d.data,
                        backgroundColor: d.color || PALETTE[i],
                        borderRadius: 6,
                        borderSkipped: false
                    };
                })
            }, opts);
        },
        doughnut: function (id, labels, values, colors) {
            return makeChart('doughnut', id, {
                labels: labels,
                datasets: [{
                    data: values,
                    backgroundColor: colors || PALETTE.slice(0, labels.length),
                    borderWidth: 0,
                    hoverOffset: 6
                }]
            }, {
                cutout: '62%',
                plugins: { legend: darkLegend({ position: 'right' }) }
            });
        },
        pie: function (id, labels, values, colors) {
            return makeChart('pie', id, {
                labels: labels,
                datasets: [{
                    data: values,
                    backgroundColor: colors || PALETTE.slice(0, labels.length),
                    borderWidth: 0,
                    hoverOffset: 6
                }]
            }, { plugins: { legend: darkLegend({ position: 'right' }) } });
        },
        radar: function (id, labels, datasets) {
            return makeChart('radar', id, {
                labels: labels,
                datasets: datasets.map(function (d, i) {
                    return {
                        label: d.label,
                        data: d.data,
                        backgroundColor: hexToRgba(d.color || PALETTE[i], 0.18),
                        borderColor: d.color || PALETTE[i],
                        borderWidth: 2,
                        pointBackgroundColor: d.color || PALETTE[i],
                        pointRadius: 3,
                        pointBorderColor: 'transparent'
                    };
                })
            }, {
                scales: {
                    r: {
                        beginAtZero: true,
                        ticks: { display: false, backdropColor: 'transparent' },
                        pointLabels: { font: { size: 10 }, color: '#94a3b8' },
                        grid: { color: 'rgba(255,255,255,0.08)' },
                        angleLines: { color: 'rgba(255,255,255,0.08)' }
                    }
                }
            });
        }
    };

    function hexToRgba(hex, alpha) {
        var h = hex.replace('#', '');
        if (h.length === 3) h = h.split('').map(function (c) { return c + c; }).join('');
        var r = parseInt(h.substr(0, 2), 16);
        var g = parseInt(h.substr(2, 2), 16);
        var b = parseInt(h.substr(4, 2), 16);
        return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
    }

    // ---------- 环形进度（非 Chart.js，纯 DOM） ----------
    function ringProgress(id, percent, color, label) {
        var el = document.getElementById(id);
        if (!el) return;
        color = color || COLORS.teal;
        var size = 130, stroke = 10, r = (size - stroke) / 2, c = 2 * Math.PI * r;
        var offset = c * (1 - percent / 100);
        el.innerHTML =
            '<svg width="' + size + '" height="' + size + '" style="transform:rotate(-90deg)">' +
            '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r + '" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="' + stroke + '"/>' +
            '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r + '" fill="none" stroke="' + color + '" stroke-width="' + stroke + '"' +
            ' stroke-dasharray="' + c + '" stroke-dashoffset="' + offset + '" stroke-linecap="round"' +
            ' style="transition:stroke-dashoffset 1.2s cubic-bezier(.22,.61,.36,1);filter:drop-shadow(0 0 6px ' + color + ')"/>' +
            '</svg>' +
            '<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;">' +
            '<div style="font-size:24px;font-weight:800;color:#f1f5f9;">' + percent + '<span style="font-size:13px;color:#94a3b8;">%</span></div>' +
            '<div style="font-size:10px;color:#64748b;margin-top:2px;">' + (label || '') + '</div>' +
            '</div>';
        el.style.position = 'relative';
        el.style.width = size + 'px';
        el.style.height = size + 'px';
        el.style.margin = '0 auto';
    }

    // ============================================================
    //  竞赛大屏增强组件（v2）——仪表盘/热力/桑基/树图/节点图/词云…
    // ============================================================

    function elById(id) { return document.getElementById(id); }
    function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
    function sum(arr, f) { return arr.reduce(function (s, x) { return s + (f ? f(x) : x); }, 0); }

    // ---------- SVG 半圆仪表盘（带刻度+指针） ----------
    function gauge(id, value, opts) {
        var el = elById(id); if (!el) return;
        opts = opts || {};
        var max = opts.max || 100, pct = clamp(value / max, 0, 1);
        var color = opts.color || (pct < 0.6 ? COLORS.amber : COLORS.teal);
        var L = Math.PI * 80, off = L * (1 - pct), angle = 180 - pct * 180;
        var ticks = '';
        for (var i = 0; i <= 10; i++) {
            var a = Math.PI - i / 10 * Math.PI;
            var r1 = 92, r2 = i % 5 === 0 ? 84 : 88;
            ticks += '<line x1="' + (100 + r1 * Math.cos(a)) + '" y1="' + (110 - r1 * Math.sin(a)) +
                '" x2="' + (100 + r2 * Math.cos(a)) + '" y2="' + (110 - r2 * Math.sin(a)) +
                '" stroke="' + (i % 5 === 0 ? '#7dd3fc' : 'rgba(125,211,252,0.35)') + '" stroke-width="' + (i % 5 === 0 ? 1.6 : 1) + '"/>';
        }
        el.className = (el.className || '') + ' viz-gauge';
        el.innerHTML =
            '<svg viewBox="0 0 200 132" style="width:100%;max-width:264px;">' +
            '<defs><linearGradient id="g-' + id + '" x1="0" y1="0" x2="1" y2="0">' +
            '<stop offset="0" stop-color="#0ea5e9"/><stop offset="0.55" stop-color="#22d3ee"/><stop offset="1" stop-color="' + color + '"/></linearGradient></defs>' +
            ticks +
            '<path d="M20 110 A80 80 0 0 1 180 110" fill="none" stroke="rgba(255,255,255,0.10)" stroke-width="9" stroke-linecap="round"/>' +
            '<path d="M20 110 A80 80 0 0 1 180 110" fill="none" stroke="url(#g-' + id + ')" stroke-width="9" stroke-linecap="round" ' +
            'stroke-dasharray="' + L + '" stroke-dashoffset="' + off + '" style="filter:drop-shadow(0 0 5px ' + hexToRgba(color, 0.9) + ')"/>' +
            '<line x1="100" y1="110" x2="100" y2="40" stroke="#f1f5f9" stroke-width="2.4" stroke-linecap="round" ' +
            'transform="rotate(' + angle + ' 100 110)" style="filter:drop-shadow(0 0 4px rgba(34,211,238,.8))"/>' +
            '<circle cx="100" cy="110" r="5.5" fill="#0b1526" stroke="' + color + '" stroke-width="2.5"/>' +
            '<text x="100" y="92" text-anchor="middle" fill="#f1f5f9" font-size="23" font-weight="800">' +
            (opts.display !== undefined ? opts.display : value) + (opts.unit || '') + '</text>' +
            '<text x="100" y="128" text-anchor="middle" fill="#64748b" font-size="8.5">' + (opts.label || '') + '</text>' +
            '<text x="18" y="126" text-anchor="middle" fill="#475569" font-size="8" font-family="monospace">0</text>' +
            '<text x="100" y="24" text-anchor="middle" fill="#64748b" font-size="8" font-family="monospace">50</text>' +
            '<text x="182" y="126" text-anchor="middle" fill="#475569" font-size="8" font-family="monospace">100</text>' +
            '</svg>';
    }

    // ---------- 极坐标面积图 ----------
    function polar(id, labels, values, colors) {
        return makeChart('polarArea', id, {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: (colors || PALETTE).slice(0, labels.length).map(function (c) { return hexToRgba(c, 0.55); }),
                borderColor: (colors || PALETTE).slice(0, labels.length),
                borderWidth: 1.4
            }]
        }, {
            scales: { r: { ticks: { display: false, backdropColor: 'transparent', color: '#475569' }, grid: { color: 'rgba(255,255,255,0.07)' }, angleLines: { color: 'rgba(255,255,255,0.07)' }, pointLabels: { color: '#94a3b8', font: { size: 9 } } } },
            plugins: { legend: darkLegend({ display: false }), tooltip: darkTooltip() }
        });
    }

    // ---------- 气泡散点 ----------
    function bubble(id, points, opts) {
        opts = opts || {};
        return makeChart('bubble', id, {
            datasets: (points.datasets || [{ label: opts.label || '', data: points, color: COLORS.cyan }]).map(function (s) {
                return {
                    label: s.label,
                    data: s.data,
                    backgroundColor: hexToRgba(s.color || COLORS.cyan, 0.5),
                    borderColor: s.color || COLORS.cyan,
                    borderWidth: 1.5
                };
            })
        }, {
            plugins: { legend: darkLegend({ display: !!points.datasets }) },
            scales: darkScales(opts.scales || {})
        });
    }

    // ---------- 热力矩阵（DOM） ----------
    function heatmap(id, opts) {
        var el = elById(id); if (!el) return;
        var rows = opts.rowLabels || [], cols = opts.colLabels || [], m = opts.matrix;
        var max = 1, min = 0;
        if (opts.raw !== false) { max = -Infinity; m.forEach(function (r) { r.forEach(function (v) { if (v > max) max = v; }); }); }
        var base = opts.color || COLORS.teal;
        var html = '<div class="viz-hm"><div class="viz-hm-y"></div><div class="viz-hm-body">';
        html += '<div class="viz-hm-x">' + cols.map(function (c) { return '<span>' + c + '</span>'; }).join('') + '</div>';
        m.forEach(function (row, ri) {
            html += '<div class="viz-hm-row">' + row.map(function (v) {
                var t = max === 0 ? 0 : clamp((v - min) / max, 0, 1);
                var glow = t > 0.78 ? 'box-shadow:0 0 10px ' + hexToRgba(base, 0.7) + ';' : '';
                return '<i title="' + rows[ri] + ' · ' + (cols[row.indexOf && row.indexOf(v)] || '') + '：' + v + '" style="background:' + hexToRgba(base, 0.06 + t * 0.9) + ';' + glow + '"></i>';
            }).join('') + '</div>';
        });
        html += '</div></div>';
        // 行标签注入
        var labels = rows.map(function (r, i) { return '<span>' + r + '</span>'; }).join('');
        el.innerHTML = html;
        var y = el.querySelector('.viz-hm-y');
        y.innerHTML = labels;
    }

    // ---------- 日历热力（DOM） ----------
    function calendar(id, values, opts) {
        var el = elById(id); if (!el) return;
        opts = opts || {};
        var data = values || [];
        for (var i = data.length; i < 35; i++) data.push(Math.random());
        var lvl = ['rgba(148,163,184,0.12)', hexToRgba(COLORS.cyan, 0.3), hexToRgba(COLORS.cyan, 0.55), hexToRgba(COLORS.teal, 0.75), hexToRgba(COLORS.teal, 1)];
        el.className = (el.className || '') + ' viz-cal';
        el.innerHTML = data.slice(0, 35).map(function (v) {
            var lv = v < 0.15 ? 0 : v < 0.35 ? 1 : v < 0.6 ? 2 : v < 0.82 ? 3 : 4;
            return '<i class="l' + lv + '" style="background:' + lvl[lv] + '" title="活跃度 ' + Math.round(v * 100) + '%"></i>';
        }).join('');
    }

    // ---------- Treemap 矩形树图（递归切分布局） ----------
    function treemap(id, items) {
        var el = elById(id); if (!el) return;
        var data = items.map(function (d, i) {
            return { name: d.name, value: Math.max(d.value, 0.001), color: d.color || PALETTE[i % PALETTE.length] };
        }).sort(function (a, b) { return b.value - a.value; });
        el.className = (el.className || '') + ' viz-treemap';
        el.innerHTML = '';
        function s(list) { return sum(list, function (d) { return d.value; }); }
        function block(list, x, y, w, h, depth) {
            var top = list[0];
            var d = document.createElement('div');
            d.className = 'tm-block';
            d.style.cssText = 'left:' + x + '%;top:' + y + '%;width:' + w + '%;height:' + h + '%;background:' + hexToRgba(top.color, 0.22 + (4 - depth) * 0.12) + ';border:1px solid ' + hexToRgba(top.color, 0.55) + ';';
            var inner = '<b>' + top.name + '</b>';
            if (w > 22 && h > 30) inner += '<em>' + (top.value >= 10 ? Math.round(top.value) : (Math.round(top.value * 10) / 10)) + '</em>';
            if (list.length > 1) inner += '<small>+' + (list.length - 1) + '</small>';
            d.innerHTML = inner;
            el.appendChild(d);
        }
        (function cut(list, x, y, w, h, depth) {
            if (list.length === 1 || depth >= 3) { block(list, x, y, w, h, depth); return; }
            var T = s(list), acc = 0, bi = 0, bd = 1e18;
            for (var i = 0; i < list.length - 1; i++) {
                acc += list[i].value;
                var df = Math.abs(acc - (T - acc));
                if (df < bd) { bd = df; bi = i; }
            }
            var a = list.slice(0, bi + 1), b = list.slice(bi + 1), ra = s(a) / T;
            if (w >= h) {
                var aw = w * ra;
                cut(a, x, y, aw, h, depth + 1); cut(b, x + aw, y, w - aw, h, depth + 1);
            } else {
                var hh = h * ra;
                cut(a, x, y, w, hh, depth + 1); cut(b, x, y + hh, w, h - hh, depth + 1);
            }
        })(data, 0, 0, 100, 100, 0);
    }

    // ---------- 词云（DOM） ----------
    function wordCloud(id, words) {
        var el = elById(id); if (!el) return;
        el.className = (el.className || '') + ' viz-cloud';
        el.innerHTML = words.map(function (w, i) {
            var c = w.color || PALETTE[i % PALETTE.length];
            var rot = i % 5 === 0 ? 'rotate(-8deg)' : (i % 7 === 0 ? 'rotate(6deg)' : 'none');
            return '<span style="font-size:' + (w.size || 14) + 'px;color:' + c + ';transform:' + rot + ';text-shadow:0 0 12px' + hexToRgba(c, 0.45) + '">' + w.text + '</span>';
        }).join('');
    }

    // ---------- 桑基流程图（SVG，自动链路） ----------
    function sankey(id, stages, opts) {
        var el = elById(id); if (!el) return;
        opts = opts || {};
        var W = 920, H = opts.height || 250;
        var n = stages.length, colW = 18, padL = 86, padR = 92;
        var gap = (W - padL - padR - colW * n) / (n - 1);
        var maxSum = 0;
        stages.forEach(function (st) { var t = sum(st.nodes, function (d) { return d.value; }); if (t > maxSum) maxSum = t; });
        var pos = [];
        stages.forEach(function (st, k) {
            var usable = H - 34, nodes = st.nodes;
            var raw = nodes.map(function (d) { return Math.max(d.value / maxSum * usable, 16); });
            var g = nodes.length > 1 ? 9 : 0, tot = sum(raw) + g * (nodes.length - 1);
            var y = 18 + (usable - tot) / 2 + 8;
            pos[k] = nodes.map(function (d, j) {
                var hgt = raw[j], p = { x: padL + k * (colW + gap), y: y, h: hgt, d: d };
                y += hgt + g; return p;
            });
        });
        var svg = '<svg width="100%" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" style="display:block"><defs>';
        pos.forEach(function (col, k) {
            if (k === pos.length - 1) return;
            col.forEach(function (a, i) {
                pos[k + 1].forEach(function (b, j) {
                    svg += '<linearGradient id="lk' + k + '-' + i + j + '" x1="0" y1="0" x2="1" y2="0">' +
                        '<stop offset="0" stop-color="' + (a.d.color || PALETTE[k % PALETTE.length]) + '"/>' +
                        '<stop offset="1" stop-color="' + (b.d.color || PALETTE[(k + 1) % PALETTE.length]) + '"/></linearGradient>';
                });
            });
        });
        svg += '</defs>';
        // links
        for (var k = 0; k < pos.length - 1; k++) {
            pos[k].forEach(function (a, i) {
                pos[k + 1].forEach(function (b, j) {
                    var v = Math.min(a.d.value, b.d.value);
                    var sw = clamp(v / maxSum * 46, 1.2, 15);
                    var y0 = a.y + a.h / 2, y1 = b.y + b.h / 2, x0 = a.x + colW, x1 = b.x;
                    svg += '<path d="M' + x0 + ' ' + y0 + ' C' + (x0 + gap * 0.5) + ' ' + y0 + ' ' + (x1 - gap * 0.5) + ' ' + y1 + ' ' + x1 + ' ' + y1 +
                        '" fill="none" stroke="url(#lk' + k + '-' + i + j + ')" stroke-width="' + sw + '" opacity="0.32"/>';
                });
            });
        }
        // nodes + labels
        pos.forEach(function (col, k) {
            col.forEach(function (p, j) {
                var c = p.d.color || PALETTE[k % PALETTE.length];
                svg += '<rect x="' + p.x + '" y="' + p.y + '" width="' + colW + '" height="' + p.h + '" rx="3" fill="' + hexToRgba(c, 0.85) + '" style="filter:drop-shadow(0 0 5px' + hexToRgba(c, 0.7) + ')"/>';
                var first = k === 0, last = k === pos.length - 1;
                if (first || last) {
                    svg += '<text x="' + (first ? p.x - 5 : p.x + colW + 5) + '" y="' + (p.y + p.h / 2 + 3) +
                        '" text-anchor="' + (first ? 'end' : 'start') + '" fill="#cbd5e1" font-size="9.5">' + p.d.name + '</text>';
                }
            });
            svg += '<text x="' + (col[0].x + colW / 2) + '" y="12" text-anchor="middle" fill="#67e8f9" font-size="9" font-weight="700" letter-spacing="1">' + stages[k].name + '</text>';
        });
        svg += '</svg>';
        el.innerHTML = svg;
    }

    // ---------- GCN 节点关系图（SVG 环形布局） ----------
    function nodeGraph(id, nodes, edges) {
        var el = elById(id); if (!el) return;
        var W = el.clientWidth || 300, H = 200, cx = W / 2, cy = H / 2 + 4, R = Math.min(W, H * 2) * 0.34;
        var p = nodes.map(function (d, i) {
            var a = -Math.PI / 2 + i / nodes.length * Math.PI * 2;
            return { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a) * 0.82, d: d };
        });
        var svg = '<svg width="100%" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet">';
        svg += '<ellipse cx="' + cx + '" cy="' + cy + '" rx="' + R + '" ry="' + R * 0.82 + '" fill="none" stroke="rgba(103,232,249,0.15)" stroke-dasharray="3 5"/>';
        edges.forEach(function (e) {
            var a = p[e[0]], b = p[e[1]], w = e[2] || 0.4;
            svg += '<line x1="' + a.x + '" y1="' + a.y + '" x2="' + b.x + '" y2="' + b.y + '" stroke="rgba(56,189,248,' + (0.15 + w * 0.5) + ')" stroke-width="' + (0.7 + w * 2) + '"/>';
        });
        p.forEach(function (pt, i) {
            var d = pt.d, r = 7 + (d.value || 0.5) * 9, c = d.color || PALETTE[i % PALETTE.length];
            svg += '<circle cx="' + pt.x + '" cy="' + pt.y + '" r="' + r + '" fill="' + hexToRgba(c, 0.3) + '" stroke="' + c + '" stroke-width="1.6" style="filter:drop-shadow(0 0 6px' + hexToRgba(c, 0.8) + ')"/>';
            var ly = pt.y - r - 4;
            svg += '<text x="' + pt.x + '" y="' + ly + '" text-anchor="middle" fill="#cbd5e1" font-size="8.5">' + d.label + '</text>';
        });
        svg += '</svg>';
        el.innerHTML = svg;
    }

    // ---------- 水波球（SVG + SMIL） ----------
    function waterBall(id, percent, label, color) {
        var el = elById(id); if (!el) return;
        color = color || COLORS.cyan;
        el.className = (el.className || '') + ' viz-water';
        el.innerHTML =
            '<svg viewBox="0 0 120 120" width="130" height="130">' +
            '<defs><clipPath id="w-' + id + '"><circle cx="60" cy="60" r="48"/></clipPath>' +
            '<linearGradient id="wg-' + id + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="' + color + '"/><stop offset="1" stop-color="#0ea5e9"/></linearGradient></defs>' +
            '<circle cx="60" cy="60" r="48" fill="rgba(255,255,255,0.03)" stroke="' + hexToRgba(color, 0.6) + '" stroke-width="2"/>' +
            '<g clip-path="url(#w-' + id + ')">' +
            '<rect x="0" y="' + (108 - percent * 0.48) + '" width="120" height="60" fill="url(#wg-' + id + ')" opacity="0.55">' +
            '<animate attributeName="y" values="' + (108 - percent * 0.48 - 2) + ';' + (108 - percent * 0.48 + 2) + ';' + (108 - percent * 0.48 - 2) + '" dur="3.6s" repeatCount="indefinite"/></rect>' +
            '<path d="M-20 100 q15 -8 30 0 t30 0 t30 0 t30 0 t30 0 v40 h-150 Z" fill="' + color + '" opacity="0.35">' +
            '<animateTransform attributeName="transform" type="translate" from="0 0" to="30 0" dur="2.8s" repeatCount="indefinite"/></path>' +
            '</g>' +
            '<text x="60" y="58" text-anchor="middle" fill="#f1f5f9" font-size="20" font-weight="800">' + percent + '%</text>' +
            '<text x="60" y="74" text-anchor="middle" fill="#94a3b8" font-size="9">' + (label || '') + '</text></svg>';
    }

    // ---------- 迷你 sparkline ----------
    function sparkline(canvasId, values, color) {
        var el = elById(canvasId); if (!el) return null;
        return new Chart(el.getContext('2d'), {
            type: 'line',
            data: { labels: values.map(function (_, i) { return i; }), datasets: [{
                data: values, borderColor: color || COLORS.teal, borderWidth: 1.6,
                backgroundColor: hexToRgba(color || COLORS.teal, 0.18), fill: true, tension: 0.4, pointRadius: 0
            }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { enabled: false } },
                scales: { x: { display: false }, y: { display: false } }, animation: { duration: 600 } }
        });
    }

    // ---------- 带 sparkline 的 KPI 卡 ----------
    function sparkKpi(id, cfg) {
        var el = elById(id); if (!el) return;
        var c = cfg.color || COLORS.teal, up = cfg.delta >= 0;
        el.className = (el.className || '') + ' viz-spark-card';
        el.style.borderColor = hexToRgba(c, 0.28);
        el.innerHTML =
            '<div class="sk-top"><span class="sk-ic" style="background:' + hexToRgba(c, 0.16) + ';color:' + c + '">' + (cfg.icon || '◆') + '</span>' +
            '<span class="sk-delta ' + (up ? 'up' : 'down') + '">' + (up ? '▲' : '▼') + ' ' + Math.abs(cfg.delta) + '%</span></div>' +
            '<div class="sk-val" style="text-shadow:0 0 16px' + hexToRgba(c, 0.5) + '">' + cfg.value + '<i>' + (cfg.unit || '') + '</i></div>' +
            '<div class="sk-lbl">' + cfg.label + '</div>' +
            '<div class="sk-spark"><canvas id="' + id + '-spark"></canvas></div>';
        sparkline(id + '-spark', cfg.spark || mock.trend(14, 80, 18), c);
    }

    // ---------- 排行榜 ----------
    function rankList(id, items, opts) {
        var el = elById(id); if (!el) return;
        opts = opts || {};
        var max = Math.max.apply(null, items.map(function (d) { return d.value; }));
        var medal = [COLORS.amber, '#cbd5e1', COLORS.orange];
        el.className = (el.className || '') + ' viz-rank';
        el.innerHTML = items.map(function (d, i) {
            var c = i < 3 ? medal[i] : '#475569';
            return '<div class="rk-row"><span class="rk-idx" style="color:' + c + ';border-color:' + hexToRgba(c, 0.5) + '">' + (i + 1) + '</span>' +
                '<span class="rk-name">' + d.name + '</span>' +
                '<span class="rk-track"><span style="width:' + Math.round(d.value / max * 100) + '%;background:linear-gradient(90deg,' + hexToRgba(c, 0.5) + ',' + c + ')"></span></span>' +
                '<span class="rk-val">' + (opts.percent ? d.value + '%' : d.value) + '</span></div>';
        }).join('');
    }

    // ---------- 实时事件流 ----------
    function eventStream(id, events) {
        var el = elById(id); if (!el) return;
        el.className = (el.className || '') + ' viz-stream';
        var lc = { info: COLORS.cyan, ok: COLORS.green, warn: COLORS.amber, ai: COLORS.purple };
        el.innerHTML = events.map(function (e) {
            var c = lc[e.level] || COLORS.cyan;
            return '<div class="st-row"><span class="st-lamp" style="background:' + c + ';box-shadow:0 0 8px' + c + '"></span>' +
                '<span class="st-time">' + e.time + '</span><span class="st-text" style="color:' + (e.level === 'warn' ? '#fcd34d' : '#cbd5e1') + '">' + e.text + '</span></div>';
        }).join('');
    }

    // ---------- 检测图画廊（HUD 标注框） ----------
    function gallery(id, images) {
        var el = elById(id); if (!el) return;
        el.className = (el.className || '') + ' viz-gallery';
        el.innerHTML = images.map(function (im, i) {
            var c = im.color || PALETTE[i % PALETTE.length];
            return '<figure class="hud-frame" style="border-color:' + hexToRgba(c, 0.5) + '">' +
                '<span class="hf-c hf-tl" style="border-color:' + c + '"></span><span class="hf-c hf-tr" style="border-color:' + c + '"></span>' +
                '<span class="hf-c hf-bl" style="border-color:' + c + '"></span><span class="hf-c hf-br" style="border-color:' + c + '"></span>' +
                '<span class="hf-scan"></span><img src="' + im.src + '" alt="' + im.title + '" loading="lazy"/>' +
                '<figcaption><b>' + im.title + '</b><span class="hf-chip" style="color:' + c + ';border-color:' + hexToRgba(c, 0.6) + ';background:' + hexToRgba(c, 0.12) + '">' + (im.tag || '') + '</span></figcaption>' +
                '</figure>';
        }).join('');
    }

    // ---------- 暴露 ----------
    global.PathoViz = {
        COLORS: COLORS,
        PALETTE: PALETTE,
        makeChart: makeChart,
        darkOptions: darkOptions,
        darkScales: darkScales,
        darkLegend: darkLegend,
        darkTooltip: darkTooltip,
        makeGradient: makeGradient,
        ringProgress: ringProgress,
        builders: builders,
        gauge: gauge,
        polar: polar,
        bubble: bubble,
        heatmap: heatmap,
        calendar: calendar,
        treemap: treemap,
        wordCloud: wordCloud,
        sankey: sankey,
        nodeGraph: nodeGraph,
        waterBall: waterBall,
        sparkline: sparkline,
        sparkKpi: sparkKpi,
        rankList: rankList,
        eventStream: eventStream,
        gallery: gallery,
        mock: mock,
        hexToRgba: hexToRgba,
        ORGANS: ORGANS,
        SUBTYPES: SUBTYPES
    };

    // 自动给已有 Chart 实例注入深色主题（对 dashboard 等已有图表无害，仅兜底）
    if (global.Chart) {
        Chart.defaults.color = '#94a3b8';
        Chart.defaults.font.family = '-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif';
        Chart.defaults.font.size = 11;
    }
})(window);
