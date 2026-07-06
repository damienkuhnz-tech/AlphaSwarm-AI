/* ================================================================
   AlphaSwarm Landing — Hero 3D "Essaim d'agents"
   Three.js Points : vol libre organique → convergence vers le
   monogramme "A + chandeliers" → dispersion au scroll.
   Perf : 1 renderer, BufferGeometry, dpr≤2, pause hors viewport /
   onglet caché. Fallbacks : WebGL indisponible ou
   prefers-reduced-motion → monogramme statique en fondu.
   ================================================================ */
(function () {
  "use strict";

  var hero = document.querySelector(".hero-standalone");
  if (!hero) return;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Fallback statique (SVG monogramme centré, fondu) ---------- */
  function staticFallback() {
    var d = document.createElement("div");
    d.className = "swarm-fallback";
    d.setAttribute("aria-hidden", "true");
    d.style.cssText =
      "position:absolute;inset:0;display:flex;align-items:center;justify-content:center;" +
      "z-index:1;pointer-events:none;opacity:0;transition:opacity 1.2s ease;";
    d.innerHTML =
      '<svg viewBox="0 0 156 96" style="width:min(46vw,520px);opacity:.16;" fill="none">' +
      '<g stroke="#EAF5F0" stroke-linecap="square">' +
      '<path d="M14 88 L52 10 L90 88" stroke-width="12"/><path d="M32 62 H72" stroke-width="10"/></g>' +
      '<path d="M16 78 L100 26" stroke="#081310" stroke-width="7"/>' +
      '<g stroke="#3DDC97" stroke-width="2.4"><line x1="107" y1="28" x2="107" y2="88"/>' +
      '<line x1="125" y1="14" x2="125" y2="78"/><line x1="143" y1="36" x2="143" y2="90"/></g>' +
      '<g fill="#3DDC97"><rect x="102" y="42" width="10" height="28" rx="1"/>' +
      '<rect x="120" y="24" width="10" height="34" rx="1"/><rect x="138" y="50" width="10" height="24" rx="1"/></g></svg>';
    hero.appendChild(d);
    requestAnimationFrame(function () { d.style.opacity = "1"; });
  }

  function webglOK() {
    try {
      var c = document.createElement("canvas");
      return !!(window.WebGLRenderingContext &&
        (c.getContext("webgl") || c.getContext("experimental-webgl")));
    } catch (e) { return false; }
  }

  if (reduced || !window.THREE || !webglOK()) { staticFallback(); return; }

  /* ---------- Cibles : échantillonnage 2D du monogramme ---------- */
  function sampleLogoTargets(n) {
    var W = 360, H = 222, c = document.createElement("canvas");
    c.width = W; c.height = H;
    var x = c.getContext("2d");
    // Réplique du SVG (viewBox 0 0 156 96) à l'échelle ~2.3
    x.save(); x.scale(2.3, 2.3); x.translate(0, 0);
    x.strokeStyle = "#fff"; x.lineCap = "square";
    x.lineWidth = 12; x.beginPath(); x.moveTo(14, 88); x.lineTo(52, 10); x.lineTo(90, 88); x.stroke();
    x.lineWidth = 10; x.beginPath(); x.moveTo(32, 62); x.lineTo(72, 62); x.stroke();
    // slash (découpe) : on efface
    x.globalCompositeOperation = "destination-out";
    x.lineWidth = 7; x.beginPath(); x.moveTo(16, 78); x.lineTo(100, 26); x.stroke();
    x.globalCompositeOperation = "source-over";
    // chandeliers (mèches + corps)
    x.lineWidth = 2.4;
    [[107, 28, 107, 88], [125, 14, 125, 78], [143, 36, 143, 90]].forEach(function (l) {
      x.beginPath(); x.moveTo(l[0], l[1]); x.lineTo(l[2], l[3]); x.stroke();
    });
    [[102, 42, 10, 28], [120, 24, 10, 34], [138, 50, 10, 24]].forEach(function (r) {
      x.fillRect(r[0], r[1], r[2], r[3]);
    });
    x.restore();

    var data = x.getImageData(0, 0, W, H).data, pts = [];
    for (var py = 0; py < H; py += 2) {
      for (var px = 0; px < W; px += 2) {
        if (data[(py * W + px) * 4 + 3] > 128) pts.push([px, py]);
      }
    }
    // n points répartis + flag "chandelier" (px du SVG > ~100 → x canvas > 230)
    var out = new Float32Array(n * 3), isCandle = new Float32Array(n);
    var scale = 0.075; // monde ≈ 27×17 unités
    for (var i = 0; i < n; i++) {
      var p = pts[(Math.random() * pts.length) | 0];
      out[i * 3]     = (p[0] - W / 2) * scale + (Math.random() - 0.5) * 0.12;
      out[i * 3 + 1] = (H / 2 - p[1]) * scale + (Math.random() - 0.5) * 0.12;
      out[i * 3 + 2] = (Math.random() - 0.5) * 0.9;
      isCandle[i] = p[0] > 230 ? 1 : 0;
    }
    return { targets: out, isCandle: isCandle };
  }

  /* ---------- Scène ---------- */
  var N = 3200;
  var wrap = document.createElement("div");
  wrap.className = "swarm-wrap";
  wrap.setAttribute("aria-hidden", "true");
  wrap.style.cssText = "position:absolute;inset:0;z-index:1;pointer-events:none;";
  hero.insertBefore(wrap, hero.firstChild);

  var renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(hero.clientWidth, hero.clientHeight);
  wrap.appendChild(renderer.domElement);

  var scene = new THREE.Scene();
  var camera = new THREE.PerspectiveCamera(50, hero.clientWidth / hero.clientHeight, 0.1, 100);
  camera.position.z = 22;

  var logo = sampleLogoTargets(N);
  var positions = new Float32Array(N * 3);
  var colors = new Float32Array(N * 3);
  var seeds = new Float32Array(N * 4);
  var ECUME = new THREE.Color("#EAF5F0"), EMERAUDE = new THREE.Color("#3DDC97");
  for (var i = 0; i < N; i++) {
    seeds[i * 4]     = Math.random() * Math.PI * 2;
    seeds[i * 4 + 1] = 0.35 + Math.random() * 0.75;   // vitesse
    seeds[i * 4 + 2] = 6 + Math.random() * 12;         // rayon de vol
    seeds[i * 4 + 3] = Math.random() * Math.PI * 2;
    var col = logo.isCandle[i] ? EMERAUDE : (Math.random() < 0.72 ? EMERAUDE : ECUME);
    colors[i * 3] = col.r; colors[i * 3 + 1] = col.g; colors[i * 3 + 2] = col.b;
  }

  var geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  var mat = new THREE.PointsMaterial({
    size: 0.11, vertexColors: true, transparent: true, opacity: 0.9,
    depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true
  });
  scene.add(new THREE.Points(geo, mat));

  /* ---------- État d'animation ---------- */
  var formation = 0;      // 0 = vol libre, 1 = monogramme formé
  var scrollDisperse = 0; // 0 = hero plein, 1 = dispersé
  var mouse = { x: 999, y: 999 };

  // Convergence d'entrée : vol libre 1s puis morph 2.4s (easing cubic)
  var t0 = performance.now(), MORPH_START = 1000, MORPH_DUR = 2400;

  hero.addEventListener("pointermove", function (e) {
    var r = hero.getBoundingClientRect();
    // NDC → monde approx au plan z=0
    var nx = ((e.clientX - r.left) / r.width) * 2 - 1;
    var ny = -(((e.clientY - r.top) / r.height) * 2 - 1);
    var fovH = Math.tan((camera.fov * Math.PI / 180) / 2) * camera.position.z;
    mouse.x = nx * fovH * camera.aspect;
    mouse.y = ny * fovH;
  });
  hero.addEventListener("pointerleave", function () { mouse.x = 999; mouse.y = 999; });

  window.addEventListener("scroll", function () {
    scrollDisperse = Math.min(1, Math.max(0, window.scrollY / (window.innerHeight * 0.55)));
  }, { passive: true });

  function resize() {
    var w = hero.clientWidth, h = hero.clientHeight;
    camera.aspect = w / h; camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  }
  window.addEventListener("resize", resize);

  /* ---------- Boucle (pausable) ---------- */
  var running = false, rafId = 0;
  function frame(now) {
    if (!running) return;
    var t = (now - t0) / 1000;

    // formation pilotée par le temps puis réduite par le scroll
    var m = Math.min(1, Math.max(0, (now - t0 - MORPH_START) / MORPH_DUR));
    m = m * m * (3 - 2 * m); // smoothstep
    formation = m * (1 - scrollDisperse);

    var pos = geo.attributes.position.array;
    for (var i = 0; i < N; i++) {
      var s0 = seeds[i * 4], sp = seeds[i * 4 + 1], rad = seeds[i * 4 + 2], ph = seeds[i * 4 + 3];
      // vol libre : lissajous organique
      var fx = Math.sin(s0 + t * sp) * rad;
      var fy = Math.cos(ph + t * sp * 0.8) * rad * 0.55;
      var fz = Math.sin(ph + s0 + t * sp * 0.6) * 3.2;
      // dispersion au scroll : le vol s'élargit et monte
      fx *= (1 + scrollDisperse * 1.6);
      fy += scrollDisperse * 9;
      var tx = logo.targets[i * 3], ty = logo.targets[i * 3 + 1], tz = logo.targets[i * 3 + 2];
      // respiration légère une fois formé
      var br = 0.10 * Math.sin(t * 1.4 + s0 * 3);
      var x = fx + (tx + br - fx) * formation;
      var y = fy + (ty + br * 0.6 - fy) * formation;
      var z = fz + (tz - fz) * formation;
      // répulsion souris (locale, douce)
      var dx = x - mouse.x, dy = y - mouse.y, d2 = dx * dx + dy * dy;
      if (d2 < 6.25) {
        var f = (2.5 - Math.sqrt(d2)) / 2.5;
        x += dx * f * 0.9; y += dy * f * 0.9;
      }
      pos[i * 3] = x; pos[i * 3 + 1] = y; pos[i * 3 + 2] = z;
    }
    geo.attributes.position.needsUpdate = true;
    mat.opacity = 0.9 * (1 - scrollDisperse * 0.85);
    renderer.render(scene, camera);
    rafId = requestAnimationFrame(frame);
  }
  function start() { if (!running) { running = true; rafId = requestAnimationFrame(frame); } }
  function stop()  { running = false; cancelAnimationFrame(rafId); }

  // Pause : onglet caché + hero hors viewport
  document.addEventListener("visibilitychange", function () {
    document.hidden ? stop() : (heroVisible && start());
  });
  var heroVisible = true;
  new IntersectionObserver(function (entries) {
    heroVisible = entries[0].isIntersecting;
    heroVisible && !document.hidden ? start() : stop();
  }, { threshold: 0.02 }).observe(hero);

  start();

  // Exposé pour la vérification (état interne inspectable)
  window.__swarm = {
    isRunning: function () { return running; },
    particleCount: N,
    formation: function () { return formation; },
    renderer: renderer
  };
})();
