
  // ── Rendu dynamique — Étape 2 : Idées ──
  function renderIdeasTable(ideas) {
    var tbody = document.getElementById('ideasBody');
    if (!tbody || !ideas.length) return;
    tbody.innerHTML = ideas.map(function(idea, i) {
      var score = idea.note_preliminary || 0;
      var scoreColor = score >= 75 ? '#117B54' : score >= 60 ? '#B07A1E' : '#64748B';
      var confBadge = idea.confiance === 'HAUTE' ? 'badge-green' : idea.confiance === 'MOYENNE-HAUTE' ? 'badge-green' : 'badge-yellow';
      return '<tr data-id="' + (i+1) + '">' +
        '<td>' + (i+1) + '</td>' +
        '<td><strong>' + (idea.ticker||'') + '</strong></td>' +
        '<td>' + (idea.nom||'').substring(0,24) + '</td>' +
        '<td>' + (idea.secteur||'—') + '</td>' +
        '<td>' + (idea.geographie||'—') + '</td>' +
        '<td><span class="badge badge-blue">' + (idea.type_signal||'—') + '</span></td>' +
        '<td><span class="badge ' + confBadge + '">' + (idea.confiance||'—') + '</span></td>' +
        '<td>—</td>' +
        '<td><strong style="color:' + scoreColor + '">' + score + '</strong></td>' +
        '<td>—</td>' +
        '<td><button type="button" class="btn-action keep" onclick="keepIdea(' + (i+1) + ')">✓</button>' +
        '<button type="button" class="btn-action exclude" onclick="excludeIdea(' + (i+1) + ')">✗</button></td>' +
        '</tr>';
    }).join('');
    var counter = document.getElementById('ideaCounter');
    if (counter) counter.textContent = ideas.length + '/' + ideas.length + ' titres sélectionnés';
  }

  // ── Rendu dynamique — Étape 3 : Research ──
  function renderResearchGrid(research) {
    var grid = document.getElementById('researchGrid');
    if (!grid || !research.length) return;

    // Comptage pour la filter bar
    var counts = { all: research.length, sb: 0, buy: 0, hold: 0 };
    research.forEach(function(r) {
      var rec = (r.recommandation || 'HOLD').toUpperCase();
      if (rec === 'STRONG BUY') counts.sb++;
      else if (rec === 'BUY')   counts.buy++;
      else                       counts.hold++;
    });
    var fb = document.getElementById('researchFilterBar');
    if (fb) {
      fb.innerHTML =
        '<button type="button" class="filter-btn active" onclick="filterResearch(\'all\',this)">Tous (' + counts.all + ')</button>' +
        '<button type="button" class="filter-btn" onclick="filterResearch(\'strong-buy\',this)">STRONG BUY (' + counts.sb + ')</button>' +
        '<button type="button" class="filter-btn" onclick="filterResearch(\'buy\',this)">BUY (' + counts.buy + ')</button>' +
        '<button type="button" class="filter-btn" onclick="filterResearch(\'hold\',this)">HOLD (' + counts.hold + ')</button>';
    }

    grid.innerHTML = research.map(function(r) {
      var reco = (r.recommandation || 'HOLD').toUpperCase();
      var ratingClass = reco === 'STRONG BUY' ? 'card-strong-buy' : reco === 'BUY' ? 'card-buy' : 'card-hold';
      var ratingData  = reco === 'STRONG BUY' ? 'strong-buy' : reco === 'BUY' ? 'buy' : 'hold';
      var score = r.score_conviction || 50;

      // Valorisation — champs réels du modèle ResearchOutput
      var val    = r.valorisation || {};
      var upside = val.upside_potentiel || '—';
      var valLine = val.PER_estime_NTM  ? 'PER NTM : ' + val.PER_estime_NTM
                  : val.EV_EBITDA_NTM   ? 'EV/EBITDA : ' + val.EV_EBITDA_NTM
                  : val.methode_principale ? val.methode_principale
                  : '—';
      var summary = r.these_investissement || '—';
      var poids   = r.poids_suggere_initial ? (r.poids_suggere_initial * 100).toFixed(1) + '%' : '—';

      return '<div class="research-card ' + ratingClass + '" data-rating="' + ratingData + '" data-score="' + score + '">' +
        '<div class="research-card-header">' +
          '<span style="font-size:13px;font-weight:700;">' + _escapeHtml((r.nom || r.ticker || '?').substring(0,26)) + '</span>' +
          '<span style="font-size:10px;color:#5F6E66;margin-left:6px;font-family:\'JetBrains Mono\',monospace;">' + _escapeHtml(r.ticker||'') + '</span>' +
        '</div>' +
        '<div class="research-meta">' +
        '<span class="rating-badge">' + _escapeHtml(reco) + '</span>' +
        '<span class="score-big">' + _escapeHtml(score) + '</span>' +
        '<span class="upside-pct" style="color:var(--accent-green);font-size:13px;font-weight:700;">' + _escapeHtml(upside) + '</span>' +
        '</div>' +
        '<div class="conviction-bar-wrap"><div class="conviction-bar" style="width:' + Math.max(0, Math.min(100, Number(score) || 0)) + '%"></div></div>' +
        '<div class="price-target" style="font-size:11px;color:#5F6E66;margin:4px 0;">' + _escapeHtml(valLine) +
          ' &nbsp;|&nbsp; Poids suggéré : <strong style="color:var(--accent-green);">' + poids + '</strong></div>' +
        // Troncature AVANT echappement : couper apres aurait pu casser une
        // entite HTML en deux (defaut F8).
        '<div class="research-summary">' + _escapeHtml(summary.substring(0, 150)) + (summary.length > 150 ? '…' : '') + '</div>' +
        '<button type="button" class="btn-report" style="margin-top:10px;width:100%;" ' +
          'onclick="window.open(\'' + API_BASE + '/api/report/' + encodeURIComponent(r.ticker||'') + '\',\'_blank\')"><span style="display:inline-flex;align-items:center;vertical-align:middle;margin-right:6px;opacity:0.8;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg></span>Voir rapport →</button>' +
        '</div>';
    }).join('');
  }

  // ── Rendu dynamique — Étape 4 : Portfolio ──
  function renderPortfolio(portfolio) {
    var tbody = document.querySelector('#screen-3 tbody');
    if (!tbody || !portfolio.positions) return;

    // ── Table des positions ──
    var rows = portfolio.positions.map(function(p, i) {
      var pctColor = p.poids >= 0.06 ? 'weight-high' : p.poids >= 0.03 ? 'weight-mid' : 'weight-low';
      return '<tr>' +
        '<td>' + (i+1) + '</td>' +
        '<td><strong>' + _escapeHtml(p.ticker||'') + '</strong></td>' +
        '<td>' + _escapeHtml((p.nom||'').substring(0,22)) + '</td>' +
        '<td>' + _escapeHtml(p.secteur||'—') + '</td>' +
        '<td>' + _escapeHtml(p.geographie||'—') + '</td>' +
        '<td>—</td>' +
        '<td class="' + pctColor + '">' + ((p.poids||0)*100).toFixed(2) + '%</td>' +
        '<td style="font-family:\'JetBrains Mono\',monospace;">$' + Math.round(p.valeur_usd||0).toLocaleString() + '</td>' +
        '<td style="font-size:11px;color:var(--accent-green);">' + _escapeHtml((p.role_portefeuille||'—').substring(0,28)) + '</td>' +
        '</tr>';
    }).join('');
    // Cash row
    rows += '<tr style="opacity:0.6"><td></td><td><strong>CASH</strong></td><td>—</td><td>—</td><td>—</td><td>—</td>' +
      '<td class="weight-mid">' + ((portfolio.cash_poids||0)*100).toFixed(1) + '%</td>' +
      '<td style="font-family:\'JetBrains Mono\',monospace;">$' + Math.round(portfolio.cash_valeur_usd||0).toLocaleString() + '</td>' +
      '<td style="font-size:11px;color:#5F6E66;">Liquidités</td></tr>';
    tbody.innerHTML = rows;

    // ── Panneaux droite : profil et répartitions ──
    var pa = portfolio.profil_attendu || {};
    var kvRows = [
      ['Capital investi', '$' + Math.round((portfolio.capital_total||0)*(1-(portfolio.cash_poids||0))).toLocaleString()],
      ['Nombre de positions', portfolio.nombre_positions || portfolio.positions.length],
      ['Cash', ((portfolio.cash_poids||0)*100).toFixed(1) + '%'],
      ['Tracking Error estimé', pa.tracking_error || '—'],
      ['Beta estimé', pa.beta || '—'],
      ['Rendement attendu', pa.rendement_annualise || '—'],
      ['Volatilité estimée', pa.volatilite_estimee || '—'],
    ];
    var rightPanels = document.getElementById('portfolioRightPanels');
    if (!rightPanels) return;

    var html = '<div class="panel"><div class="panel-title">Profil du Portefeuille</div><div class="table-wrap"><table class="kv-table">';
    kvRows.forEach(function(row) { html += '<tr><td>' + row[0] + '</td><td>' + row[1] + '</td></tr>'; });
    html += '</table></div></div>';

    // Répartition sectorielle → DONUT (cash inclus pour totaliser 100%)
    var sect = portfolio.repartition_sectorielle || {};
    var sectEntries = Object.entries(sect).filter(function(e){ return e[1] > 0; }).sort(function(a,b){ return b[1]-a[1]; });
    if (sectEntries.length) {
      var sectSegs = sectEntries.map(function(e){ return { label: e[0].replace(/_/g,' '), value: e[1] }; });
      var cashP = portfolio.cash_poids || 0;
      if (cashP > 0) sectSegs.push({ label: 'Cash', value: cashP, color: '#5F6E66' });
      var topSect = sectEntries[0];
      html += '<div class="panel"><div class="panel-title">Répartition Sectorielle</div>' +
        CHART.donut(sectSegs, { size: 168, centerLabel: (topSect[1]*100).toFixed(0) + '%', centerSub: topSect[0].replace(/_/g,' ').substring(0,10) }) + '</div>';
    }

    // Répartition géographique → DONUT (agrégée depuis les positions)
    var geoMap = {};
    portfolio.positions.forEach(function(p) {
      var g = p.geographie || 'Autre';
      geoMap[g] = (geoMap[g] || 0) + (p.poids || 0);
    });
    var geoEntries = Object.entries(geoMap).sort(function(a,b){ return b[1]-a[1]; });
    if (geoEntries.length) {
      var geoSegs = geoEntries.map(function(e){ return { label: e[0].substring(0,16), value: e[1] }; });
      html += '<div class="panel"><div class="panel-title">Répartition Géographique</div>' +
        CHART.donut(geoSegs, { size: 168 }) + '</div>';
    }
    rightPanels.innerHTML = html;
  }

  // ── Analyse Sectorielle — construite depuis research + ideas (secteurs réels) ──
  function renderSectorAnalysisTab(research, ideas) {
    var grid = document.getElementById('research-sectors');
    if (!grid || !research || !research.length) return;

    var COLORS = {
      'Technologie':'#5F6E66','Sante':'#117B54','Santé':'#117B54',
      'Finance':'#f4a742','Industrie':'#8b5cf6',
      'Consommation_courante':'#14b8a6','Consommation courante':'#14b8a6',
      'Consommation_discretionnaire':'#ef4444','Consommation discrétionnaire':'#ef4444',
      'Energie':'#f59e0b','Énergie':'#f59e0b',
      'Materiaux':'#06b6d4','Matériaux':'#06b6d4',
      'Utilities':'#22c55e','Services_publics':'#22c55e','Services publics':'#22c55e',
      'Immobilier':'#ec4899','Telecom':'#0ea5e9','Communication':'#0ea5e9','Autre':'#94a3b8'
    };

    // ticker → secteur depuis les ideas (step 2)
    var tickerSect = {};
    if (ideas && ideas.length) {
      ideas.forEach(function(idea) { tickerSect[idea.ticker] = idea.secteur || 'Autre'; });
    }

    // Grouper les entreprises par secteur
    var sectors = {};
    research.forEach(function(r) {
      var s = tickerSect[r.ticker] || r.secteur || 'Autre';
      if (!sectors[s]) sectors[s] = [];
      sectors[s].push(r);
    });

    var entries = Object.entries(sectors).sort(function(a,b){ return b[1].length - a[1].length; });
    if (!entries.length) return;

    grid.innerHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px;">' +
      entries.map(function(entry) {
        var sName = entry[0];
        var comps = entry[1];
        var color = COLORS[sName] || '#7a8499';
        var avgScore = Math.round(comps.reduce(function(s,c){ return s+(c.score_conviction||50); },0)/comps.length);
        var buyCount = comps.filter(function(c){ return (c.recommandation||'').toUpperCase()==='BUY'; }).length;
        var totalPoids = comps.reduce(function(s,c){ return s+(c.poids_suggere_initial||0); },0);

        var compRows = comps.map(function(c) {
          var sc = c.score_conviction || 50;
          var scColor = sc >= 75 ? '#117B54' : sc >= 60 ? '#B07A1E' : '#64748B';
          var rec = (c.recommandation || 'HOLD').toUpperCase();
          var recBadge = rec === 'BUY' ? 'badge-green' : 'badge-blue';
          return '<div style="display:flex;justify-content:space-between;align-items:center;' +
            'padding:5px 0;border-bottom:1px solid rgba(26,36,32,0.03);">' +
            '<span style="font-weight:700;font-size:12px;font-family:\'JetBrains Mono\',monospace;">' + (c.ticker||'') + '</span>' +
            '<span style="font-size:11px;color:#5F6E66;flex:1;padding:0 8px;">' + (c.nom||'').substring(0,16) + '</span>' +
            '<span class="badge ' + recBadge + '" style="font-size:9px;padding:1px 5px;margin-right:6px;">' + rec + '</span>' +
            '<span style="font-size:11px;font-weight:700;color:' + scColor + ';">' + sc + '</span>' +
            '</div>';
        }).join('');

        return '<div class="panel" style="border-top:3px solid ' + color + ';padding:16px;">' +
          '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">' +
            '<span style="font-size:15px;font-weight:700;color:' + color + ';">' + sName.replace(/_/g,' ') + '</span>' +
            '<span class="badge badge-green" style="font-size:9px;">' + buyCount + '/' + comps.length + ' BUY</span>' +
          '</div>' +
          '<div style="display:flex;gap:20px;margin-bottom:14px;">' +
            '<div style="text-align:center;">' +
              '<div style="font-size:22px;font-weight:800;color:' + color + ';">' + avgScore + '</div>' +
              '<div style="font-size:10px;color:#5F6E66;">Conviction</div>' +
            '</div>' +
            '<div style="text-align:center;">' +
              '<div style="font-size:22px;font-weight:800;color:#1A2420;">' + comps.length + '</div>' +
              '<div style="font-size:10px;color:#5F6E66;">Entreprises</div>' +
            '</div>' +
            '<div style="text-align:center;">' +
              '<div style="font-size:22px;font-weight:800;color:#B07A1E;">' + (totalPoids*100).toFixed(0) + '%</div>' +
              '<div style="font-size:10px;color:#5F6E66;">Poids cible</div>' +
            '</div>' +
          '</div>' +
          '<div>' + compRows + '</div>' +
          '<button type="button" class="btn-report" style="width:100%;margin-top:12px;" ' +
            'onclick="window.open(\'' + API_BASE + '/api/sector-report/' + encodeURIComponent(sName) + '\',\'_blank\')">&#128196; Voir rapport sectoriel \u2192</button>' +
          '</div>';
      }).join('') + '</div>';
  }

  // ── Rendu dynamique — Étape 5 : Risk ──
  // ═══════════════════════════════════════════════════════════════════════════
  //  RISK — DASHBOARD DE VALIDATION QUANTITATIVE
  //  Rend le rapport complet produit par quant.run_full_validation() :
  //  Executive Summary, Compliance, Performance, Train/Test, Walk-Forward,
  //  Rolling, Drawdown, Bootstrap, Monte Carlo, Stress Tests, Benchmarks.
  //  Repli automatique sur le rendu historique si le moteur quant est absent.
  // ═══════════════════════════════════════════════════════════════════════════

