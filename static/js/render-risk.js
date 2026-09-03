  var _QD_MONO = 'font-family:\'JetBrains Mono\',monospace;';
  function _qdPct(x, dec) { return (x == null || isNaN(x)) ? '' : (x * 100).toFixed(dec == null ? 1 : dec) + '%'; }
  function _qdPctS(x, dec) { return (x == null || isNaN(x)) ? '' : ((x >= 0 ? '+' : '') + (x * 100).toFixed(dec == null ? 1 : dec) + '%'); }
  function _qdNum(x, dec) { return (x == null || isNaN(x)) ? '' : Number(x).toFixed(dec == null ? 2 : dec); }
  function _qdKpi(lbl, val, sub, tone) {
    return '<div class="qd-kpi' + (tone ? ' ' + tone : '') + '"><div class="lbl">' + lbl + '</div><div class="val">' + val + '</div>' + (sub ? '<div class="sub">' + sub + '</div>' : '') + '</div>';
  }
  function _qdPanel(id, title, body, note) {
    return '<div class="panel qd-section-anchor" id="qd-' + id + '"><div class="panel-title">' + title + '</div>' + body + (note ? '<div class="qd-note">' + note + '</div>' : '') + '</div>';
  }

  function renderRisk(risk) {
    var el = document.getElementById('riskContent');
    if (!el || !risk) return;
    var vq = risk.validation_quantitative;
    if (!vq || vq.statut !== 'OK') { _renderRiskLegacy(risk, el, vq); return; }

    el.className = 'qd-wrap';
    var statut = risk.statut || 'INCONNU';
    var perf = vq.performance || {}, meta = vq.meta || {};
    var m = risk.metriques_risque || {};
    var html = '';

    // ── Navigation interne ────────────────────────────────────────────────────
    var sections = [
      ['resume', 'Résumé'], ['compliance', 'Compliance'], ['perf', 'Performance'],
      ['traintest', 'Train / Test'], ['walkforward', 'Walk-Forward'], ['rolling', 'Rolling'],
      ['drawdown', 'Drawdown'], ['bootstrap', 'Bootstrap'], ['montecarlo', 'Monte Carlo'],
      ['stress', 'Stress Tests'], ['benchmarks', 'Benchmarks']
    ];
    html += '<div class="qd-nav">' + sections.map(function (s, i) {
      return '<div class="qd-pill' + (i === 0 ? ' active' : '') + '" onclick="qdScrollTo(\'' + s[0] + '\', this)">' + s[1] + '</div>';
    }).join('') + '</div>';

    // ── 1. EXECUTIVE SUMMARY ─────────────────────────────────────────────────
    var comp = vq.compliance || { tests: [] };
    var rScore = (typeof risk.score_risque_global === 'number') ? risk.score_risque_global
      : (statut === 'PASS' ? 32 : statut === 'AJUSTER' ? 62 : 85);
    var hero = '<div class="qd-hero">' +
      '<div style="text-align:center;min-width:140px;"><div style="font-size:10px;color:#5F6E66;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Verdict Risk Agent</div><div class="verdict ' + statut + '">' + statut + '</div>' +
      '<div style="font-size:11px;color:#5F6E66;margin-top:4px;">' + comp.n_pass + ' tests PASS · ' + comp.n_fail + ' FAIL</div></div>' +
      '<div style="min-width:180px;">' + CHART.gauge(rScore, 0, 100, { size: 180, display: rScore, label: rScore < 40 ? 'Risque faible' : rScore < 70 ? 'Risque modéré' : 'Risque élevé' }) + '</div>' +
      '<div style="flex:1;min-width:240px;font-size:12.5px;color:#1A2420;line-height:1.6;">' + _escapeHtml(risk.commentaire || '') +
      '<div style="font-size:10.5px;color:#5F6E66;margin-top:8px;">Validation sur ' + (meta.jours || '') + ' jours (' + (meta.debut || '') + ' → ' + (meta.fin || '') + ') · benchmark ' + _escapeHtml(meta.benchmark || '') + ' · rebalancement ' + (meta.rebalancement || 'mensuel') + ' · calcul ' + (meta.duree_calcul_s != null ? meta.duree_calcul_s + 's' : '') + '</div></div></div>';
    var kpis = '<div class="qd-kpis" style="margin-top:14px;">' +
      _qdKpi('CAGR', _qdPct(perf.cagr), 'bench ' + _qdPct(perf.cagr_benchmark), (perf.cagr || 0) >= (perf.cagr_benchmark || 0) ? 'good' : 'bad') +
      _qdKpi('Sharpe', _qdNum(perf.sharpe), 'Sortino ' + _qdNum(perf.sortino), 'accent') +
      _qdKpi('Volatilité', _qdPct(perf.volatilite), 'baisse ' + _qdPct(perf.volatilite_baisse)) +
      _qdKpi('Max Drawdown', _qdPct(perf.max_drawdown), (perf.drawdown_recovery != null ? 'récup. ' + perf.drawdown_recovery + ' j' : 'non récupéré'), 'bad') +
      _qdKpi('Alpha', _qdPctS(perf.alpha), 'Beta ' + _qdNum(perf.beta), (perf.alpha || 0) >= 0 ? 'good' : 'bad') +
      _qdKpi('Info Ratio', _qdNum(perf.information_ratio), 'TE ' + _qdPct(perf.tracking_error)) +
      _qdKpi('VaR 95% (1j)', _qdPct(perf.var_95, 2), 'CVaR ' + _qdPct(perf.cvar_95, 2)) +
      _qdKpi('Hit Ratio', _qdPct(perf.hit_ratio, 0), 'mois > benchmark') +
      '</div>';
    html += _qdPanel('resume', 'Executive Summary', hero + kpis);

    // ── Violations + Recommandations (jugement de l'agent) ───────────────────
    if ((risk.violations && risk.violations.length) || (risk.recommandations && risk.recommandations.length)) {
      var vb = '<div class="qd-grid-2">';
      vb += '<div>';
      if (risk.violations && risk.violations.length) {
        vb += '<div class="table-wrap"><table><thead><tr><th>Sévérité</th><th>Violation</th><th>Action</th></tr></thead><tbody>';
        risk.violations.forEach(function (v) {
          var bc = v.severite === 'CRITIQUE' ? 'badge-red' : v.severite === 'MAJEURE' ? 'badge-orange' : 'badge-yellow';
          vb += '<tr><td><span class="badge ' + bc + '" style="font-size:10px;">' + (v.severite || '') + '</span></td><td style="font-size:12px;">' + _escapeHtml(v.detail || '') + '</td><td style="font-size:11.5px;color:#5F6E66;">' + _escapeHtml(v.action || '') + '</td></tr>';
        });
        vb += '</tbody></table></div>';
      } else { vb += '<div class="qd-note">Aucune violation détectée.</div>'; }
      vb += '</div><div>';
      (risk.recommandations || []).forEach(function (r) {
        vb += '<div style="font-size:12.5px;padding:6px 0;border-bottom:1px solid rgba(26,36,32,0.03);color:#1A2420;">→ ' + _escapeHtml(r) + '</div>';
      });
      vb += '</div></div>';
      html += _qdPanel('violations', 'Violations & Recommandations', vb);
    }

    // ── 2. MANDATE COMPLIANCE ────────────────────────────────────────────────
    var ct = '<div style="margin-bottom:10px;">' +
      '<span class="badge ' + (comp.statut_global === 'PASS' ? 'badge-green' : 'badge-red') + '" style="font-size:12px;padding:5px 16px;">MANDAT : ' + comp.statut_global + '</span>' +
      '<span style="font-size:11px;color:#5F6E66;margin-left:12px;">' + comp.n_pass + ' PASS · ' + comp.n_fail + ' FAIL · ' + comp.n_na + ' N/A - tests calculés en Python, indépendants du LLM</span></div>';
    ct += '<div class="table-wrap"><table><thead><tr><th>Contrainte</th><th>Catégorie</th><th>Limite</th><th>Mesuré</th><th style="text-align:center;">Statut</th></tr></thead><tbody>';
    (comp.tests || []).forEach(function (t) {
      var cls = t.statut === 'PASS' ? 'qd-pass' : t.statut === 'FAIL' ? 'qd-fail' : 'qd-na';
      var icon = t.statut === 'PASS' ? '✓' : t.statut === 'FAIL' ? '✗' : '';
      ct += '<tr class="qd-compliance-row"><td>' + _escapeHtml(t.nom) + (t.detail ? '<div style="font-size:10px;color:#5F6E66;">' + _escapeHtml(t.detail) + '</div>' : '') + '</td>' +
        '<td style="color:#5F6E66;font-size:11px;">' + _escapeHtml(t.categorie) + '</td>' +
        '<td style="' + _QD_MONO + 'font-size:11.5px;">' + _escapeHtml(t.limite) + '</td>' +
        '<td style="' + _QD_MONO + 'font-size:11.5px;">' + _escapeHtml(t.valeur) + '</td>' +
        '<td style="text-align:center;" class="' + cls + '">' + icon + ' ' + t.statut + '</td></tr>';
    });
    ct += '</tbody></table></div>';
    html += _qdPanel('compliance', 'Mandate Compliance', ct);

    // ── 3. PERFORMANCE ───────────────────────────────────────────────────────
    var curve = (vq.courbe_valeur || []).map(function (p) { return { port: p.port, bench: p.bench }; });
    var pb = '';
    if (curve.length > 1) pb += CHART.perfCurve(curve, { height: 230 });
    pb += '<div class="qd-grid-2" style="margin-top:14px;"><div class="table-wrap"><table class="kv-table">' +
      '<tr><td>Rendement total</td><td style="' + _QD_MONO + '">' + _qdPctS(perf.rendement_total) + '</td></tr>' +
      '<tr><td>Rendement benchmark</td><td style="' + _QD_MONO + '">' + _qdPctS(perf.rendement_benchmark) + '</td></tr>' +
      '<tr><td>Surperformance</td><td style="' + _QD_MONO + 'color:' + ((perf.surperformance || 0) >= 0 ? '#117B54' : '#B3261E') + ';">' + _qdPctS(perf.surperformance) + '</td></tr>' +
      '<tr><td>CAGR</td><td style="' + _QD_MONO + '">' + _qdPct(perf.cagr) + '</td></tr>' +
      '<tr><td>Alpha (Jensen, annualisé)</td><td style="' + _QD_MONO + '">' + _qdPctS(perf.alpha) + '</td></tr>' +
      '<tr><td>Beta</td><td style="' + _QD_MONO + '">' + _qdNum(perf.beta) + '</td></tr>' +
      '<tr><td>Corrélation benchmark</td><td style="' + _QD_MONO + '">' + _qdNum(perf.correlation) + '</td></tr>' +
      '</table></div><div class="table-wrap"><table class="kv-table">' +
      '<tr><td>Sharpe</td><td style="' + _QD_MONO + '">' + _qdNum(perf.sharpe) + '</td></tr>' +
      '<tr><td>Sortino</td><td style="' + _QD_MONO + '">' + _qdNum(perf.sortino) + '</td></tr>' +
      '<tr><td>Calmar</td><td style="' + _QD_MONO + '">' + _qdNum(perf.calmar) + '</td></tr>' +
      '<tr><td>Treynor</td><td style="' + _QD_MONO + '">' + _qdNum(perf.treynor) + '</td></tr>' +
      '<tr><td>Information Ratio</td><td style="' + _QD_MONO + '">' + _qdNum(perf.information_ratio) + '</td></tr>' +
      '<tr><td>VaR 95% / 99% (1j)</td><td style="' + _QD_MONO + '">' + _qdPct(perf.var_95, 2) + ' / ' + _qdPct(perf.var_99, 2) + '</td></tr>' +
      '<tr><td>CVaR 95% (1j)</td><td style="' + _QD_MONO + '">' + _qdPct(perf.cvar_95, 2) + '</td></tr>' +
      '</table></div></div>';
    var st = vq.structure || {};
    pb += '<div class="qd-kpis" style="margin-top:14px;">' +
      _qdKpi('Positions', st.nombre_positions != null ? st.nombre_positions : '', 'effectives : ' + (st.positions_effectives != null ? st.positions_effectives : '')) +
      _qdKpi('HHI', _qdNum(st.herfindahl, 3), 'concentration') +
      _qdKpi('Ratio diversification', _qdNum(st.ratio_diversification), '&gt; 1 = bénéfice réel') +
      _qdKpi('Turnover', _qdPct(st.turnover_annuel_rebalancement, 0), 'rebalancement mensuel') +
      _qdKpi('Top 10', m.concentration_top10 || '', 'top 1 : ' + (m.concentration_top1 || '')) +
      '</div>';
    html += _qdPanel('perf', 'Performance - ' + (meta.periode || '') + ' vs ' + _escapeHtml(meta.benchmark || ''), pb,
      (st.tickers_exclus && st.tickers_exclus.length) ? 'Titres exclus (historique insuffisant) : ' + st.tickers_exclus.join(', ') + ' - poids renormalisés.' : '');

    // ── 4. TRAIN / TEST ──────────────────────────────────────────────────────
    var tt = vq.train_test || {};
    if (tt.statut === 'OK') {
      var isM = tt.in_sample || {}, oosM = tt.out_of_sample || {};
      function ttCard(title, mm, tone) {
        return '<div><div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:' + tone + ';margin-bottom:8px;">' + title + '</div>' +
          '<div class="table-wrap"><table class="kv-table">' +
          '<tr><td>Période</td><td style="' + _QD_MONO + 'font-size:11px;">' + (mm.debut || '') + ' → ' + (mm.fin || '') + '</td></tr>' +
          '<tr><td>CAGR</td><td style="' + _QD_MONO + '">' + _qdPct(mm.cagr) + '</td></tr>' +
          '<tr><td>Sharpe</td><td style="' + _QD_MONO + '">' + _qdNum(mm.sharpe) + '</td></tr>' +
          '<tr><td>Volatilité</td><td style="' + _QD_MONO + '">' + _qdPct(mm.volatilite) + '</td></tr>' +
          '<tr><td>Max drawdown</td><td style="' + _QD_MONO + '">' + _qdPct(mm.max_drawdown) + '</td></tr>' +
          '<tr><td>Surperformance</td><td style="' + _QD_MONO + '">' + _qdPctS(mm.surperformance) + '</td></tr>' +
          '</table></div></div>';
      }
      var degrad = (isM.sharpe != null && oosM.sharpe != null) ? (oosM.sharpe - isM.sharpe) : null;
      var tb = '<div class="qd-grid-2">' + ttCard('In-Sample (80% - ' + (tt.date_coupure ? 'jusqu\'au ' + tt.date_coupure : '') + ')', isM, '#5F6E66') +
        ttCard('Out-of-Sample (20% récents)', oosM, '#117B54') + '</div>' +
        '<div class="qd-kpis" style="margin-top:14px;">' +
        _qdKpi('Δ Sharpe OOS', degrad == null ? '' : (degrad >= 0 ? '+' : '') + degrad.toFixed(2), degrad != null && degrad >= -0.3 ? 'généralisation correcte' : 'dégradation hors échantillon', degrad != null ? (degrad >= -0.3 ? 'good' : 'bad') : '') +
        '</div>';
      html += _qdPanel('traintest', 'Validation Train / Test (split chronologique 80/20)', tb,
        'Split temporel sans mélange : les 20 % les plus récents jouent le rôle de données jamais vues. Limite : la sélection des titres reste postérieure au début de l\'historique (biais de sélection documenté).');
    }

    // ── 5. WALK-FORWARD ──────────────────────────────────────────────────────
    var wf = vq.walk_forward || {};
    if (wf.statut === 'OK') {
      var wb = '<div class="qd-kpis" style="margin-bottom:14px;">' +
        _qdKpi('Fenêtres', wf.nb_fenetres, 'train ' + wf.config.train_annees + ' ans / test ' + wf.config.test_annees + ' an') +
        _qdKpi('CAGR moyen', _qdPct((wf.cagr || {}).moyenne), '± ' + _qdPct((wf.cagr || {}).ecart_type)) +
        _qdKpi('Sharpe moyen', _qdNum((wf.sharpe || {}).moyenne), '± ' + _qdNum((wf.sharpe || {}).ecart_type)) +
        _qdKpi('Drawdown moyen', _qdPct((wf.max_drawdown || {}).moyenne), 'pire : ' + _qdPct((wf.max_drawdown || {}).min)) +
        _qdKpi('Stabilité', _qdPct(wf.stabilite, 0), 'fenêtres profitables', (wf.stabilite || 0) >= 0.7 ? 'good' : '') +
        '</div>';
      wb += '<div class="table-wrap"><table><thead><tr><th>#</th><th>Période test</th><th>CAGR</th><th>Sharpe</th><th>Volatilité</th><th>Max DD</th><th>Surperf.</th></tr></thead><tbody>';
      (wf.fenetres || []).forEach(function (f) {
        wb += '<tr><td>' + f.fenetre + '</td><td style="' + _QD_MONO + 'font-size:11px;">' + (f.test_debut || '') + ' → ' + (f.test_fin || '') + '</td>' +
          '<td style="' + _QD_MONO + 'color:' + ((f.cagr || 0) >= 0 ? '#117B54' : '#B3261E') + ';">' + _qdPctS(f.cagr) + '</td>' +
          '<td style="' + _QD_MONO + '">' + _qdNum(f.sharpe) + '</td>' +
          '<td style="' + _QD_MONO + '">' + _qdPct(f.volatilite) + '</td>' +
          '<td style="' + _QD_MONO + 'color:#B3261E;">' + _qdPct(f.max_drawdown) + '</td>' +
          '<td style="' + _QD_MONO + '">' + _qdPctS(f.surperformance) + '</td></tr>';
      });
      wb += '</tbody></table></div>';
      html += _qdPanel('walkforward', 'Walk-Forward - stabilité temporelle', wb,
        'Chaque fenêtre de test est disjointe : une performance stable entre fenêtres est un signe de robustesse, un bon résultat isolé peut être de la chance.');
    }

    // ── 6. ROLLING METRICS ───────────────────────────────────────────────────
    var roll = vq.rolling || {};
    if ((roll.sharpe || []).length > 3) {
      var rb = '<div class="qd-grid-3">' +
        '<div><div style="font-size:11px;color:#5F6E66;margin-bottom:6px;">Rolling Sharpe (6 mois)</div>' + CHART.dlines([{ label: 'Sharpe', color: '#117B54', points: roll.sharpe }], { height: 130, refLine: 0 }) + '</div>' +
        '<div><div style="font-size:11px;color:#5F6E66;margin-bottom:6px;">Rolling Beta (6 mois)</div>' + CHART.dlines([{ label: 'Beta', color: '#117B54', points: roll.beta }], { height: 130, refLine: 1 }) + '</div>' +
        '<div><div style="font-size:11px;color:#5F6E66;margin-bottom:6px;">Rolling Volatilité (6 mois)</div>' + CHART.dlines([{ label: 'Volatilité', color: '#117B54', points: roll.volatilite }], { height: 130 }) + '</div>' +
        '</div>';
      html += _qdPanel('rolling', 'Rolling Metrics - fenêtre glissante 126 jours', rb);
    }

    // ── 7. DRAWDOWN ──────────────────────────────────────────────────────────
    var ddq = vq.drawdown || {};
    if ((ddq.courbe || []).length > 3) {
      var db = '<div class="qd-kpis" style="margin-bottom:12px;">' +
        _qdKpi('Max Drawdown', _qdPct(ddq.max), '', 'bad') +
        _qdKpi('Durée de chute', (ddq.duree_jours != null ? ddq.duree_jours + ' j' : ''), 'pic → creux') +
        _qdKpi('Récupération', (ddq.recovery_jours != null ? ddq.recovery_jours + ' j' : 'en cours'), 'creux → nouveau pic', ddq.recovery_jours != null ? 'good' : 'bad') +
        '</div>';
      db += CHART.dlines([{ label: 'Drawdown (%)', color: '#B3261E', points: (ddq.courbe || []).map(function (p) { return { date: p.date, valeur: p.drawdown }; }) }], { height: 160, refLine: 0 });
      html += _qdPanel('drawdown', 'Drawdown Analysis', db);
    }

    // ── 8. BOOTSTRAP ─────────────────────────────────────────────────────────
    var bs = vq.bootstrap || {};
    if (bs.statut === 'OK') {
      function bsBlock(title, d, fmt, obs) {
        return '<div><div style="font-size:11px;color:#5F6E66;margin-bottom:6px;">' + title + '</div>' +
          CHART.histogram(d.histogramme, { height: 130, format: fmt, marker: obs, markerLabel: 'observé' }) +
          '<div style="font-size:11px;color:#1A2420;margin-top:6px;' + _QD_MONO + '">médiane ' + fmt(d.mediane) + ' · IC95 [' + fmt(d.ci_bas) + ' ; ' + fmt(d.ci_haut) + ']</div></div>';
      }
      var fmtP = function (x) { return _qdPct(x, 0); }, fmtN = function (x) { return _qdNum(x, 2); };
      var bb = '<div class="qd-kpis" style="margin-bottom:14px;">' +
        _qdKpi('Simulations', bs.n_simulations, 'block bootstrap 21 j, seedé') +
        _qdKpi('P(battre benchmark)', _qdPct(bs.prob_batre_benchmark, 0), '', (bs.prob_batre_benchmark || 0) >= 0.5 ? 'good' : 'bad') +
        _qdKpi('P(CAGR > 0)', _qdPct(bs.prob_cagr_positif, 0), '', (bs.prob_cagr_positif || 0) >= 0.8 ? 'good' : '') +
        _qdKpi('P(Sharpe > 0)', _qdPct(bs.prob_sharpe_positif, 0), '') +
        '</div>';
      bb += '<div class="qd-grid-3">' +
        bsBlock('Distribution du CAGR', bs.cagr, fmtP, perf.cagr) +
        bsBlock('Distribution du Sharpe', bs.sharpe, fmtN, perf.sharpe) +
        bsBlock('Distribution du Max Drawdown', bs.max_drawdown, fmtP, perf.max_drawdown) +
        '</div>';
      html += _qdPanel('bootstrap', 'Bootstrap - significativité statistique (' + bs.n_simulations + ' ré-échantillonnages)', bb,
        'Ré-échantillonnage par blocs conjoint portefeuille/benchmark : préserve l\'autocorrélation et la corrélation croisée. Si l\'IC95 du Sharpe exclut 0, la performance est statistiquement significative.');
    }

    // ── 9. MONTE CARLO ───────────────────────────────────────────────────────
    var mc = vq.monte_carlo || {};
    if (mc.statut === 'OK') {
      var mb = '<div class="qd-kpis" style="margin-bottom:14px;">' +
        _qdKpi('Trajectoires', mc.n_simulations, 'horizon 1 an, non-paramétrique') +
        _qdKpi('Rendement attendu', _qdPctS(mc.rendement_attendu), 'médian ' + _qdPctS(mc.rendement_median)) +
        _qdKpi('P(perte)', _qdPct(mc.prob_perte, 0), 'P(perte > 10%) : ' + _qdPct(mc.prob_perte_10pct, 0), (mc.prob_perte || 0) <= 0.2 ? 'good' : 'bad') +
        _qdKpi('VaR 95% (1 an)', _qdPct(mc.var_95_1an), 'VaR 99% : ' + _qdPct(mc.var_99_1an), 'bad') +
        _qdKpi('P(≥ ' + _qdPct(mc.rendement_cible, 0) + ')', _qdPct(mc.prob_rendement_cible, 0), 'rendement cible') +
        '</div>';
      mb += '<div class="qd-grid-2"><div><div style="font-size:11px;color:#5F6E66;margin-bottom:6px;">Éventail des trajectoires (base 100)</div>' +
        CHART.fanChart(mc.fan_chart, { height: 190 }) + '</div>' +
        '<div><div style="font-size:11px;color:#5F6E66;margin-bottom:6px;">Distribution du rendement à 1 an</div>' +
        CHART.histogram(mc.histogramme, { height: 170, format: function (x) { return _qdPct(x, 0); }, marker: 0, markerLabel: '0%' }) + '</div></div>';
      html += _qdPanel('montecarlo', 'Monte Carlo - distribution des scénarios futurs', mb,
        'Trajectoires simulées par bootstrap de blocs des rendements historiques (aucune hypothèse de normalité). ' + (mc.methode || ''));
    }

    // ── 10. STRESS TESTS ─────────────────────────────────────────────────────
    var stress = (vq.stress_tests || []).filter(function (s) { return s.statut === 'OK'; });
    if (stress.length) {
      var sb = CHART.hbars(stress.map(function (s) {
        return { label: s.nom, value: s.rendement, ref: s.rendement_benchmark };
      }));
      sb += '<div class="table-wrap" style="margin-top:14px;"><table><thead><tr><th>Scénario</th><th>Période</th><th>Portefeuille</th><th>Benchmark</th><th>Max DD</th><th>Récup.</th><th>Couverture</th></tr></thead><tbody>';
      stress.forEach(function (s) {
        sb += '<tr><td>' + _escapeHtml(s.nom) + '<div style="font-size:10px;color:#5F6E66;">' + _escapeHtml(s.description || '') + '</div></td>' +
          '<td style="' + _QD_MONO + 'font-size:10.5px;">' + s.debut + ' → ' + s.fin + '</td>' +
          '<td style="' + _QD_MONO + 'color:' + ((s.rendement || 0) >= 0 ? '#117B54' : '#B3261E') + ';">' + _qdPctS(s.rendement) + '</td>' +
          '<td style="' + _QD_MONO + '">' + _qdPctS(s.rendement_benchmark) + '</td>' +
          '<td style="' + _QD_MONO + 'color:#B3261E;">' + _qdPct(s.max_drawdown) + '</td>' +
          '<td style="' + _QD_MONO + '">' + (s.recovery_jours != null ? s.recovery_jours + ' j' : '') + '</td>' +
          '<td style="' + _QD_MONO + '">' + _qdPct(s.couverture_poids, 0) + '</td></tr>';
      });
      sb += '</tbody></table></div>';
      html += _qdPanel('stress', 'Stress Tests - scénarios historiques', sb,
        'Allocation actuelle rejouée sur des crises réelles : capture les corrélations effectives en période de stress. Couverture = part du portefeuille disposant d\'un historique sur la fenêtre.');
    }

    // ── 11. BENCHMARKS ───────────────────────────────────────────────────────
    var bmk = vq.benchmarks || {};
    if ((bmk.comparaisons || []).length) {
      var kb = '<div class="table-wrap"><table><thead><tr><th>Référence</th><th>Type</th><th>CAGR réf.</th><th>Surperf. ann.</th><th>TE</th><th>Info Ratio</th><th>Hit Ratio</th><th>Sharpe réf.</th></tr></thead><tbody>';
      bmk.comparaisons.forEach(function (b) {
        kb += '<tr><td><strong>' + _escapeHtml(b.nom) + '</strong></td><td style="color:#5F6E66;font-size:11px;">' + _escapeHtml(b.type) + '</td>' +
          '<td style="' + _QD_MONO + '">' + _qdPct(b.cagr) + '</td>' +
          '<td style="' + _QD_MONO + 'color:' + ((b.surperformance_annuelle || 0) >= 0 ? '#117B54' : '#B3261E') + ';">' + _qdPctS(b.surperformance_annuelle) + '</td>' +
          '<td style="' + _QD_MONO + '">' + _qdPct(b.tracking_error) + '</td>' +
          '<td style="' + _QD_MONO + '">' + _qdNum(b.information_ratio) + '</td>' +
          '<td style="' + _QD_MONO + '">' + _qdPct(b.hit_ratio, 0) + '</td>' +
          '<td style="' + _QD_MONO + '">' + _qdNum(b.sharpe) + '</td></tr>';
      });
      kb += '</tbody></table></div>';
      var ta = bmk.test_aleatoire || {};
      if (ta.statut === 'OK') {
        kb += '<div class="qd-kpis" style="margin-top:14px;">' +
          _qdKpi('Test placebo', 'p' + Math.round((ta.percentile_portefeuille || 0) * 100), 'percentile parmi ' + ta.n_portefeuilles + ' portefeuilles aléatoires', (ta.percentile_portefeuille || 0) >= 0.7 ? 'good' : '') +
          _qdKpi('Sharpe portefeuille', _qdNum(ta.sharpe_portefeuille), 'aléatoire médian : ' + _qdNum(ta.sharpe_aleatoire_median)) +
          _qdKpi('Seuil p95 aléatoire', _qdNum(ta.sharpe_aleatoire_p95), 'même univers, poids Dirichlet') +
          '</div>';
      }
      html += _qdPanel('benchmarks', 'Benchmark - comparaison multi-références', kb,
        'Le test placebo situe l\'allocation dans la distribution de portefeuilles aléatoires sur le MÊME univers de titres : il mesure la valeur de l\'allocation au-delà de la sélection.');
    }

    // ── Commentaire méthodologique de l'agent ────────────────────────────────
    if (risk.commentaire_backtest) {
      html += _qdPanel('methodo', 'Lecture du Risk Agent - validation & limites',
        '<div style="font-size:12.5px;color:#1A2420;line-height:1.6;">' + _escapeHtml(risk.commentaire_backtest) + '</div>',
        'Backtest rétrospectif : l\'allocation actuelle est rejouée sur le passé (biais de sélection possible sur le choix des titres). Les protocoles ci-dessus (OOS, walk-forward, bootstrap, placebo) encadrent ce biais.');
    }

    el.innerHTML = html;
    _qdUpdateAlert(risk);
  }

  // Navigation interne du dashboard (pills → scroll)
  function qdScrollTo(id, pill) {
    var t = document.getElementById('qd-' + id);
    if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' });
    document.querySelectorAll('.qd-pill').forEach(function (p) { p.classList.remove('active'); });
    if (pill) pill.classList.add('active');
  }

  function _qdUpdateAlert(risk) {
    var ra = document.getElementById('riskAlert');
    if (!ra) return;
    if (risk.violations && risk.violations.length) {
      ra.style.display = '';
      ra.textContent = '⚠ ' + risk.violations.length + ' violation(s) détectée(s)';
    } else {
      ra.style.display = 'none';
    }
  }

  // Rendu de repli : moteur quant indisponible (réseau coupé, historique vide...)
  function _renderRiskLegacy(risk, el, vq) {
    el.className = 'risk-two-col';
    var statut = risk.statut || 'INCONNU';
    var badge = statut === 'PASS' ? 'badge-green' : statut === 'AJUSTER' ? 'badge-orange' : 'badge-red';
    var html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">';
    html += '<div>';
    if (vq && vq.statut === 'ERREUR') {
      html += '<div class="alert alert-orange" style="margin-bottom:14px;">Moteur de validation quantitative indisponible : ' + _escapeHtml(vq.message || 'données de marché manquantes') + '. Verdict rendu sur la structure du portefeuille uniquement.</div>';
    }
    if (risk.violations && risk.violations.length) {
      html += '<div class="panel"><div class="panel-title">Violations Détectées</div><div class="table-wrap"><table><thead><tr><th>Sévérité</th><th>Détail</th></tr></thead><tbody>';
      risk.violations.forEach(function(v) {
        var bc = v.severite === 'CRITIQUE' ? 'badge-red' : v.severite === 'MAJEURE' ? 'badge-orange' : 'badge-yellow';
        html += '<tr><td><span class="badge ' + bc + '" style="font-size:10px;">' + (v.severite||'') + '</span></td><td style="font-size:12px;">' + (v.detail||'') + '</td></tr>';
      });
      html += '</tbody></table></div></div>';
    }
    if (risk.recommandations && risk.recommandations.length) {
      html += '<div class="panel"><div class="panel-title">Recommandations</div>';
      risk.recommandations.forEach(function(r) {
        html += '<div style="font-size:12.5px;padding:6px 0;border-bottom:1px solid rgba(26,36,32,0.03);color:#1A2420;">→ ' + r + '</div>';
      });
      html += '</div>';
    }
    html += '</div><div>';
    html += '<div class="panel"><div class="panel-title">Score de Risque</div>';
    var rScore = (typeof risk.score_risque_global === 'number') ? risk.score_risque_global
      : (statut === 'PASS' ? 32 : statut === 'AJUSTER' ? 62 : 85);
    var rLabel = rScore < 40 ? 'Faible' : rScore < 70 ? 'Modéré' : 'Élevé';
    html += CHART.gauge(rScore, 0, 100, { size: 220, display: rScore, label: rLabel });
    html += '<div style="text-align:center;padding:4px 0 6px;"><span class="badge ' + badge + '" style="font-size:13px;padding:6px 20px;">' + statut + '</span></div></div>';
    if (risk.metriques_risque) {
      var m = risk.metriques_risque;
      var mono = 'font-family:\'JetBrains Mono\',monospace;';
      var benchLbl = m.benchmark_utilise ? (' <span style="color:#5F6E66;font-size:10px;">vs ' + _escapeHtml(m.benchmark_utilise) + (m.periode ? ' · ' + _escapeHtml(m.periode) : '') + '</span>') : '';
      html += '<div class="panel"><div class="panel-title">Métriques calculées' + benchLbl + '</div><div class="table-wrap"><table class="kv-table">';
      if (m.volatilite_estimee)     html += '<tr><td>Volatilité</td><td style="' + mono + '">' + _escapeHtml(m.volatilite_estimee) + '</td></tr>';
      if (m.tracking_error_estimee) html += '<tr><td>Tracking Error</td><td style="' + mono + '">' + _escapeHtml(m.tracking_error_estimee) + '</td></tr>';
      if (m.beta_estime)            html += '<tr><td>Beta</td><td style="' + mono + '">' + _escapeHtml(m.beta_estime) + '</td></tr>';
      if (m.concentration_top1)     html += '<tr><td>Concentration top 1</td><td style="' + mono + '">' + _escapeHtml(m.concentration_top1) + '</td></tr>';
      if (m.concentration_top10)    html += '<tr><td>Concentration top 10</td><td style="' + mono + '">' + _escapeHtml(m.concentration_top10) + '</td></tr>';
      html += '</table></div></div>';
      if (risk.backtest && risk.backtest.statut === 'OK') {
        var b = risk.backtest, pctB = function(x){ return (x==null) ? '' : (x*100).toFixed(2) + '%'; };
        var surColor = (b.surperformance||0) >= 0 ? 'var(--perf-green)' : '#B3261E';
        html += '<div class="panel"><div class="panel-title">Backtest - ' + _escapeHtml(b.periode||'') + (b.benchmark_utilise ? ' <span style="color:#5F6E66;font-size:10px;">vs ' + _escapeHtml(b.benchmark_utilise) + '</span>' : '') + '</div>';
        if (b.courbe_valeur && b.courbe_valeur.length > 1) html += '<div style="margin-bottom:14px;">' + CHART.perfCurve(b.courbe_valeur, { height: 180 }) + '</div>';
        html += '<div class="table-wrap"><table class="kv-table">';
        html += '<tr><td>Rendement portefeuille</td><td style="' + mono + '">' + pctB(b.rendement_total) + '</td></tr>';
        html += '<tr><td>Rendement benchmark</td><td style="' + mono + '">' + pctB(b.rendement_benchmark) + '</td></tr>';
        html += '<tr><td>Surperformance</td><td style="' + mono + 'color:' + surColor + ';">' + ((b.surperformance||0)>=0?'+':'') + pctB(b.surperformance) + '</td></tr>';
        html += '<tr><td>Sharpe</td><td style="' + mono + '">' + (b.sharpe==null?'':b.sharpe) + '</td></tr>';
        html += '<tr><td>Max drawdown</td><td style="' + mono + 'color:#B3261E;">' + pctB(b.max_drawdown) + '</td></tr>';
        html += '</table></div>';
        if (risk.commentaire_backtest) html += '<div style="font-size:12px;color:#1A2420;padding:8px 4px 2px;line-height:1.5;">' + _escapeHtml(risk.commentaire_backtest) + '</div>';
        html += '<div style="font-size:10px;color:#5F6E66;padding:6px 4px 0;font-style:italic;">Rétrospectif : allocation figée appliquée au passé. Indicatif.</div></div>';
      }
    }
    html += '</div></div>';
    el.innerHTML = html;
    _qdUpdateAlert(risk);
  }

  // ── Rendu dynamique - Étape 5 : Execution ──
  function renderExecution(execution) {
    var el = document.getElementById('executionContent');
    if (!el || !execution) return;
    var ordres = execution.ordres || [];
    var html = '<div style="display:grid;grid-template-columns:1.5fr 1fr;gap:20px;">';
    html += '<div><div class="panel"><div class="panel-title">Liste des Ordres (' + ordres.length + ')</div><div class="table-wrap"><table><thead><tr><th>#</th><th>Ticker</th><th>Action</th><th>Valeur USD</th><th>Poids</th><th>Algo</th><th>Priorité</th></tr></thead><tbody>';
    ordres.forEach(function(o, i) {
      var ac = o.action === 'BUY' ? 'badge-green' : 'badge-red';
      var pc = o.priorite === 'HIGH' ? 'badge-red' : o.priorite === 'NORMAL' ? 'badge-blue' : 'badge-orange';
      html += '<tr><td>' + (i+1) + '</td><td><strong>' + (o.ticker||'') + '</strong></td>';
      html += '<td><span class="badge ' + ac + '" style="font-size:10px;">' + (o.action||'') + '</span></td>';
      html += '<td style="font-family:\'JetBrains Mono\',monospace;">$' + Math.round(o.valeur_usd||0).toLocaleString() + '</td>';
      html += '<td>' + ((o.poids_cible||0)*100).toFixed(1) + '%</td>';
      html += '<td style="font-size:11px;">' + (o.algo_suggere||'') + '</td>';
      html += '<td><span class="badge ' + pc + '" style="font-size:10px;">' + (o.priorite||'') + '</span></td></tr>';
    });
    html += '</tbody></table></div>';
    if (execution.couts_transaction) {
      html += '<div class="exec-total">Capital investi : $' + Math.round(execution.capital_investi||0).toLocaleString() + ' &nbsp;|&nbsp; Cash : $' + Math.round(execution.capital_cash||0).toLocaleString() + '</div>';
    }
    html += '</div></div>';
    html += '<div>';
    if (execution.couts_transaction) {
      var c = execution.couts_transaction;
      html += '<div class="panel"><div class="panel-title">Coûts Estimés</div><div class="table-wrap"><table class="kv-table">';
      var comm = c.commissions_estimees_usd || c.commissions_usd || 0;
      var mkt  = c.market_impact_estime_usd || c.market_impact_usd || 0;
      if (comm)  html += '<tr><td>Commissions</td><td>$' + Math.round(comm).toLocaleString() + '</td></tr>';
      if (mkt)   html += '<tr><td>Market impact</td><td>$' + Math.round(mkt).toLocaleString() + '</td></tr>';
      html += '<tr><td><strong>Total</strong></td><td><strong>$' + Math.round(c.total_estime_usd||0).toLocaleString() + '</strong></td></tr>';
      html += '<tr><td>En bps</td><td>' + Math.round(c.total_bps||0) + ' bps</td></tr>';
      html += '</table></div></div>';
    }
    html += '<div class="panel"><div class="panel-title">Format Export OMS</div>';
    html += '<div class="radio-group" id="exportFormat"><div class="radio-option selected" onclick="selectFormat(this)">&#9679; FIX Protocol</div><div class="radio-option" onclick="selectFormat(this)">&#9675; CSV</div><div class="radio-option" onclick="selectFormat(this)">&#9675; JSON</div></div>';
    html += '<button type="button" class="btn-report" style="width:100%;padding:10px;font-size:13px;margin-top:10px;">Télécharger pour OMS</button></div>';
    html += '</div></div>';
    el.innerHTML = html;
  }
