  /* ════ MODULE DATAVIZ - composants SVG maison (aucune dépendance) ════ */
  // Échappement HTML (sécurité XSS : tout contenu issu du LLM ou des données
  // de marché passe par ici avant innerHTML). Correction d'un bug latent :
  // cette fonction était appelée par CHART.donut et renderRisk sans être définie.
  function _escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  var CHART = (function () {
    var ORANGE = '#117B54', ORANGE_LT = '#2AA172', GREEN = '#117B54', GREY = '#8B968F', RED = '#B3261E';
    var SEG_COLORS = ['#117B54','#4A6157','#2AA172','#7CCBA8','#8B968F','#0D5C3F','#A9C9B9','#153F2E','#B3261E','#5E8A78'];
    function polar(cx, cy, r, deg) { var a = (deg - 90) * Math.PI / 180; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; }
    function arcPath(cx, cy, rO, rI, s, e) {
      var large = (e - s) % 360 > 180 ? 1 : 0;
      var p1 = polar(cx, cy, rO, e), p2 = polar(cx, cy, rO, s), p3 = polar(cx, cy, rI, s), p4 = polar(cx, cy, rI, e);
      return 'M ' + p1[0].toFixed(2) + ' ' + p1[1].toFixed(2) + ' A ' + rO + ' ' + rO + ' 0 ' + large + ' 0 ' + p2[0].toFixed(2) + ' ' + p2[1].toFixed(2) +
        ' L ' + p3[0].toFixed(2) + ' ' + p3[1].toFixed(2) + ' A ' + rI + ' ' + rI + ' 0 ' + large + ' 1 ' + p4[0].toFixed(2) + ' ' + p4[1].toFixed(2) + ' Z';
    }
    function donut(segments, opts) {
      opts = opts || {};
      var size = opts.size || 168, cx = size / 2, cy = size / 2, rO = size / 2 - 6, rI = rO * 0.62;
      var total = segments.reduce(function (s, x) { return s + (x.value || 0); }, 0) || 1;
      var angle = 0, paths = '', legend = '';
      segments.forEach(function (seg, i) {
        var frac = (seg.value || 0) / total, sweep = frac * 360, col = seg.color || SEG_COLORS[i % SEG_COLORS.length];
        if (sweep > 0.4) paths += '<path d="' + arcPath(cx, cy, rO, rI, angle, angle + sweep) + '" fill="' + col + '" stroke="#FFFFFF" stroke-width="1.5" class="donut-seg"><title>' + _escapeHtml(seg.label) + ' · ' + (frac * 100).toFixed(1) + '%</title></path>';
        legend += '<div class="donut-legend-row"><span class="donut-dot" style="background:' + col + '"></span><span class="donut-legend-lbl">' + _escapeHtml(seg.label) + '</span><span class="donut-legend-val">' + (frac * 100).toFixed(1) + '%</span></div>';
        angle += sweep;
      });
      var center = opts.centerLabel ? '<text x="' + cx + '" y="' + (cy - 4) + '" text-anchor="middle" class="donut-center-val">' + opts.centerLabel + '</text><text x="' + cx + '" y="' + (cy + 14) + '" text-anchor="middle" class="donut-center-sub">' + (opts.centerSub || '') + '</text>' : '';
      return '<div class="chart-donut-wrap"><svg viewBox="0 0 ' + size + ' ' + size + '" width="' + size + '" height="' + size + '" class="chart-donut"><circle cx="' + cx + '" cy="' + cy + '" r="' + ((rO + rI) / 2) + '" fill="none" stroke="rgba(26,36,32,0.06)" stroke-width="' + (rO - rI) + '"/>' + paths + center + '</svg><div class="donut-legend">' + legend + '</div></div>';
    }
    function gauge(value, min, max, opts) {
      opts = opts || {};
      var w = opts.size || 220, h = w * 0.62, cx = w / 2, cy = h - 10, r = w / 2 - 14;
      var frac = Math.max(0, Math.min(1, (value - min) / (max - min))), startDeg = -90, valDeg = startDeg + frac * 180;
      function semiArc(fromDeg, toDeg, color, width, glow) {
        var p1 = polar(cx, cy, r, fromDeg), p2 = polar(cx, cy, r, toDeg), large = (toDeg - fromDeg) > 180 ? 1 : 0;
        return '<path d="M ' + p1[0].toFixed(2) + ' ' + p1[1].toFixed(2) + ' A ' + r + ' ' + r + ' 0 ' + large + ' 1 ' + p2[0].toFixed(2) + ' ' + p2[1].toFixed(2) + '" fill="none" stroke="' + color + '" stroke-width="' + width + '" stroke-linecap="round"' + '/>';
      }
      var tip = polar(cx, cy, r, valDeg);
      return '<div class="chart-gauge-wrap"><svg viewBox="0 0 ' + w + ' ' + h + '" width="' + w + '" height="' + h + '" class="chart-gauge"><defs><linearGradient id="gaugeGrad" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="' + ORANGE + '"/><stop offset="100%" stop-color="' + ORANGE_LT + '"/></linearGradient></defs>' + semiArc(startDeg, 90, 'rgba(26,36,32,0.08)', 12, false) + semiArc(startDeg, valDeg, 'url(#gaugeGrad)', 12, true) + '<circle cx="' + tip[0].toFixed(2) + '" cy="' + tip[1].toFixed(2) + '" r="6" fill="' + ORANGE_LT + '"/><text x="' + cx + '" y="' + (cy - 14) + '" text-anchor="middle" class="gauge-val">' + (opts.display != null ? opts.display : Math.round(value)) + '</text><text x="' + cx + '" y="' + (cy + 4) + '" text-anchor="middle" class="gauge-label">' + (opts.label || '') + '</text></svg></div>';
    }
    function sparkline(points, opts) {
      opts = opts || {};
      if (!points || points.length < 2) return '';
      var w = opts.width || 56, h = opts.height || 20, pad = 2, min = Math.min.apply(null, points), max = Math.max.apply(null, points), rng = (max - min) || 1;
      var col = opts.color || (points[points.length - 1] >= points[0] ? GREEN : RED), step = (w - pad * 2) / (points.length - 1);
      var pts = points.map(function (v, i) { return (pad + i * step).toFixed(1) + ',' + (h - pad - ((v - min) / rng) * (h - pad * 2)).toFixed(1); });
      var last = pts[pts.length - 1].split(',');
      return '<svg viewBox="0 0 ' + w + ' ' + h + '" width="' + w + '" height="' + h + '" class="chart-spark"><polyline points="' + pts.join(' ') + '" fill="none" stroke="' + col + '" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/><circle cx="' + last[0] + '" cy="' + last[1] + '" r="1.8" fill="' + col + '"/></svg>';
    }
    function perfCurve(curve, opts) {
      opts = opts || {};
      if (!curve || curve.length < 2) return '';
      var w = opts.width || 560, h = opts.height || 200, padL = 8, padR = 8, padT = 14, padB = 18;
      var ports = curve.map(function (p) { return p.port; }), benchs = curve.map(function (p) { return p.bench != null ? p.bench : p.port; });
      var allV = ports.concat(benchs), min = Math.min.apply(null, allV), max = Math.max.apply(null, allV), rng = (max - min) || 1;
      min -= rng * 0.08; max += rng * 0.08; rng = max - min;
      var iw = w - padL - padR, ih = h - padT - padB;
      var X = function (k) { return padL + (k / (curve.length - 1)) * iw; }, Y = function (v) { return padT + ih - ((v - min) / rng) * ih; };
      function line(vals) { return vals.map(function (v, k) { return X(k).toFixed(1) + ',' + Y(v).toFixed(1); }).join(' '); }
      var area = 'M ' + X(0).toFixed(1) + ' ' + Y(ports[0]).toFixed(1) + ' L ' + ports.map(function (v, k) { return X(k).toFixed(1) + ' ' + Y(v).toFixed(1); }).join(' L ') + ' L ' + X(curve.length - 1).toFixed(1) + ' ' + (padT + ih).toFixed(1) + ' L ' + X(0).toFixed(1) + ' ' + (padT + ih).toFixed(1) + ' Z';
      var grid = '';
      for (var g = 0; g <= 3; g++) { var gy = padT + (ih * g / 3); grid += '<line x1="' + padL + '" y1="' + gy.toFixed(1) + '" x2="' + (w - padR) + '" y2="' + gy.toFixed(1) + '" stroke="rgba(26,36,32,0.07)" stroke-width="1"/>'; }
      var lastX = X(curve.length - 1), lastY = Y(ports[ports.length - 1]);
      return '<svg viewBox="0 0 ' + w + ' ' + h + '" width="100%" preserveAspectRatio="none" class="chart-perf"><defs><linearGradient id="perfArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="rgba(17,123,84,0.18)"/><stop offset="100%" stop-color="rgba(17,123,84,0)"/></linearGradient><linearGradient id="perfLine" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="' + ORANGE + '"/><stop offset="100%" stop-color="' + ORANGE_LT + '"/></linearGradient></defs>' + grid + '<path d="' + area + '" fill="url(#perfArea)"/><polyline points="' + line(benchs) + '" fill="none" stroke="' + GREY + '" stroke-width="1.5" stroke-dasharray="4,3" stroke-linejoin="round"/><polyline points="' + line(ports) + '" fill="none" stroke="url(#perfLine)" stroke-width="2.4" stroke-linejoin="round"/><circle cx="' + lastX.toFixed(1) + '" cy="' + lastY.toFixed(1) + '" r="3.5" fill="' + ORANGE_LT + '"/></svg><div class="perf-legend"><span><i style="background:' + ORANGE + '"></i>Portefeuille</span><span><i style="background:' + GREY + '"></i>Benchmark</span></div>';
    }
    // ── Histogramme (distributions bootstrap / Monte Carlo) ──
    // bins = [{x: centre_classe, n: effectif}], opts: {width, height, format, marker}
    function histogram(bins, opts) {
      opts = opts || {};
      if (!bins || bins.length < 3) return '';
      var w = opts.width || 320, h = opts.height || 140, padL = 6, padB = 20, padT = 8;
      var maxN = Math.max.apply(null, bins.map(function (b) { return b.n; })) || 1;
      var iw = w - padL * 2, ih = h - padT - padB, bw = iw / bins.length;
      var bars = '';
      bins.forEach(function (b, i) {
        var bh = (b.n / maxN) * ih;
        var neg = b.x < 0;
        bars += '<rect x="' + (padL + i * bw + 0.5).toFixed(1) + '" y="' + (padT + ih - bh).toFixed(1) +
          '" width="' + Math.max(1, bw - 1.2).toFixed(1) + '" height="' + bh.toFixed(1) +
          '" rx="1" fill="' + (neg ? 'rgba(179,38,30,0.75)' : 'rgba(17,123,84,0.75)') + '">' +
          '<title>' + (opts.format ? opts.format(b.x) : b.x) + ' · ' + b.n + '</title></rect>';
      });
      // Marqueur vertical optionnel (ex: valeur observée, médiane)
      var marker = '';
      if (opts.marker != null) {
        var xs = bins.map(function (b) { return b.x; });
        var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs), rngX = (maxX - minX) || 1;
        var mx = padL + ((opts.marker - minX) / rngX) * iw;
        if (mx >= padL && mx <= w - padL) {
          marker = '<line x1="' + mx.toFixed(1) + '" y1="' + padT + '" x2="' + mx.toFixed(1) + '" y2="' + (padT + ih) +
            '" stroke="#117B54" stroke-width="1.6" stroke-dasharray="4,3"/>' +
            '<text x="' + mx.toFixed(1) + '" y="' + (padT + 2) + '" text-anchor="middle" font-size="8.5" fill="#117B54" font-family="JetBrains Mono,monospace">' + (opts.markerLabel || '') + '</text>';
        }
      }
      var fmt = opts.format || function (x) { return x; };
      var lbls = '<text x="' + padL + '" y="' + (h - 6) + '" font-size="9" fill="#5F6E66" font-family="JetBrains Mono,monospace">' + fmt(bins[0].x) + '</text>' +
        '<text x="' + (w - padL) + '" y="' + (h - 6) + '" text-anchor="end" font-size="9" fill="#5F6E66" font-family="JetBrains Mono,monospace">' + fmt(bins[bins.length - 1].x) + '</text>';
      return '<svg viewBox="0 0 ' + w + ' ' + h + '" width="100%" preserveAspectRatio="none">' + bars + marker + lbls + '</svg>';
    }
    // ── Multi-lignes datées (rolling metrics) ──
    // series = [{label, color, points: [{date, valeur}]}], opts: {height, refLine}
    function dlines(series, opts) {
      opts = opts || {};
      var w = opts.width || 560, h = opts.height || 150, padL = 8, padR = 8, padT = 12, padB = 18;
      var all = [];
      series.forEach(function (s) { (s.points || []).forEach(function (p) { all.push(p.valeur); }); });
      if (all.length < 4) return '';
      var min = Math.min.apply(null, all), max = Math.max.apply(null, all);
      if (opts.refLine != null) { min = Math.min(min, opts.refLine); max = Math.max(max, opts.refLine); }
      var rng = (max - min) || 1; min -= rng * 0.08; max += rng * 0.08; rng = max - min;
      var iw = w - padL - padR, ih = h - padT - padB;
      var Y = function (v) { return padT + ih - ((v - min) / rng) * ih; };
      var grid = '';
      for (var g = 0; g <= 3; g++) { var gy = padT + ih * g / 3; grid += '<line x1="' + padL + '" y1="' + gy.toFixed(1) + '" x2="' + (w - padR) + '" y2="' + gy.toFixed(1) + '" stroke="rgba(26,36,32,0.07)"/>'; }
      var ref = '';
      if (opts.refLine != null) ref = '<line x1="' + padL + '" y1="' + Y(opts.refLine).toFixed(1) + '" x2="' + (w - padR) + '" y2="' + Y(opts.refLine).toFixed(1) + '" stroke="rgba(26,36,32,0.25)" stroke-width="1" stroke-dasharray="3,4"/>';
      var lines = '', legend = '<div class="perf-legend">';
      series.forEach(function (s, si) {
        var pts = s.points || []; if (pts.length < 2) return;
        var step = iw / (pts.length - 1);
        var poly = pts.map(function (p, k) { return (padL + k * step).toFixed(1) + ',' + Y(p.valeur).toFixed(1); }).join(' ');
        lines += '<polyline points="' + poly + '" fill="none" stroke="' + s.color + '" stroke-width="1.8" stroke-linejoin="round"/>';
        legend += '<span><i style="background:' + s.color + '"></i>' + _escapeHtml(s.label) + '</span>';
      });
      var d0 = series[0].points, dl = '';
      if (d0 && d0.length > 1 && d0[0].date) {
        dl = '<text x="' + padL + '" y="' + (h - 4) + '" font-size="9" fill="#5F6E66" font-family="JetBrains Mono,monospace">' + d0[0].date + '</text>' +
          '<text x="' + (w - padR) + '" y="' + (h - 4) + '" text-anchor="end" font-size="9" fill="#5F6E66" font-family="JetBrains Mono,monospace">' + d0[d0.length - 1].date + '</text>';
      }
      return '<svg viewBox="0 0 ' + w + ' ' + h + '" width="100%" preserveAspectRatio="none">' + grid + ref + lines + dl + '</svg>' + legend + '</div>';
    }
    // ── Fan chart Monte Carlo (percentiles p5/p25/p50/p75/p95, base 100) ──
    function fanChart(fc, opts) {
      opts = opts || {};
      if (!fc || !fc.p50 || fc.p50.length < 4) return '';
      var w = opts.width || 560, h = opts.height || 190, padL = 8, padR = 8, padT = 12, padB = 18;
      var all = fc.p5.concat(fc.p95);
      var min = Math.min.apply(null, all), max = Math.max.apply(null, all), rng = (max - min) || 1;
      min -= rng * 0.06; max += rng * 0.06; rng = max - min;
      var n = fc.p50.length, iw = w - padL - padR, ih = h - padT - padB;
      var X = function (k) { return padL + (k / (n - 1)) * iw; }, Y = function (v) { return padT + ih - ((v - min) / rng) * ih; };
      function band(lo, hi, fill) {
        var up = hi.map(function (v, k) { return X(k).toFixed(1) + ' ' + Y(v).toFixed(1); }).join(' L ');
        var dn = lo.slice().reverse().map(function (v, k) { return X(n - 1 - k).toFixed(1) + ' ' + Y(v).toFixed(1); }).join(' L ');
        return '<path d="M ' + up + ' L ' + dn + ' Z" fill="' + fill + '"/>';
      }
      var median = fc.p50.map(function (v, k) { return X(k).toFixed(1) + ',' + Y(v).toFixed(1); }).join(' ');
      var base = '<line x1="' + padL + '" y1="' + Y(100).toFixed(1) + '" x2="' + (w - padR) + '" y2="' + Y(100).toFixed(1) + '" stroke="rgba(26,36,32,0.25)" stroke-dasharray="3,4"/>';
      return '<svg viewBox="0 0 ' + w + ' ' + h + '" width="100%" preserveAspectRatio="none">' +
        band(fc.p5, fc.p95, 'rgba(17,123,84,0.10)') + band(fc.p25, fc.p75, 'rgba(17,123,84,0.20)') + base +
        '<polyline points="' + median + '" fill="none" stroke="#117B54" stroke-width="2.2" stroke-linejoin="round"/>' +
        '<text x="' + (w - padR) + '" y="' + (Y(fc.p95[n-1]) - 3).toFixed(1) + '" text-anchor="end" font-size="9" fill="#5F6E66" font-family="JetBrains Mono,monospace">p95</text>' +
        '<text x="' + (w - padR) + '" y="' + (Y(fc.p5[n-1]) + 11).toFixed(1) + '" text-anchor="end" font-size="9" fill="#B3261E" font-family="JetBrains Mono,monospace">p5</text>' +
        '</svg><div class="perf-legend"><span><i style="background:#117B54"></i>Médiane</span><span><i style="background:rgba(17,123,84,0.35)"></i>IC 50%</span><span><i style="background:rgba(17,123,84,0.15)"></i>IC 90%</span></div>';
    }
    // ── Barres horizontales comparatives (stress tests) ──
    // rows = [{label, value, ref}] - value = portefeuille, ref = benchmark
    function hbars(rows, opts) {
      opts = opts || {};
      if (!rows || !rows.length) return '';
      var w = opts.width || 560, rowH = 34, padL = 170, padR = 60, h = rows.length * rowH + 8;
      var vals = [];
      rows.forEach(function (r) { vals.push(r.value); if (r.ref != null) vals.push(r.ref); });
      var maxAbs = Math.max.apply(null, vals.map(Math.abs)) || 1;
      var iw = w - padL - padR, x0 = padL + iw / 2;
      var out = '<svg viewBox="0 0 ' + w + ' ' + h + '" width="100%" style="max-width:720px;display:block;margin:0 auto;">';
      out += '<line x1="' + x0 + '" y1="4" x2="' + x0 + '" y2="' + (h - 4) + '" stroke="rgba(26,36,32,0.18)"/>';
      rows.forEach(function (r, i) {
        var y = i * rowH + 8;
        var bw = (Math.abs(r.value) / maxAbs) * (iw / 2);
        var bx = r.value >= 0 ? x0 : x0 - bw;
        var col = r.value >= 0 ? '#117B54' : '#B3261E';
        out += '<text x="' + (padL - 8) + '" y="' + (y + 13) + '" text-anchor="end" font-size="11" fill="#1A2420" font-family="IBM Plex Sans,sans-serif">' + _escapeHtml(r.label) + '</text>';
        out += '<rect x="' + bx.toFixed(1) + '" y="' + y + '" width="' + Math.max(1.5, bw).toFixed(1) + '" height="12" rx="2" fill="' + col + '" opacity="0.85"><title>Portefeuille : ' + (r.value * 100).toFixed(1) + '%</title></rect>';
        if (r.ref != null) {
          var bwR = (Math.abs(r.ref) / maxAbs) * (iw / 2);
          var bxR = r.ref >= 0 ? x0 : x0 - bwR;
          out += '<rect x="' + bxR.toFixed(1) + '" y="' + (y + 14) + '" width="' + Math.max(1.5, bwR).toFixed(1) + '" height="5" rx="1.5" fill="#8B968F" opacity="0.8"><title>Benchmark : ' + (r.ref * 100).toFixed(1) + '%</title></rect>';
        }
        out += '<text x="' + (r.value >= 0 ? (x0 + bw + 6) : (x0 - bw - 6)).toFixed(1) + '" y="' + (y + 11) + '" ' + (r.value >= 0 ? '' : 'text-anchor="end" ') + 'font-size="10.5" fill="' + col + '" font-family="JetBrains Mono,monospace">' + ((r.value >= 0 ? '+' : '') + (r.value * 100).toFixed(1)) + '%</text>';
      });
      out += '</svg><div class="perf-legend"><span><i style="background:#117B54"></i>Portefeuille</span><span><i style="background:#8B968F"></i>Benchmark</span></div>';
      return out;
    }
    return { donut: donut, gauge: gauge, sparkline: sparkline, perfCurve: perfCurve,
             histogram: histogram, dlines: dlines, fanChart: fanChart, hbars: hbars };
  })();
