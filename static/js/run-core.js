  // ── API Config ──
  // Origine du serveur : reprend celle de la page quand elle est servie par
  // Flask (http://localhost:5001/app), et retombe sur le defaut en ouverture
  // directe du fichier. Plus aucune adresse codee en dur ailleurs (defaut F5).
  const API_BASE = (window.location.protocol === 'http:' || window.location.protocol === 'https:')
    ? window.location.origin
    : 'http://localhost:5001';
  let currentRunId = null;

  // Dernier run termine avec succes. Transmis au serveur (from_run_id) quand on
  // relance UN agent : sans lui, le serveur repartait d'un etat vide et
  // reconstruisait mandat + recherche + portefeuille depuis zero, si bien que
  // l'agent relance ne jugeait PAS le portefeuille affiche (defaut A2).
  let lastCompletedRunId = null;

  // Duree maximale de suivi d'un run avant abandon du polling (defaut D2).
  const MAX_RUN_MINUTES = 45;
  let pollInterval = null;
  let lastCompletedStep = 0;
  var lastProgressPct = -1;
  var _restoringSession = false; // true pendant les 3s de restauration de session au reload
  var _mandateSubmitted = false; // true uniquement après clic volontaire sur "Valider" étape 1
  var _lastIdeasLen = -1, _lastResearchLen = -1, _lastResearchDoneN = -1;
  var _lastPortfolioJSON = '', _lastRiskJSON = '';
  var _lastExecutionJSON = '';

  // ── Séquençage strict des agents ───────────────────────────────────────────
  // Un seul agent peut tourner à la fois (verrou global) et les agents ne se
  // lancent que dans l'ordre du pipeline : Mandat → Research(2) → Portfolio(3)
  // → Risk(4) → Execution(5). Un agent n'est lançable que si l'étape précédente
  // est terminée. `refreshLaunchButtons()` est l'unique source de vérité de
  // l'état (activé/désactivé + libellé + info-bulle) de chaque bouton.
  var agentRunning = false;                                  // un agent est en cours
  var _agentCompleted = { 2:false, 3:false, 4:false, 5:false }; // agent terminé (run OK)

  // L'agent `stepNum` est-il débloqué (prérequis pipeline satisfait) ?
  function _agentUnlocked(stepNum) {
    if (stepNum === 2) return _mandateSubmitted;   // Research : mandat soumis
    return _agentCompleted[stepNum - 1] === true;  // 3/4/5 : agent précédent terminé
  }

  function refreshLaunchButtons() {
    for (var s = 2; s <= 5; s++) {
      var btn = document.getElementById('launch-btn-' + s);
      var unlocked = _agentUnlocked(s);
      var done = _agentCompleted[s] === true;
      var isThisRunning = agentRunning && btn && btn.dataset.running === '1';

      if (btn) {
        // Désactivé si : un agent tourne, ou prérequis pipeline non satisfait.
        btn.disabled = agentRunning || !unlocked;
        if (isThisRunning) {
          // bouton de l'agent actuellement en exécution - libellé géré par launchAgent
        } else if (agentRunning) {
          btn.textContent = done ? 'Relancer l\'agent' : 'Lancer l\'agent';
          btn.title = 'Un agent est déjà en cours d\'exécution - attendez sa fin.';
        } else if (!unlocked) {
          btn.textContent = 'Lancer l\'agent';
          btn.title = 'Terminez d\'abord l\'étape précédente du pipeline.';
        } else {
          btn.textContent = done ? 'Relancer l\'agent' : 'Lancer l\'agent';
          btn.title = '';
        }
      }

      // ── Badge de l'étape : reflète l'état du pipeline sans écraser les états
      //    transitoires/finaux gérés ailleurs (EN COURS / COMPLÉTÉ / ERREUR). ──
      var badge = document.getElementById('step-badge-' + s);
      if (badge && !isThisRunning && !done) {
        var t = badge.textContent || '';
        if (t.indexOf('EN COURS') === -1 && t !== 'COMPLÉTÉ' && t !== 'ERREUR') {
          if (unlocked && !agentRunning) {
            badge.className = 'badge badge-orange'; badge.textContent = 'DISPONIBLE';
          } else {
            badge.className = 'badge badge-locked'; badge.textContent = 'VERROUILLÉ';
          }
        }
      }
    }
  }

  // ── Collecte les paramètres du formulaire mandat ──
  function collectMandateParams() {
    const v  = (id) => { const el = document.getElementById(id); return el ? el.value.trim() : ''; };
    const vf = (id) => { const val = v(id); return val ? parseFloat(val) : null; };
    const radio   = (name) => { const el = document.querySelector('input[name="' + name + '"]:checked'); return el ? el.value : ''; };
    const checked = (id)   => { const el = document.getElementById(id); return el ? el.checked : false; };

    // Exclusions ESG - IDs réels du formulaire
    const exclusions = [];
    if (checked('esg-tabac'))   exclusions.push('tabac');
    if (checked('esg-armes'))   exclusions.push('armement');
    if (checked('esg-charbon')) exclusions.push('charbon');
    if (checked('esg-jeux'))    exclusions.push('jeux');
    if (checked('esg-alcool'))  exclusions.push('alcool');
    if (checked('esg-nucleaire')) exclusions.push('nucleaire');

    // Profil de risque - normalisation vers les clés Python attendues
    const profilRaw = v('m-profil');
    const profilMap = {
      'conservateur': 'conservateur',
      'equilibre':    'equilibre',
      'agressif':     'agressif',
    };
    // La valeur du <select> peut contenir un emoji ex: "Conservateur ..."
    let profil = 'equilibre';
    Object.keys(profilMap).forEach(function(key) {
      if (profilRaw.toLowerCase().includes(key)) profil = profilMap[key];
    });

    // Priorité principale - radio buttons
    const prioriteRaw = radio('m-priorite') || 'Croissance long terme';
    const prioriteMap = {
      'préservation': 'preservation', 'preservation': 'preservation',
      'revenus':      'revenus',
      'croissance':   'croissance',
      'performance':  'performance',
    };
    let priorite = 'croissance';
    Object.keys(prioriteMap).forEach(function(key) {
      if (prioriteRaw.toLowerCase().includes(key)) priorite = prioriteMap[key];
    });

    return {
      strategie:           v('m-strategie')   || 'Long-Only Equity Global',
      capital:             vf('m-capital')    || 100000000,
      benchmark:           v('m-benchmark')   || 'S&P 500',
      horizon:             v('m-horizon')     || '3-5 ans',
      profil_risque:       profil,
      perte_max_toleree:   vf('m-perte-max'),
      priorite_principale: priorite,
      // Nombre de positions cible : pilote la taille de l'univers analysé par
      // l'Equity Research Agent (univers ≈ 1.5× la cible). Défaut 12 si non saisi.
      nombre_positions_cible: vf('m-nb-positions') || 12,
      exclusions_esg:      exclusions,
      // ── Contraintes beta explicites saisies dans le formulaire ──────────────
      // Transmises au MandateAgent pour réconciliation si conflit avec profil_risque.
      // Ex: profil="conservateur" + beta_min=1.5 → MandateAgent détecte l'incohérence
      // et recalibre le profil effectif vers "agressif".
      beta_min_override:   vf('m-beta-min'),
      beta_max_override:   vf('m-beta-max'),
    };
  }

  // ── Helpers loading ──
  function _loadingDiv(msg) {
    return '<div class="agent-loading-block"><div class="spin-big"></div>' + msg + '<br><span style="font-size:11px;color:#8B968F;margin-top:6px;display:block;">Durée estimée : 2–10 min selon le mandat</span></div>';
  }
  function _loadingRow(msg, cols) {
    return '<tr class="loading-row"><td colspan="' + (cols||10) + '"><div class="agent-spinner"></div>' + msg + '</td></tr>';
  }

  // ── Vide les 4 écrans agents au chargement : état "Lancer l'agent" ──
  function _emptyPlaceholder(label) {
    return '<div style="padding:60px 20px;text-align:center;color:var(--text-dim);font-size:13px;">' +
           '<div style="font-size:28px;margin-bottom:14px;opacity:0.4;">∅</div>' +
           '<div style="font-size:14px;color:var(--text-secondary);margin-bottom:6px;">Aucune donnée pour le moment</div>' +
           '<div style="font-size:12px;color:var(--text-dim);">' + label + '</div>' +
           '</div>';
  }
  function emptyAgentScreens() {
    var rg = document.getElementById('researchGrid');
    if (rg) rg.innerHTML = _emptyPlaceholder('Cliquez sur « Lancer l\'agent » pour analyser les titres selon votre mandat.');
    var sectGrid = document.getElementById('research-sectors');
    if (sectGrid) sectGrid.innerHTML = _emptyPlaceholder('L\'analyse sectorielle sera générée après l\'exécution de l\'agent.');
    // Portfolio - tbody
    var pb = document.querySelector('#screen-3 tbody');
    if (pb) pb.innerHTML = '<tr><td colspan="9" style="padding:48px;text-align:center;color:var(--text-dim);">Cliquez sur « Lancer l\'agent » pour construire le portefeuille.</td></tr>';
    // Portfolio right panels (secteurs / géo)
    var prp = document.getElementById('portfolioRightPanels');
    if (prp) prp.innerHTML = _emptyPlaceholder('Répartitions sectorielles et géographiques disponibles après lancement.');
    // Risk
    var rc = document.getElementById('riskContent');
    if (rc) rc.innerHTML = _emptyPlaceholder('Cliquez sur « Lancer l\'agent » pour analyser les risques.');
    var ra = document.getElementById('riskAlert');
    if (ra) ra.style.display = 'none';
    // Execution
    var ec = document.getElementById('executionContent');
    if (ec) ec.innerHTML = _emptyPlaceholder('Cliquez sur « Lancer l\'agent » pour préparer les ordres d\'exécution.');
  }

  // ── Vide tout le contenu statique dès le lancement ──
  function clearStaticData() {
    var ib = document.getElementById('ideasBody');
    if (ib) ib.innerHTML = _loadingRow('Génération des idées d\'investissement...', 11);
    var rg = document.getElementById('researchGrid');
    if (rg) rg.innerHTML = _loadingDiv('Analyse equity en cours...');
    var pb = document.querySelector('#screen-3 tbody');
    if (pb) pb.innerHTML = _loadingRow('Construction du portefeuille en cours...', 9);
    var rc = document.getElementById('riskContent');
    if (rc) rc.innerHTML = _loadingDiv('Analyse des risques...');
    var ec = document.getElementById('executionContent');
    if (ec) ec.innerHTML = _loadingDiv('Préparation des ordres d\'exécution...');
    // Counter idées
    var ctr = document.getElementById('ideaCounter');
    if (ctr) ctr.textContent = 'Chargement...';
    // Alerte risk
    var ra = document.getElementById('riskAlert');
    if (ra) { ra.style.display = 'none'; }
    // Analyse sectorielle - vide le hardcodé
    var sectGrid = document.getElementById('research-sectors');
    if (sectGrid) sectGrid.innerHTML = _loadingDiv('Analyse sectorielle en cours...');
    // Progress bar
    var pb2 = document.getElementById('agentProgressBar');
    if (pb2) { pb2.style.display = 'block'; }
    var pf = document.getElementById('agentProgressFill');
    if (pf) { pf.style.width = '5%'; }
    lastProgressPct = 5;
    // Ne pas réinitialiser _mandateSubmitted ici - il est géré par completeStep/session restore
    _lastIdeasLen = -1; _lastResearchLen = -1; _lastResearchDoneN = -1;
    _lastPortfolioJSON = ''; _lastRiskJSON = '';
    _lastExecutionJSON = '';
    lastCompletedStep = 0;
  }

  // ── Lance le workflow via l'API ──
  function startAgentRun(params) {
    clearStaticData();
    fetch(API_BASE + '/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params)
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      currentRunId = data.run_id;
      sessionStorage.setItem('alphaswarm_run_id', currentRunId);
      showRunBanner('Run ' + currentRunId + ' lancé - agents en cours...', 'info');
      startPolling(currentRunId, _pipelinePollCallbacks());
    })
    .catch(function(err) {
      // Il n'existe aucun mode demonstration : l'interface reste vide (defaut F2).
      showRunBanner('Serveur injoignable - aucune donnée ne sera chargée. Démarrez le serveur (python api.py) puis relancez.', 'error');
    });
  }

  // ── Lance un agent individuel depuis son onglet ──
  var _stepNameMap = { 2:'research', 3:'portfolio', 4:'risk', 5:'execution' };
  var _stepNumMap  = { research:2, portfolio:3, risk:4, execution:5 };

  function launchAgent(stepNum) {
    if (!_mandateSubmitted) {
      showRunBanner('Complétez d\'abord le Mandat avant de lancer un agent.', 'warn');
      return;
    }
    // ── Verrou global : un seul agent à la fois ──
    if (agentRunning) {
      showRunBanner('Un agent est déjà en cours d\'exécution - attendez sa fin avant d\'en lancer un autre.', 'warn');
      return;
    }
    // ── Ordre du pipeline : l'étape précédente doit être terminée ──
    if (!_agentUnlocked(stepNum)) {
      showRunBanner('Étape verrouillée - terminez d\'abord l\'agent précédent du pipeline.', 'warn');
      return;
    }
    var stepName = _stepNameMap[stepNum];
    if (!stepName) return;

    agentRunning = true;
    var launchBtn = document.getElementById('launch-btn-' + stepNum);
    if (launchBtn) { launchBtn.dataset.running = '1'; launchBtn.disabled = true; launchBtn.textContent = 'En cours...'; }
    refreshLaunchButtons(); // grise tous les autres boutons
    try { SwarmFX.launch(stepNum); } catch (e) { /* FX jamais bloquant */ }

    var badge = document.getElementById('step-badge-' + stepNum);
    if (badge) { badge.className = 'badge badge-orange pulsing'; badge.textContent = 'EN COURS...'; }

    // Remplacer le placeholder vide par un loading sur l'écran concerné
    if (stepNum === 2) {
      var rg = document.getElementById('researchGrid');
      if (rg) rg.innerHTML = _loadingDiv('Analyse equity en cours...');
      var sg = document.getElementById('research-sectors');
      if (sg) sg.innerHTML = _loadingDiv('Analyse sectorielle en cours...');
    } else if (stepNum === 3) {
      var pb = document.querySelector('#screen-3 tbody');
      if (pb) pb.innerHTML = _loadingRow('Construction du portefeuille en cours...', 9);
    } else if (stepNum === 4) {
      var rc = document.getElementById('riskContent');
      if (rc) rc.innerHTML = _loadingDiv('Analyse des risques...');
    } else if (stepNum === 5) {
      var ec = document.getElementById('executionContent');
      if (ec) ec.innerHTML = _loadingDiv('Préparation des ordres d\'exécution...');
    }

    var pb = document.getElementById('agentProgressBar');
    if (pb) pb.style.display = 'block';
    var pf = document.getElementById('agentProgressFill');
    if (pf) { pf.style.width = '5%'; lastProgressPct = 5; }

    var params = collectMandateParams();
    params.target_step = stepName;
    // Reprise de l'etat du run precedent : les etapes deja produites ne sont
    // pas rejouees, et l'agent travaille sur le portefeuille reellement affiche.
    if (lastCompletedRunId) params.from_run_id = lastCompletedRunId;

    fetch(API_BASE + '/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params)
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var runId = data.run_id;
      showRunBanner('Agent ' + stepName + ' lancé (run ' + runId + ')', 'info');
      // Suivi via la boucle unifiee (defaut D3). Le comportement propre a ce
      // chemin - liberation du bouton, markStepDoneUI, badge d'erreur - est
      // porte par les callbacks ; le reste est mutualise dans startPolling.
      function releaseBtn() { if (launchBtn) delete launchBtn.dataset.running; }
      startPolling(runId, {
        onDone: function() {
          releaseBtn();
          showRunBanner('Agent ' + stepName + ' terminé', 'success');
          markStepDoneUI(stepNum); // marque _agentCompleted + rafraîchit les boutons
          updateTabs();
        },
        onError: function(d) {
          releaseBtn();
          showRunBanner('Erreur agent ' + stepName + ' : ' + ((d && d.error) || '?'), 'error');
          if (badge) { badge.className = 'badge badge-red'; badge.textContent = 'ERREUR'; }
        },
        onTimeout: function() {
          releaseBtn();
          showRunBanner('Agent ' + stepName + ' : aucune réponse après ' + MAX_RUN_MINUTES +
                        ' minutes - suivi interrompu. Vérifiez la console du serveur.', 'error');
          if (badge) { badge.className = 'badge badge-red'; badge.textContent = 'INTERROMPU'; }
        }
      });
    })
    .catch(function() {
      agentRunning = false; // libère le verrou en cas d'échec réseau
      if (launchBtn) delete launchBtn.dataset.running;
      showRunBanner('Impossible de contacter l\'API - l\'agent n\'a pas été lancé. Démarrez le serveur (python api.py) puis réessayez.', 'error');
      if (badge) { badge.className = 'badge badge-orange'; badge.textContent = 'DISPONIBLE'; }
      refreshLaunchButtons();
    });
  }
