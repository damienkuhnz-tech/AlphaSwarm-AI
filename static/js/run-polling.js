
  // Callbacks du pipeline complet (lancement global + reprise de session apres
  // reload). Declaration de fonction : hoistee, donc utilisable depuis le
  // handler DOMContentLoaded qui s'execute avant ce point du script.
  function _pipelinePollCallbacks() {
    return {
      onDone: function() {
        showRunBanner('Analyse terminée - données réelles chargées', 'success');
      },
      onError: function(d) {
        showRunBanner('Erreur agent : ' + ((d && d.error) || '?'), 'error');
      },
      onTimeout: function() {
        showRunBanner('Aucune réponse après ' + MAX_RUN_MINUTES +
                      ' minutes - suivi interrompu. Vérifiez la console du serveur.', 'error');
      }
    };
  }

  // ── Polling unifie (toutes les 2.5s) ──────────────────────────────────────
  // Une seule boucle pour les deux appelants (pipeline complet et lancement d'un
  // agent isole). Elle etait dupliquee : `startPolling`/`pollRun` d'un cote, un
  // setInterval ecrit a la main dans `launchAgent` de l'autre. L'intervalle
  // inline n'etait annulable que par son propre callback, si bien qu'un
  // changement de page ou une relance laissait une boucle vivante (defaut D3).
  // Le handle est desormais TOUJOURS `pollInterval`, donc toujours annulable.
  //
  // Les differences de fin de run sont portees par les callbacks :
  //   opts.onDone(data)    - run termine avec succes
  //   opts.onError(data)   - run termine en erreur
  //   opts.onTimeout()     - garde-temps MAX_RUN_MINUTES depasse
  // Le tronc commun (arret de la boucle, purge du sessionStorage, liberation du
  // verrou agentRunning, refreshLaunchButtons) est fait ici une fois pour toutes.
  function startPolling(runId, opts) {
    opts = opts || {};
    stopPolling();
    // Horloge du garde-temps. On teste la DISPONIBILITE de l'API, pas la valeur
    // retournee : performance.now() compte depuis le chargement de la page et
    // vaut ~0 quand startPolling est appele tres tot (reprise de session dans
    // DOMContentLoaded). Un test « if (startedAt) » desarmait alors le
    // garde-temps precisement dans ce cas. Repli sur Date.now() si absent.
    var _clock = (window.performance && typeof performance.now === 'function')
      ? function () { return performance.now(); }
      : function () { return Date.now(); };
    var startedAt = _clock();

    // Fin de suivi, quelle qu'en soit la cause : etat global remis a plat avant
    // d'appeler le callback specifique de l'appelant.
    function finish(cb, arg) {
      stopPolling();
      sessionStorage.removeItem('alphaswarm_run_id');
      agentRunning = false; // libere le verrou global
      if (cb) { try { cb(arg); } catch (e) { /* un callback ne doit jamais bloquer */ } }
      refreshLaunchButtons();
    }

    pollInterval = setInterval(function() {
      // Garde-temps : un run bloque laissait tourner le polling indefiniment et
      // le spinner ne s'arretait jamais (defaut D2).
      if ((_clock() - startedAt) / 60000 > MAX_RUN_MINUTES) {
        finish(opts.onTimeout);
        return;
      }
      fetch(API_BASE + '/api/run/' + runId)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        updateFromRunData(data);
        if (data.status === 'done') {
          lastCompletedRunId = runId;
          finish(opts.onDone, data);
        } else if (data.status === 'error') {
          finish(opts.onError, data);
        }
      })
      .catch(function() {}); // erreur reseau ponctuelle : on retente au tick suivant
    }, 2500);
  }

  // Arret explicite du suivi en cours (relance, navigation, fin de run).
  function stopPolling() {
    if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
  }

  // ── Met à jour l'interface selon l'état du run ──
  function updateFromRunData(data) {
    var partial = data.partial_state || {};
    var final   = data.final_state   || {};
    var stepMap = { mandate:1, research:2, portfolio:3, risk:4, execution:5 };
    var stepNum = stepMap[data.current_step] || 1;

    // ── Progression recherche en temps réel (hook par ticker) ──────────────
    var rp = data.research_progress;
    if (rp && rp.total > 0) {
      var rg = document.getElementById('researchGrid');
      var pctR = Math.round((rp.done / rp.total) * 100);
      // Badge "EN COURS" du step 3 : affiche le compteur
      var b3 = document.getElementById('step-badge-3');
      if (b3 && b3.textContent !== 'COMPLÉTÉ ✓') {
        b3.className = 'badge badge-orange pulsing';
        b3.textContent = 'EN COURS ' + rp.done + '/' + rp.total;
      }
      // Si des résultats partiels arrivent, on les affiche immédiatement
      var partialRes = partial.research || [];
      if (partialRes.length > 0) {
        var ideas = partial.ideas || final.ideas || [];
        renderResearchGrid(partialRes);
        renderSectorAnalysisTab(partialRes, ideas);
        // Met à jour le titre du loading block avec le compteur
        var loadMsg = document.querySelector('#researchGrid .agent-loading-block p');
        if (loadMsg) loadMsg.textContent = rp.done + ' / ' + rp.total + ' entreprises analysées (' + pctR + '%)';
      } else if (rg && rg.querySelector('.agent-loading-block')) {
        // Toujours en loading, juste mettre à jour le texte
        var loadP = rg.querySelector('.agent-loading-block p');
        if (loadP) loadP.textContent = 'Analyse en cours : ' + rp.done + ' / ' + rp.total + ' entreprises (' + pctR + '%)';
      }
      // Barre de progression : step 3 = plage 33%-55%
      var pf = document.getElementById('agentProgressFill');
      if (pf && stepNum <= 3) {
        var barPct = 33 + Math.round((rp.done / rp.total) * 22);
        if (barPct !== lastProgressPct) { lastProgressPct = barPct; pf.style.width = barPct + '%'; }
      }
    }

    // Met à jour le badge de l'étape concernée - sans navigation automatique
    if (stepNum > lastCompletedStep) {
      markStepDoneUI(stepNum);
      lastCompletedStep = stepNum;
      updateTabs();
      updateFooter();
    }

    // Injecte les données dans chaque écran - guarded by change detection
    var ideas    = partial.ideas    || final.ideas    || [];
    var research = partial.research || final.research || [];
    var portfolio= partial.portfolio|| final.portfolio|| null;
    var curIdeaLen = ideas ? ideas.length : 0;
    var curResLen  = research ? research.length : 0;
    var curResDone = (rp && rp.total > 0) ? rp.done : -1;
    if (ideas && curIdeaLen !== _lastIdeasLen) {
      _lastIdeasLen = curIdeaLen; renderIdeasTable(ideas);
    }
    if (research && (curResLen !== _lastResearchLen || curResDone !== _lastResearchDoneN)) {
      _lastResearchLen = curResLen; _lastResearchDoneN = curResDone;
      renderResearchGrid(research); renderSectorAnalysisTab(research, ideas);
    }
    if (portfolio) {
      var pJ = JSON.stringify(portfolio);
      if (pJ !== _lastPortfolioJSON) { _lastPortfolioJSON = pJ; renderPortfolio(portfolio); }
    }
    if (final.risk) {
      var rJ = JSON.stringify(final.risk);
      if (rJ !== _lastRiskJSON) { _lastRiskJSON = rJ; renderRisk(final.risk); }
    }
    if (final.execution) {
      var eJ = JSON.stringify(final.execution);
      if (eJ !== _lastExecutionJSON) { _lastExecutionJSON = eJ; renderExecution(final.execution); }
    }
    // Update progress bar
    var pf2 = document.getElementById('agentProgressFill');
    if (pf2 && !(rp && rp.total > 0 && stepNum <= 3)) {
      var newPct2 = Math.min(10 + stepNum * 11, 98);
      if (newPct2 !== lastProgressPct) { lastProgressPct = newPct2; pf2.style.width = newPct2 + '%'; }
    }
    if (data.status === 'done' || data.status === 'error') {
      if (pf2 && lastProgressPct !== 100) { lastProgressPct = 100; pf2.style.width = '100%'; }
      setTimeout(function() {
        var pb2 = document.getElementById('agentProgressBar');
        if (pb2) pb2.style.display = 'none';
      }, 1500);
    }
  }

  function markStepDoneUI(n) {
    setStepState(n, 'completed');
    if (n >= 2 && n <= 5) _agentCompleted[n] = true; // débloque l'agent suivant du pipeline
    var badge = document.getElementById('step-badge-' + n);
    if (badge) { badge.className = 'badge badge-green'; badge.textContent = 'COMPLÉTÉ'; }
    // L'état de tous les boutons (celui-ci + le suivant débloqué) est recalculé
    // de façon centralisée pour éviter toute logique dupliquée.
    refreshLaunchButtons();
    try { SwarmFX.complete(n); } catch (e) { /* FX jamais bloquant */ }
  }
