// ── EVENTS - câblage des interactions du HTML statique ──────────────────────
// Remplace les 56 anciens attributs onclick/onchange/onkeydown inline du HTML
// (refactor phase 3b). Chargé EN DERNIER : toutes les fonctions référencées
// sont des globales définies par les fichiers précédents. Les éléments générés
// dynamiquement par le JS (filtres re-rendus, boutons de tableau, pills du
// dashboard quant...) portent leurs handlers dans les templates JS d'origine.

(function () {
  'use strict';

  function on(id, evt, fn) {
    var el = document.getElementById(id);
    if (el) el.addEventListener(evt, fn);
  }

  // ── Login ──────────────────────────────────────────────────────────────────
  on('btn-login', 'click', function () { doLogin(); });

  // ── Écran 1 : Mandat ───────────────────────────────────────────────────────
  on('btnAnalyze', 'click', function () { analyzeMandate(); });
  on('btn-reset-analysis', 'click', function () { resetAnalysis(); });

  // Boutons « Valider » des étapes 1-3 (btn-validate-N → completeStep(N))
  [1, 2, 3].forEach(function (n) {
    on('btn-validate-' + n, 'click', function () { completeStep(n); });
  });

  // ── Lancement des agents 2-5 (launch-btn-N → launchAgent(N)) ──────────────
  [2, 3, 4, 5].forEach(function (n) {
    on('launch-btn-' + n, 'click', function () { launchAgent(n); });
  });

  // ── Sous-onglets Analyse / Chat de chaque agent (data-panel) ──────────────
  document.querySelectorAll('.agent-sub-tab[data-panel]').forEach(function (tab) {
    tab.addEventListener('click', function () {
      switchAgentTab(tab, tab.dataset.panel);
    });
  });

  // ── Sous-onglets Research : Entreprises / Sectorielle (data-group/tab) ────
  document.querySelectorAll('.sub-tab[data-group]').forEach(function (tab) {
    tab.addEventListener('click', function () {
      switchSubTab(tab.dataset.group, tab.dataset.tab, tab);
    });
  });

  // ── Barre de filtres Research statique (data-filter) ──────────────────────
  // NB : renderResearchGrid() régénère cette barre avec ses propres handlers ;
  // ces bindings ne concernent que l'état initial (compteurs à 0).
  document.querySelectorAll('#researchFilterBar .filter-btn[data-filter]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      filterResearch(btn.dataset.filter, btn);
    });
  });

  // ── Chats des agents 2-5 ──────────────────────────────────────────────────
  [2, 3, 4, 5].forEach(function (n) {
    on('chat-input-' + n, 'keydown', function (event) { handleChatKey(event, n); });
    on('chat-send-' + n, 'click', function () { sendChatMessage(n); });
    var sugg = document.getElementById('chat-suggestions-' + n);
    if (sugg) {
      sugg.querySelectorAll('.chat-suggestion').forEach(function (s) {
        s.addEventListener('click', function () { injectSuggestion(n, s); });
      });
    }
  });

  // ── Écran Marché ──────────────────────────────────────────────────────────
  on('market-ticker-input', 'keydown', function (event) {
    if (event.key === 'Enter') addMarketTicker();
  });
  on('btn-market-add', 'click', function () { addMarketTicker(); });
  on('market-auto', 'change', function () { toggleAutoRefresh(); });
  on('btn-market-refresh', 'click', function () { refreshMarket(true); });

  // ── Footer de navigation ──────────────────────────────────────────────────
  on('btnPrev', 'click', function () { prevStep(); });
  on('btnNext', 'click', function () { nextStep(); });

  // ── Modale de rejet ───────────────────────────────────────────────────────
  on('btn-reject-cancel', 'click', function () { closeRejectModal(); });
  on('btn-reject-confirm', 'click', function () { confirmReject(); });
})();
