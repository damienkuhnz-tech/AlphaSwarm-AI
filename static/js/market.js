
  // ════════════════════════════════════════════════════════════════════════
  //  ONGLET MARCHÉ - cours de bourse quasi temps réel (/api/quotes)
  // ════════════════════════════════════════════════════════════════════════
  var _marketWatchlist = ['NVDA','MSFT','LLY','ASML','AMZN','V','NVO','JPM','SAP','TSM','AAPL','GOOGL'];
  var _marketScreenPrev = null;   // étape à restaurer en quittant le marché
  var _marketLoading = false;
  var _marketTimer = null;        // handle setInterval auto-refresh
  var _marketLastPrices = {};     // ticker → dernier prix connu (pour flash up/down)
  var _MARKET_INTERVAL = 8000;    // 8 s

  // Affiche / masque l'écran Marché (onglet hors du flux verrouillé des 5 étapes)
  function toggleMarket() {
    if (!currentUser) return;   // pas avant connexion
    var marketScreen = document.getElementById('screen-market');
    var tab = document.getElementById('tab-item-market');
    var isOpen = marketScreen.classList.contains('active');

    if (isOpen) {
      // Fermer → stopper le polling + revenir à l'étape précédente
      stopAutoRefresh();
      marketScreen.classList.remove('active');
      if (tab) tab.classList.remove('active');
      var back = document.getElementById('screen-' + (_marketScreenPrev || currentStep));
      if (back) back.classList.add('active');
      updateTabs();   // restaure le surlignage de l'onglet étape courant
      return;
    }

    // Ouvrir → masquer tous les écrans + surligner l'onglet Marché
    _marketScreenPrev = currentStep;
    document.querySelectorAll('.screen.active').forEach(function(s){ s.classList.remove('active'); });
    document.querySelectorAll('.report-modal.show').forEach(function(m){ m.classList.remove('show'); });
    document.querySelectorAll('.tab-item.active').forEach(function(t){ t.classList.remove('active'); });
    marketScreen.classList.add('active');
    if (tab) tab.className = 'tab-item active';
    window.scrollTo(0, 0);
    refreshMarket(true);
    startAutoRefresh();
  }

  function startAutoRefresh() {
    stopAutoRefresh();
    var chk = document.getElementById('market-auto');
    if (chk && !chk.checked) return;             // auto-refresh désactivé
    _marketTimer = setInterval(function() { refreshMarket(false); }, _MARKET_INTERVAL);
    _setLiveBadge(true);
  }

  function stopAutoRefresh() {
    if (_marketTimer) { clearInterval(_marketTimer); _marketTimer = null; }
    _setLiveBadge(false);
  }

  function toggleAutoRefresh() {
    var chk = document.getElementById('market-auto');
    if (chk && chk.checked) { refreshMarket(false); startAutoRefresh(); }
    else stopAutoRefresh();
  }

  function _setLiveBadge(on) {
    var badge = document.getElementById('market-live-badge');
    if (!badge) return;
    if (on) {
      badge.style.opacity = '1';
      badge.innerHTML = '<span class="market-live-dot"></span>LIVE';
    } else {
      badge.style.opacity = '0.5';
      badge.innerHTML = '<span class="market-live-dot" style="animation:none;background:var(--text-dim);box-shadow:none;"></span>EN PAUSE';
    }
  }

  function addMarketTicker() {
    var input = document.getElementById('market-ticker-input');
    if (!input) return;
    var raw = input.value.trim().toUpperCase();
    if (!raw) return;
    // Autorise plusieurs tickers séparés par virgule/espace
    raw.split(/[\s,]+/).forEach(function(t) {
      if (t && /^[A-Z0-9.\-^]{1,12}$/.test(t) && _marketWatchlist.indexOf(t) === -1) {
        _marketWatchlist.unshift(t);
      }
    });
    input.value = '';
    refreshMarket(true);
  }

  function removeMarketTicker(tk) {
    _marketWatchlist = _marketWatchlist.filter(function(t){ return t !== tk; });
    delete _marketLastPrices[tk];
    refreshMarket(false);
  }

  // showSpinner=true affiche "Chargement…" (1er chargement / action manuelle).
  // En auto-refresh on rafraîchit silencieusement (showSpinner=false).
  function refreshMarket(showSpinner) {
    if (_marketLoading) return;
    if (!_marketWatchlist.length) {
      document.getElementById('market-tbody').innerHTML =
        '<tr><td colspan="10" style="text-align:center;padding:40px;color:var(--text-dim);">Watchlist vide - ajoutez un ticker ci-dessus.</td></tr>';
      return;
    }
    _marketLoading = true;
    var lbl = document.getElementById('market-refresh-label');
    if (lbl && showSpinner) lbl.textContent = '↻ Chargement…';

    fetch(API_BASE + '/api/quotes/live?tickers=' + encodeURIComponent(_marketWatchlist.join(',')))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        _marketLoading = false;
        if (lbl) lbl.textContent = '↻ Actualiser';
        if (data.error) {
          document.getElementById('market-tbody').innerHTML =
            '<tr><td colspan="10" style="text-align:center;padding:30px;color:var(--accent-red);">' + data.error + '</td></tr>';
          return;
        }
        renderMarket(data.quotes || []);
        var ts = document.getElementById('market-timestamp');
        if (ts && data.horodatage) {
          var d = new Date(data.horodatage);
          ts.textContent = 'Dernière maj : ' + d.toLocaleTimeString('fr-FR');
        }
      })
      .catch(function() {
        _marketLoading = false;
        if (lbl) lbl.textContent = '↻ Actualiser';
        document.getElementById('market-tbody').innerHTML =
          '<tr><td colspan="10" style="text-align:center;padding:30px;color:var(--accent-red);">API non disponible - lancez python api.py</td></tr>';
      });
  }

  function renderMarket(quotes) {
    var tbody = document.getElementById('market-tbody');
    if (!tbody) return;
    if (!quotes.length) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:40px;color:var(--text-dim);">Aucune donnée.</td></tr>';
      return;
    }
    var mono = "font-family:'JetBrains Mono',monospace;";
    var flashTickers = [];   // tickers dont le prix a bougé → flash après rendu

    tbody.innerHTML = quotes.map(function(q) {
      if (q.statut !== 'OK') {
        return '<tr data-tk="' + q.ticker + '"><td><strong>' + q.ticker + '</strong></td>' +
          '<td colspan="8" style="color:var(--text-dim);font-size:12px;">' + (q.message || 'Indisponible') + '</td>' +
          '<td><button type="button" class="btn-mkt-remove" onclick="removeMarketTicker(\'' + q.ticker + '\')" title="Retirer">×</button></td></tr>';
      }
      var cur = q.devise === 'EUR' ? '€' : q.devise === 'USD' ? '$' : (q.devise || '') + ' ';
      var fmt = function(v, dec) { return (v != null) ? Number(v).toLocaleString('fr-FR', {maximumFractionDigits: dec == null ? 2 : dec}) : ''; };
      var prix = (q.prix != null) ? cur + fmt(q.prix) : '';

      // Détection mouvement de prix (pour flash)
      var prev = _marketLastPrices[q.ticker];
      if (prev != null && q.prix != null && q.prix !== prev) {
        flashTickers.push({ tk: q.ticker, up: q.prix > prev });
      }
      if (q.prix != null) _marketLastPrices[q.ticker] = q.prix;

      // Variation du jour (abs + %) colorée
      var up = (q.variation_pct != null) ? q.variation_pct >= 0 : true;
      var cls = up ? 'market-up' : 'market-down';
      var arrow = up ? '▲' : '▼';
      var varAbs = (q.variation_abs != null) ? '<span class="' + cls + '" style="' + mono + '">' + (up ? '+' : '') + fmt(q.variation_abs) + '</span>' : '';
      var varPct = (q.variation_pct != null) ? '<span class="' + cls + '" style="' + mono + 'font-weight:700;">' + arrow + ' ' + (up ? '+' : '') + (q.variation_pct * 100).toFixed(2) + '%</span>' : '';

      // 52 semaines (barre de position)
      var range52 = '';
      if (q.annee_bas && q.annee_haut && q.annee_haut > q.annee_bas) {
        var pos = Math.max(0, Math.min(100, Math.round((q.prix - q.annee_bas) / (q.annee_haut - q.annee_bas) * 100)));
        range52 = '<div style="font-size:10px;color:var(--text-dim);' + mono + '">' + fmt(q.annee_bas,0) + ' – ' + fmt(q.annee_haut,0) + '</div>' +
          '<div class="mkt-52-track"><div class="mkt-52-fill" style="width:' + pos + '%"></div></div>';
      }
      // Volume formaté (M)
      var vol = (q.volume != null) ? (q.volume >= 1e6 ? (q.volume/1e6).toFixed(1) + 'M' : fmt(q.volume,0)) : '';

      return '<tr data-tk="' + q.ticker + '">' +
        '<td><strong style="color:var(--accent-gold);">' + q.ticker + '</strong></td>' +
        '<td class="mkt-price" style="' + mono + 'font-weight:700;font-size:14px;">' + prix + '</td>' +
        '<td>' + varAbs + '</td>' +
        '<td>' + varPct + '</td>' +
        '<td style="' + mono + 'font-size:12px;color:var(--text-secondary);">' + fmt(q.ouverture) + '</td>' +
        '<td style="' + mono + 'font-size:12px;color:var(--text-secondary);">' + fmt(q.haut_jour) + '</td>' +
        '<td style="' + mono + 'font-size:12px;color:var(--text-secondary);">' + fmt(q.bas_jour) + '</td>' +
        '<td style="min-width:90px;">' + range52 + '</td>' +
        '<td style="' + mono + 'font-size:12px;color:var(--text-secondary);">' + vol + '</td>' +
        '<td><button type="button" class="btn-mkt-remove" onclick="removeMarketTicker(\'' + q.ticker + '\')" title="Retirer">×</button></td>' +
        '</tr>';
    }).join('');

    // Flash vert/rouge sur les prix qui ont bougé
    flashTickers.forEach(function(f) {
      var row = tbody.querySelector('tr[data-tk="' + f.tk + '"]');
      if (!row) return;
      var cell = row.querySelector('.mkt-price');
      if (!cell) return;
      cell.classList.remove('flash-up', 'flash-down');
      void cell.offsetWidth;  // force reflow pour relancer l'animation
      cell.classList.add(f.up ? 'flash-up' : 'flash-down');
    });
  }

  // ── Research card filter (Screen-3) ──
  function filterResearch(rating, btn) {
    // Update active button
    document.querySelectorAll('#researchFilterBar .filter-btn').forEach(function(b) {
      b.classList.remove('active');
    });
    btn.classList.add('active');

    // Show/hide cards
    var cards = document.querySelectorAll('#researchGrid .research-card');
    cards.forEach(function(card) {
      if (rating === 'all') {
        card.style.display = '';
      } else {
        var cardRating = card.getAttribute('data-rating');
        card.style.display = (cardRating === rating) ? '' : 'none';
      }
    });
  }
