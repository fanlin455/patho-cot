/**
 * Patho-COT 3D 病理细胞场景（three.js）
 * 参考真实显微镜下 H&E 染色细胞：
 *  - 细胞膜：半透明粉色胞质 + 菲涅尔边缘膜晕 + 高光 + 噪点颗粒，顶点噪声模拟活体膜起伏
 *  - 细胞核：苏木精紫蓝、染色质纹理、偏心核、肿瘤细胞核内有核仁亮点
 *  - 细胞在组织液中缓慢漂移、自转、呼吸式缩放；可拖拽旋转 / 滚轮缩放
 */
import * as THREE from '/static/assets/vendor/three.module.js';

(function () {
  'use strict';

  var viewport = document.querySelector('.viewport');
  var canvas = document.getElementById('cellCanvas');
  if (!viewport || !canvas || !THREE) return;

  // ---------- 渲染器 / 场景 / 相机 ----------
  var renderer = new THREE.WebGLRenderer({
    canvas: canvas, alpha: true, antialias: true, preserveDrawingBuffer: true
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);

  var scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x0a0817, 0.032);

  var camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  var cam = { radius: 11.5, theta: 0.6, phi: 1.35 };
  var DEFAULT_CAM = { radius: 11.5, theta: 0.6, phi: 1.35 };
  // pan / measure 模式标志位，updateCamera 会立即用到 panOffset
  var panMode = false, measureMode = false;
  var panOffset = { x: 0, y: 0 };
  function updateCamera() {
    var p = Math.max(0.35, Math.min(2.6, cam.phi));
    var cx = panOffset.x, cy = panOffset.y, cz = 0;
    camera.position.set(
      cx + cam.radius * Math.sin(p) * Math.sin(cam.theta),
      cy + cam.radius * Math.cos(p),
      cz + cam.radius * Math.sin(p) * Math.cos(cam.theta)
    );
    camera.lookAt(cx, cy, cz);
  }
  updateCamera();

  // ---------- 光照（自定义 shader 用，也供网格材质用） ----------
  scene.add(new THREE.AmbientLight(0x8b7fc0, 0.5));
  var keyLight = new THREE.DirectionalLight(0xffe4f2, 1.4);
  keyLight.position.set(-5, 7, 6);
  scene.add(keyLight);

  // ---------- GLSL 噪声（Ashima simplex 3D） ----------
  var SNOISE = [
    'vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}',
    'vec4 mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}',
    'vec4 permute(vec4 x){return mod289(((x*34.0)+1.0)*x);}',
    'vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}',
    'float snoise(vec3 v){',
    'const vec2 C=vec2(1.0/6.0,1.0/3.0); const vec4 D=vec4(0.0,0.5,1.0,2.0);',
    'vec3 i=floor(v+dot(v,C.yyy)); vec3 x0=v-i+dot(i,C.xxx);',
    'vec3 g=step(x0.yzx,x0.xyz); vec3 l=1.0-g; vec3 i1=min(g.xyz,l.zxy); vec3 i2=max(g.xyz,l.zxy);',
    'vec3 x1=x0-i1+C.xxx; vec3 x2=x0-i2+C.yyy; vec3 x3=x0-D.yyy;',
    'i=mod289(i);',
    'vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));',
    'float n_=0.142857142857; vec3 ns=n_*D.wyz-D.xzx;',
    'vec4 j=p-49.0*floor(p*ns.z*ns.z);',
    'vec4 x_=floor(j*ns.z); vec4 y_=floor(j-7.0*x_);',
    'vec4 x=x_*ns.x+ns.yyyy; vec4 y=y_*ns.x+ns.yyyy; vec4 h=1.0-abs(x)-abs(y);',
    'vec4 b0=vec4(x.xy,y.xy); vec4 b1=vec4(x.zw,y.zw);',
    'vec4 s0=floor(b0)*2.0+1.0; vec4 s1=floor(b1)*2.0+1.0; vec4 sh=-step(h,vec4(0.0));',
    'vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy; vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;',
    'vec3 p0=vec3(a0.xy,h.x); vec3 p1=vec3(a0.zw,h.y); vec3 p2=vec3(a1.xy,h.z); vec3 p3=vec3(a1.zw,h.w);',
    'vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));',
    'p0*=norm.x; p1*=norm.y; p2*=norm.z; p3*=norm.w;',
    'vec4 m=max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0); m=m*m;',
    'return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));}'
  ].join('\n');

  var VERT = [
    'uniform float uTime; uniform float uWobble; uniform float uSeed;',
    'varying vec3 vN; varying vec3 vV; varying vec3 vP; varying float vD;',
    SNOISE,
    'void main(){',
    '  vec3 nrm = normalize(normal);',
    '  float n = snoise(nrm*1.7 + vec3(uSeed) + uTime*0.22)*0.55',
    '          + snoise(nrm*3.6 - uTime*0.15 + uSeed*2.1)*0.25',
    '          + snoise(nrm*7.0 + uTime*0.4 + uSeed)*0.12;',
    '  float disp = n * uWobble;',
    '  disp = clamp(disp, -uWobble*1.5, uWobble*1.5);',
    '  vec3 pos = position + nrm * disp;',
    '  vD = disp; vP = position;',
    '  vec4 mv = modelViewMatrix * vec4(pos,1.0);',
    '  vN = normalize(normalMatrix * nrm); vV = normalize(-mv.xyz);',
    '  gl_Position = projectionMatrix * mv;',
    '}'
  ].join('\n');

  // 细胞膜（胞质）：包裹光 + 菲涅尔膜晕 + 颗粒 + 柔高光
  var FRAG_MEMB = [
    'precision highp float;',
    'uniform float uTime; uniform float uSeed; uniform float uAlpha;',
    'uniform vec3 uCore; uniform vec3 uDeep; uniform vec3 uRim;',
    'varying vec3 vN; varying vec3 vV; varying vec3 vP; varying float vD;',
    SNOISE,
    'void main(){',
    '  vec3 N=normalize(vN); vec3 V=normalize(vV);',
    '  vec3 L=normalize(vec3(-0.45,0.62,0.75));',
    '  float ndl=dot(N,L);',
    '  float wrap=clamp((ndl+0.55)/1.5,0.0,1.0);',
    '  float gran=snoise(vP*4.5 + vec3(uSeed) + uTime*0.04)*0.5+0.5;',
    '  vec3 base=mix(uDeep,uCore,pow(wrap,0.9));',
    '  base += gran*0.05*uCore;',
    '  float fres=pow(1.0-max(dot(N,V),0.0),2.4);',
    '  base += uRim*fres*1.55;',
    '  vec3 H=normalize(L+V);',
    '  float spec=pow(max(dot(N,H),0.0),48.0)*0.55;',
    '  base += spec*vec3(1.0,0.92,0.98);',
    '  float a = uAlpha + fres*0.3 + clamp(vD,0.0,1.0)*0.05;',
    '  gl_FragColor=vec4(base, clamp(a,0.0,0.92));',
    '}'
  ].join('\n');

  // 细胞核：苏木精紫 + 染色质纹理 + 偏心高光
  var FRAG_NUC = [
    'precision highp float;',
    'uniform float uTime; uniform float uSeed;',
    'uniform vec3 uHi; uniform vec3 uLo;',
    'varying vec3 vN; varying vec3 vV; varying vec3 vP;',
    SNOISE,
    'void main(){',
    '  vec3 N=normalize(vN); vec3 V=normalize(vV);',
    '  vec3 L=normalize(vec3(-0.45,0.62,0.75));',
    '  float chr=snoise(vP*7.5+vec3(uSeed*1.7)-uTime*0.03)*0.5+0.5;',
    '  chr=smoothstep(0.15,0.95,chr);',
    '  vec3 base=mix(uLo,uHi,chr*0.8);',
    '  float wrap=clamp((dot(N,L)+0.6)/1.5,0.0,1.0);',
    '  base *= 0.65+0.55*wrap;',
    '  float fres=pow(1.0-max(dot(N,V),0.0),2.0);',
    '  base += vec3(0.45,0.3,0.8)*fres*0.6;',
    '  gl_FragColor=vec4(base,0.96);',
    '}'
  ].join('\n');

  function makeMembMat(opt) {
    return new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 }, uSeed: { value: opt.seed },
        uWobble: { value: opt.wobble }, uAlpha: { value: opt.alpha },
        uCore: { value: new THREE.Color(opt.core) },
        uDeep: { value: new THREE.Color(opt.deep) },
        uRim: { value: new THREE.Color(opt.rim) }
      },
      vertexShader: VERT, fragmentShader: FRAG_MEMB,
      transparent: true, depthWrite: false, side: THREE.FrontSide
    });
  }
  function makeNucMat(opt) {
    return new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 }, uSeed: { value: opt.seed },
        uHi: { value: new THREE.Color(opt.hi) }, uLo: { value: new THREE.Color(opt.lo) },
        uWobble: { value: 0.035 }
      },
      vertexShader: VERT, fragmentShader: FRAG_NUC,
      transparent: true, depthWrite: false
    });
  }

  // ---------- 光晕贴图 ----------
  function haloTexture(color) {
    var c = document.createElement('canvas');
    c.width = c.height = 128;
    var ctx = c.getContext('2d');
    var g = ctx.createRadialGradient(64, 64, 4, 64, 64, 62);
    g.addColorStop(0, color);
    g.addColorStop(0.35, color.replace(/[\d.]+\)$/, '0.18)'));
    g.addColorStop(1, color.replace(/[\d.]+\)$/, '0)'));
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
    var tex = new THREE.CanvasTexture(c);
    return tex;
  }
  var HALOS = {
    tumor: haloTexture('rgba(244,114,182,0.55)'),
    normal: haloTexture('rgba(249,168,212,0.4)'),
    lymph: haloTexture('rgba(196,181,253,0.5)')
  };

  var TYPES = {
    tumor: {
      core: 0xe88ab2, deep: 0x52113d, rim: 0xf472b6, alpha: 0.46,
      wobble: 0.15, nucHi: 0x8a66c8, nucLo: 0x24104c, nucR: 0.52, nucleoli: 2
    },
    normal: {
      core: 0xf0aec6, deep: 0x6b1d4b, rim: 0xf9a8d4, alpha: 0.4,
      wobble: 0.065, nucHi: 0x9878d8, nucLo: 0x2e1858, nucR: 0.34, nucleoli: 1
    },
    lymph: {
      core: 0xbcabec, deep: 0x2a1557, rim: 0xc4b5fd, alpha: 0.52,
      wobble: 0.03, nucHi: 0x7c5ec4, nucLo: 0x1a0a38, nucR: 0.62, nucleoli: 0
    }
  };

  // ---------- 构建细胞 ----------
  var root = new THREE.Group();
  root.rotation.x = -0.12;
  scene.add(root);

  var layers = { tumor: new THREE.Group(), normal: new THREE.Group(), lymph: new THREE.Group() };
  Object.keys(layers).forEach(function (k) { root.add(layers[k]); });

  var cells = [];
  var sphereGeo = new THREE.SphereGeometry(1, 48, 48);
  var nucGeo = new THREE.SphereGeometry(1, 36, 36);
  var nucleolusMat = new THREE.MeshBasicMaterial({ color: 0xf48fb8 });

  var LAYOUT = [
    // [类型, 半径档位, 分布半径, 角度]
    ['tumor', 2.35, 1.1, 0.7], ['tumor', 1.85, 3.4, 2.4], ['tumor', 2.05, 2.6, 4.4],
    ['normal', 1.35, 4.2, 1.3], ['normal', 1.2, 3.8, 3.4], ['normal', 1.45, 2.0, 5.4],
    ['normal', 1.1, 4.5, 5.9], ['normal', 1.28, 1.0, 3.9],
    ['lymph', 0.82, 4.3, 0.2], ['lymph', 0.7, 3.1, 4.9], ['lymph', 0.76, 1.6, 2.0], ['lymph', 0.66, 4.6, 2.9]
  ];

  LAYOUT.forEach(function (cfg, i) {
    var type = cfg[0], r0 = cfg[1], dist = cfg[2], ang = cfg[3];
    var def = TYPES[type];
    var seed = Math.random() * 100;

    var g = new THREE.Group();
    var anchor = new THREE.Vector3(
      Math.cos(ang) * dist + (Math.random() - 0.5) * 0.7,
      Math.sin(ang * 1.3) * dist * 0.62 + (Math.random() - 0.5) * 0.7,
      (Math.random() - 0.5) * 2.6
    );
    g.position.copy(anchor);
    g.scale.setScalar(r0);

    // 细胞膜（胞质）
    var memb = new THREE.Mesh(sphereGeo, makeMembMat({
      seed: seed, wobble: def.wobble, alpha: def.alpha,
      core: def.core, deep: def.deep, rim: def.rim
    }));
    memb.renderOrder = 10;
    g.add(memb);

    // 细胞核（偏心）
    var nucGroup = new THREE.Group();
    var off = type === 'lymph' ? 0.04 : 0.14;
    nucGroup.position.set((Math.random() - 0.5) * off, (Math.random() - 0.5) * off, (Math.random() - 0.5) * off);
    var nuc = new THREE.Mesh(nucGeo, makeNucMat({ seed: seed + 9, hi: def.nucHi, lo: def.nucLo }));
    nuc.scale.setScalar(def.nucR * (0.92 + Math.random() * 0.16));
    nuc.renderOrder = 5;
    nucGroup.add(nuc);

    // 核仁
    for (var k = 0; k < def.nucleoli; k++) {
      var ncl = new THREE.Mesh(new THREE.SphereGeometry(0.06 + Math.random() * 0.03, 12, 12), nucleolusMat);
      var u = new THREE.Vector3(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).normalize();
      ncl.position.copy(u.multiplyScalar(def.nucR * 0.55));
      nucGroup.add(ncl);
    }
    g.add(nucGroup);

    // 细胞器小点（上皮/肿瘤细胞）
    if (type !== 'lymph') {
      var nOrg = 4 + Math.floor(Math.random() * 4);
      for (var j = 0; j < nOrg; j++) {
        var om = new THREE.Mesh(
          new THREE.SphereGeometry(0.035 + Math.random() * 0.04, 10, 10),
          new THREE.MeshStandardMaterial({
            color: 0x9a7be0, roughness: 0.4, metalness: 0,
            emissive: 0x4c2f8f, emissiveIntensity: 0.35,
            transparent: true, opacity: 0.75, depthWrite: false
          })
        );
        var v = new THREE.Vector3(
          (Math.random() - 0.5) * 1.3, (Math.random() - 0.5) * 1.3, (Math.random() - 0.5) * 1.3
        );
        if (v.length() > 0.85) v.setLength(0.85);
        om.position.copy(v);
        om.renderOrder = 4;
        g.add(om);
      }
    }

    // 光晕
    var halo = new THREE.Sprite(new THREE.SpriteMaterial({
      map: HALOS[type], transparent: true, opacity: 0.5,
      blending: THREE.AdditiveBlending, depthWrite: false
    }));
    halo.scale.setScalar(3.1);
    halo.renderOrder = 1;
    g.add(halo);

    layers[type].add(g);

    cells.push({
      group: g, anchor: anchor, r0: r0,
      phase: Math.random() * Math.PI * 2,
      drift: 0.18 + Math.random() * 0.22,
      driftSpeed: 0.25 + Math.random() * 0.3,
      rot: (Math.random() - 0.5) * 0.25,
      breath: 0.55 + Math.random() * 0.4
    });
  });

  // ---------- 切片平面（3D 网格，缓慢上下移动） ----------
  function sliceTexture() {
    var c = document.createElement('canvas');
    c.width = c.height = 512;
    var ctx = c.getContext('2d');
    ctx.strokeStyle = 'rgba(56,189,248,0.5)';
    ctx.lineWidth = 1;
    for (var i = 0; i <= 512; i += 32) {
      ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, 512); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, i); ctx.lineTo(512, i); ctx.stroke();
    }
    var g = ctx.createRadialGradient(256, 256, 60, 256, 256, 256);
    g.addColorStop(0, 'rgba(45,212,191,0.18)');
    g.addColorStop(1, 'rgba(45,212,191,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 512, 512);
    return new THREE.CanvasTexture(c);
  }
  var sliceGroup = new THREE.Group();
  var slicePlane = new THREE.Mesh(
    new THREE.PlaneGeometry(11, 11),
    new THREE.MeshBasicMaterial({
      map: sliceTexture(), transparent: true, opacity: 0.5,
      blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide
    })
  );
  slicePlane.rotation.x = -Math.PI / 2;
  sliceGroup.add(slicePlane);
  // 切片外环光晕
  var ring = new THREE.Mesh(
    new THREE.RingGeometry(3.9, 4.05, 80),
    new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.5, side: THREE.DoubleSide })
  );
  ring.rotation.x = -Math.PI / 2;
  sliceGroup.add(ring);
  scene.add(sliceGroup);

  // ---------- 坐标轴（默认隐藏） ----------
  var axesGroup = new THREE.Group();
  function axisLine(dir, color) {
    var geo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), dir.clone().multiplyScalar(3.4)]);
    return new THREE.Line(geo, new THREE.LineBasicMaterial({ color: color, transparent: true, opacity: 0.7 }));
  }
  axesGroup.add(axisLine(new THREE.Vector3(1, 0, 0), 0x38bdf8));
  axesGroup.add(axisLine(new THREE.Vector3(0, 1, 0), 0x2dd4bf));
  axesGroup.add(axisLine(new THREE.Vector3(0, 0, 1), 0xfbbf24));
  axesGroup.visible = false;
  scene.add(axesGroup);

  // ---------- 交互：拖拽旋转(默认) / 平移 / 滚轮缩放 ----------
  var dragging = false, lastX = 0, lastY = 0, lastInteract = 0;
  canvas.addEventListener('pointerdown', function (e) {
    dragging = true; lastX = e.clientX; lastY = e.clientY;
    lastInteract = performance.now();
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointermove', function (e) {
    if (!dragging) return;
    if (panMode) {
      panOffset.x += (e.clientX - lastX) * 0.004;
      panOffset.y -= (e.clientY - lastY) * 0.004;
    } else {
      cam.theta -= (e.clientX - lastX) * 0.006;
      cam.phi -= (e.clientY - lastY) * 0.006;
    }
    lastX = e.clientX; lastY = e.clientY;
    lastInteract = performance.now();
    updateCamera();
  });
  window.addEventListener('pointerup', function () { dragging = false; });
  canvas.addEventListener('wheel', function (e) {
    e.preventDefault();
    cam.radius = Math.max(6.5, Math.min(20, cam.radius * (1 + e.deltaY * 0.001)));
    lastInteract = performance.now();
    updateCamera();
  }, { passive: false });

  // ---------- 控制参数 ----------
  var settings = { autoRotate: true, rotSpeed: 0.18, cellScale: 1, sliceSpeed: 0.4 };

  function resize() {
    var w = viewport.clientWidth, h = viewport.clientHeight;
    if (w === 0 || h === 0) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', resize);
  window.addEventListener('load', resize);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) setTimeout(resize, 60); });
  if (window.ResizeObserver) new ResizeObserver(resize).observe(viewport);
  resize();
  setTimeout(resize, 120);
  setTimeout(resize, 600);

  // ---------- 主循环 ----------
  var clock = new THREE.Clock();
  var visible = true;
  document.addEventListener('visibilitychange', function () { visible = !document.hidden; });

  function tick() {
    requestAnimationFrame(tick);
    if (!visible) return;
    var t = clock.getElapsedTime();

    // 静置 3 秒后恢复自动旋转
    if (settings.autoRotate && performance.now() - lastInteract > 3000) {
      root.rotation.y += settings.rotSpeed * 0.01;
    }

    cells.forEach(function (c) {
      var ph = c.phase;
      c.group.position.set(
        c.anchor.x + Math.sin(t * c.driftSpeed + ph) * c.drift,
        c.anchor.y + Math.cos(t * c.driftSpeed * 0.8 + ph * 1.3) * c.drift * 0.8,
        c.anchor.z + Math.sin(t * c.driftSpeed * 0.6 + ph * 0.7) * c.drift
      );
      c.group.rotation.y += c.rot * 0.01;
      c.group.rotation.x = Math.sin(t * 0.3 + ph) * 0.12;
      var s = c.r0 * settings.cellScale * (1 + Math.sin(t * c.breath + ph) * 0.035);
      c.group.scale.setScalar(s);
      c.group.traverse(function (o) {
        if (o.material && o.material.uniforms && o.material.uniforms.uTime) {
          o.material.uniforms.uTime.value = t;
        }
      });
    });

    sliceGroup.position.y = Math.sin(t * settings.sliceSpeed) * 0.8;
    sliceGroup.rotation.y = t * 0.03;

    renderer.render(scene, camera);
  }
  tick();

  // ---------- 对外控制接口 ----------

  function disposeMesh(m) {
    if (m.geometry && !m.geometry._shared) { try { m.geometry.dispose(); } catch(e) {} m.geometry._shared = true; }
    if (m.material) {
      if (Array.isArray(m.material)) m.material.forEach(doDisposeMat);
      else doDisposeMat(m.material);
    }
  }
  function doDisposeMat(mat) {
    try { mat.dispose(); } catch(e) {}
    if (mat.map) try { mat.map.dispose(); } catch(e) {}
  }

  function destroyCells() {
    cells.forEach(function (c) {
      c.group.traverse(function (o) {
        if (o.isMesh || o.isSprite) disposeMesh(o);
      });
      if (c.group.parent) c.group.parent.remove(c.group);
    });
    cells = [];
    ['tumor', 'normal', 'lymph'].forEach(function (k) {
      while (layers[k] && layers[k].children.length) layers[k].remove(layers[k].children[0]);
    });
  }

  function buildCells(layout) {
    layout.forEach(function (cfg, i) {
      var type = cfg[0], r0 = cfg[1], dist = cfg[2], ang = cfg[3];
      var def = TYPES[type];
      if (!def) def = TYPES.normal;
      var seed = Math.random() * 100;

      var g = new THREE.Group();
      var anchor = new THREE.Vector3(
        Math.cos(ang) * dist + (Math.random() - 0.5) * 0.7,
        Math.sin(ang * 1.3) * dist * 0.62 + (Math.random() - 0.5) * 0.7,
        (Math.random() - 0.5) * 2.6
      );
      g.position.copy(anchor);
      g.scale.setScalar(r0);

      var memb = new THREE.Mesh(sphereGeo, makeMembMat({
        seed: seed, wobble: def.wobble, alpha: def.alpha,
        core: def.core, deep: def.deep, rim: def.rim
      }));
      memb.renderOrder = 10;
      g.add(memb);

      var nucGroup = new THREE.Group();
      var off = type === 'lymph' ? 0.04 : 0.14;
      nucGroup.position.set((Math.random() - 0.5) * off, (Math.random() - 0.5) * off, (Math.random() - 0.5) * off);
      var nuc = new THREE.Mesh(nucGeo, makeNucMat({ seed: seed + 9, hi: def.nucHi, lo: def.nucLo }));
      nuc.scale.setScalar(def.nucR * (0.92 + Math.random() * 0.16));
      nuc.renderOrder = 5;
      nucGroup.add(nuc);

      for (var k = 0; k < def.nucleoli; k++) {
        var ncl = new THREE.Mesh(new THREE.SphereGeometry(0.06 + Math.random() * 0.03, 12, 12), nucleolusMat);
        var u = new THREE.Vector3(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).normalize();
        ncl.position.copy(u.multiplyScalar(def.nucR * 0.55));
        nucGroup.add(ncl);
      }
      g.add(nucGroup);

      if (type !== 'lymph') {
        var nOrg = 4 + Math.floor(Math.random() * 4);
        for (var j = 0; j < nOrg; j++) {
          var om = new THREE.Mesh(
            new THREE.SphereGeometry(0.035 + Math.random() * 0.04, 10, 10),
            new THREE.MeshStandardMaterial({
              color: 0x9a7be0, roughness: 0.4, metalness: 0,
              emissive: 0x4c2f8f, emissiveIntensity: 0.35,
              transparent: true, opacity: 0.75, depthWrite: false
            })
          );
          var v = new THREE.Vector3(
            (Math.random() - 0.5) * 1.3, (Math.random() - 0.5) * 1.3, (Math.random() - 0.5) * 1.3
          );
          if (v.length() > 0.85) v.setLength(0.85);
          om.position.copy(v);
          om.renderOrder = 4;
          g.add(om);
        }
      }

      var halo = new THREE.Sprite(new THREE.SpriteMaterial({
        map: HALOS[type], transparent: true, opacity: 0.5,
        blending: THREE.AdditiveBlending, depthWrite: false
      }));
      halo.scale.setScalar(3.1);
      halo.renderOrder = 1;
      g.add(halo);

      layers[type].add(g);
      cells.push({
        group: g, anchor: anchor, r0: r0,
        phase: Math.random() * Math.PI * 2,
        drift: 0.18 + Math.random() * 0.22,
        driftSpeed: 0.25 + Math.random() * 0.3,
        rot: (Math.random() - 0.5) * 0.25,
        breath: 0.55 + Math.random() * 0.4
      });
    });
  }

  function generateLayout(config) {
    var total = config.totalCells || 12;
    var rT = config.tumorRatio != null ? config.tumorRatio : 0.3;
    var rN = config.normalRatio != null ? config.normalRatio : 0.5;
    var rL = config.lymphRatio != null ? config.lymphRatio : Math.max(0, 1 - rT - rN);
    var nT = Math.round(total * rT), nN = Math.round(total * rN), nL = Math.max(0, total - nT - nN);
    var out = [];
    function r(min, max) { return min + Math.random() * (max - min); }
    for (var i = 0; i < nT; i++) out.push(['tumor', r(1.6, 2.6), r(0.8, 4.6), Math.random() * Math.PI * 2]);
    for (var j = 0; j < nN; j++) out.push(['normal', r(1.0, 1.6), r(1.0, 4.8), Math.random() * Math.PI * 2]);
    for (var k = 0; k < nL; k++) out.push(['lymph', r(0.55, 0.9), r(1.0, 4.8), Math.random() * Math.PI * 2]);
    return out;
  }

  function rebuild(config) {
    destroyCells();
    buildCells(generateLayout(config));
  }

  window.PathoCellScene = {
    setLayer: function (name, on) {
      if (layers[name]) layers[name].visible = on;
      if (name === 'slice') sliceGroup.visible = on;
      if (name === 'axes') axesGroup.visible = on;
    },
    setRotSpeed: function (v) { settings.rotSpeed = v; },
    setCellScale: function (v) { settings.cellScale = v; },
    setSliceSpeed: function (v) { settings.sliceSpeed = v; },
    setAutoRotate: function (on) { settings.autoRotate = on; lastInteract = performance.now(); },
    resetView: function () {
      cam = Object.assign({}, DEFAULT_CAM);
      panOffset = { x: 0, y: 0 };
      panMode = false; measureMode = false;
      canvas.style.cursor = 'grab';
      updateCamera(); lastInteract = performance.now();
    },
    screenshot: function () {
      var a = document.createElement('a');
      a.download = 'patho-cell-3d.png';
      a.href = renderer.domElement.toDataURL('image/png');
      a.click();
    },
    setPan: function (mode) {
      panMode = !!mode;
      canvas.style.cursor = panMode ? 'move' : 'grab';
      if (!panMode) { panOffset = { x: 0, y: 0 }; updateCamera(); }
    },
    isPanMode: function () { return panMode; },
    setZoom: function (step) {
      cam.radius = Math.max(6, Math.min(18, cam.radius + step));
      lastInteract = performance.now();
      updateCamera();
    },
    setMeasure: function (enable) {
      measureMode = !!enable;
      canvas.style.cursor = measureMode ? 'crosshair' : (panMode ? 'move' : 'grab');
      var ov = document.getElementById('measureOverlay');
      if (ov) ov.style.display = measureMode ? 'block' : 'none';
    },
    isMeasureMode: function () { return measureMode; },
    rebuild: rebuild,
    destroy: destroyCells,
    setSample: function (config) {
      rebuild(config);
      settings.cellScale = 1;
      lastInteract = performance.now();
    }
  };
})();
