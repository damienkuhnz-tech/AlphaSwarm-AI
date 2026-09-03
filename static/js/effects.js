
  // ── AlphaSwarm - FX 3D "essaim" (lancement / complétion d'agent) ──────────
  // Un SEUL canvas WebGL global, lazy-loadé au premier lancement (three.js
  // chargé dynamiquement depuis /vendor/three/). Purement décoratif : toute
  // erreur est avalée, le verrou agentRunning / refreshLaunchButtons reste
  // l'unique source de vérité. prefers-reduced-motion → aucun FX (le pulse
  // CSS du badge existant est conservé).
  var SwarmFX = (function () {
    var THREE_URL = '/vendor/three/three.min.js';
    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var state = null, threeP = null, running = false, rafId = 0, anims = [];
    var MAXP = 900; // particules max simultanées (buffer fixe, zéro realloc)

    function loadThree() {
      if (window.THREE) return Promise.resolve();
      if (threeP) return threeP;
      threeP = new Promise(function (res, rej) {
        var s = document.createElement('script');
        s.src = THREE_URL;
        s.onload = res;
        s.onerror = function () { rej(new Error('three: échec de chargement')); };
        document.head.appendChild(s);
      });
      return threeP;
    }

    function ensureScene() {
      if (state) return state;
      var canvas = document.createElement('canvas');
      canvas.id = 'swarmFxCanvas';
      canvas.style.cssText = 'position:fixed;inset:0;z-index:9998;pointer-events:none;display:none;';
      document.body.appendChild(canvas);
      var renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: false });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(innerWidth, innerHeight);
      // Caméra orthographique mappée 1:1 sur les pixels écran (y vers le bas)
      var camera = new THREE.OrthographicCamera(0, innerWidth, 0, innerHeight, -10, 10);
      var scene = new THREE.Scene();
      var geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(MAXP * 3), 3));
      var mat = new THREE.PointsMaterial({
        size: 3.2, color: 0x117B54, transparent: true, opacity: 0.95,
        depthWrite: false, blending: THREE.AdditiveBlending
      });
      var points = new THREE.Points(geo, mat);
      points.frustumCulled = false;
      scene.add(points);
      window.addEventListener('resize', function () {
        renderer.setSize(innerWidth, innerHeight);
        camera.right = innerWidth; camera.bottom = innerHeight;
        camera.updateProjectionMatrix();
      });
      state = { renderer: renderer, scene: scene, camera: camera, geo: geo, mat: mat, canvas: canvas };
      return state;
    }

    function center(el) {
      var r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }

    // Trajectoires : bézier quadratique origin→cible avec arc perpendiculaire
    function makeAnim(from, to, n, dur) {
      var parts = [];
      var mx = (from.x + to.x) / 2, my = (from.y + to.y) / 2;
      var dx = to.x - from.x, dy = to.y - from.y, len = Math.max(1, Math.hypot(dx, dy));
      var px = -dy / len, py = dx / len;
      for (var i = 0; i < n; i++) {
        var arc = (40 + Math.random() * 160) * ((Math.random() - 0.5) * 2);
        parts.push({
          ox: from.x + (Math.random() - 0.5) * 26, oy: from.y + (Math.random() - 0.5) * 14,
          cx: mx + px * arc, cy: my + py * arc,
          tx: to.x + (Math.random() - 0.5) * 30, ty: to.y + (Math.random() - 0.5) * 16,
          delay: Math.random() * 0.35, spin: Math.random() * Math.PI * 2
        });
      }
      return { t0: performance.now(), dur: dur, parts: parts };
    }

    function frame(now) {
      if (!running) return;
      var st = state, pos = st.geo.attributes.position.array, k = 0;
      for (var a = 0; a < anims.length; a++) {
        var an = anims[a], T = (now - an.t0) / an.dur;
        for (var i = 0; i < an.parts.length && k < MAXP; i++, k++) {
          var p = an.parts[i];
          var t = Math.min(1, Math.max(0, (T - p.delay) / (1 - p.delay)));
          var e = t * t * (3 - 2 * t), u = 1 - e;
          var wob = (1 - e) * e * 12;
          pos[k * 3]     = u * u * p.ox + 2 * u * e * p.cx + e * e * p.tx + Math.sin(now / 90 + p.spin) * wob;
          pos[k * 3 + 1] = u * u * p.oy + 2 * u * e * p.cy + e * e * p.ty + Math.cos(now / 110 + p.spin) * wob;
          pos[k * 3 + 2] = 0;
        }
      }
      for (; k < MAXP; k++) { pos[k * 3] = -9999; pos[k * 3 + 1] = -9999; }
      anims = anims.filter(function (an) { return (now - an.t0) / an.dur < 1.1; });
      st.geo.attributes.position.needsUpdate = true;
      st.renderer.render(st.scene, st.camera);
      if (anims.length) { rafId = requestAnimationFrame(frame); }
      else { running = false; st.canvas.style.display = 'none'; } // RAF au repos hors animation
    }

    function fromTo(fromEl, toEl, n, dur) {
      if (reduced || !fromEl || !toEl || document.hidden) return;
      loadThree().then(function () {
        ensureScene();
        state.canvas.style.display = 'block';
        anims.push(makeAnim(center(fromEl), center(toEl), n, dur));
        if (!running) { running = true; rafId = requestAnimationFrame(frame); }
      }).catch(function () { /* décoratif : silence */ });
    }

    return {
      // L'essaim jaillit du bouton et "part travailler" vers l'onglet de l'étape
      launch: function (stepNum) {
        fromTo(document.getElementById('launch-btn-' + stepNum),
               document.getElementById('tab-item-' + stepNum) || document.getElementById('step-badge-' + stepNum),
               620, 2000);
      },
      // Fin de run : l'essaim revient converger sur le badge COMPLÉTÉ
      complete: function (stepNum) {
        fromTo(document.getElementById('tab-item-' + stepNum) || document.body,
               document.getElementById('step-badge-' + stepNum),
               380, 1400);
      },
      _state: function () {
        return { running: running, anims: anims.length,
                 info: state ? state.renderer.info.render : null,
                 mem: state ? state.renderer.info.memory : null };
      }
    };
  })();

  // ── Bannière statut run ──
  function showRunBanner(msg, type) {
    var banner = document.getElementById('runStatusBanner');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'runStatusBanner';
      banner.style.cssText = 'position:fixed;bottom:16px;right:16px;padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;z-index:9999;max-width:420px;';
      document.body.appendChild(banner);
    }
    var colors = { info:'#EDF1EF', success:'#E3F6EC', warn:'#FFF4DE', error:'#FBE9E7' };
    var borders = { info:'#4A6157', success:'#117B54', warn:'#B07A1E', error:'#B3261E' };
    banner.style.background = colors[type] || colors.info;
    banner.style.border = '1px solid ' + (borders[type] || borders.info);
    banner.style.color = '#1A2420';
    banner.textContent = msg;
    if (type === 'success') setTimeout(function() { banner.style.opacity='0'; }, 4000);
  }
