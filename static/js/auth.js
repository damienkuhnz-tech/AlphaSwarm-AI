
  // ── Auth (demo gate - pas de credentials stockés côté client) ──
  let currentUser = null;

  // ── Masque l'overlay de login (commun login + restore) ──
  function _hideLoginOverlay(u) {
    currentUser = u;
    sessionStorage.setItem('alphaswarm_user', u);
    var overlay = document.getElementById('loginOverlay');
    overlay.classList.add('hidden');
    setTimeout(function() { overlay.style.display = 'none'; }, 400);
    var pmInput = document.getElementById('pmName');
    if (pmInput) pmInput.value = u;
    checkApproveBtn();
  }

  function doLogin() {
    var u = document.getElementById('loginUser').value.trim();
    var err = document.getElementById('loginError');
    if (u) {
      _hideLoginOverlay(u);
      // Première connexion : active l'étape 1
      setStepState(1, 'active');
      var b1 = document.getElementById('step-badge-1');
      if (b1) { b1.className = 'badge badge-orange pulsing'; b1.textContent = 'EN COURS...'; }
      buildNav();
      updateFooter();
    } else {
      err.style.display = 'block';
    }
  }

  // Allow Enter key on login inputs + restore session on reload
  document.addEventListener('DOMContentLoaded', function() {
    // Vider les 4 écrans agents dès le chargement - pas de données hardcodées
    try { emptyAgentScreens(); } catch(e) { /* fonction définie plus bas */ }

    var loginEl = document.getElementById('loginUser');
    if (loginEl) loginEl.addEventListener('keydown', function(e) { if (e.key === 'Enter') doLogin(); });

    // ── Restauration de session après reload ──────────────────────────────
    var savedUser = sessionStorage.getItem('alphaswarm_user');
    var savedRunId = sessionStorage.getItem('alphaswarm_run_id');
    if (savedUser) {
      // Masquer l'overlay uniquement - NE PAS réinitialiser les états des étapes
      _hideLoginOverlay(savedUser);
      if (savedRunId) {
        // Vérifier le statut du run avant de reprendre le polling
        fetch(API_BASE + '/api/run/' + savedRunId)
          .then(function(r) { return r.json(); })
          .then(function(data) {
            if (data.status === 'running') {
              // Run encore actif : reprendre le polling - navigation bloquée pendant 3s
              currentRunId = savedRunId;
              _mandateSubmitted = true; // run en cours = mandat déjà soumis
              agentRunning = true;      // verrou : aucun autre agent lançable pendant ce run
              _restoringSession = true;
              startPolling(savedRunId, _pipelinePollCallbacks());
              refreshLaunchButtons();
              setTimeout(function() { _restoringSession = false; }, 3000);
            } else {
              // Run terminé : page fraîche propre - NE PAS restaurer les badges
              sessionStorage.removeItem('alphaswarm_run_id');
              buildNav(); updateFooter(); refreshLaunchButtons();
            }
          })
          .catch(function() {
            sessionStorage.removeItem('alphaswarm_run_id');
            buildNav(); updateFooter(); refreshLaunchButtons();
          });
      } else {
        // Pas de run actif : juste initialiser la nav proprement
        buildNav();
        updateFooter();
      }
    }
  });

