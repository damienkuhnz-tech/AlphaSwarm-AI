
  // ── Step State Machine ──
  // States: 'locked' | 'active' | 'completed'
  const stepStates = { 1:'active', 2:'locked', 3:'locked', 4:'locked', 5:'locked' }; // 1 toujours actif au démarrage

  function setStepState(n, state) {
    stepStates[n] = state;
  }

  function completeStep(n) {
    setStepState(n, 'completed');
    // Update badge
    const badge = document.getElementById('step-badge-' + n);
    if (badge) { badge.className = 'badge badge-green'; badge.textContent = 'COMPLÉTÉ'; }
    // Update validate button
    const btn = document.getElementById('btn-validate-' + n);
    if (btn) { btn.textContent = 'Validé'; btn.classList.add('done'); btn.disabled = true; }

    // ── Étape 1 validée → rend les écrans navigables, mais le LANCEMENT des
    //    agents reste séquentiel : seul Research (étape 2) devient lançable ;
    //    les étapes 3-5 restent verrouillées jusqu'à la fin de l'agent précédent.
    if (n === 1) {
      _mandateSubmitted = true;
      for (var s = 2; s <= totalSteps; s++) {
        setStepState(s, 'active'); // navigation autorisée (consultation)
      }
      refreshLaunchButtons(); // badges + boutons : seul l'agent 2 est débloqué
      updateTabs();
      updateFooter();
    }
  }

  // ── State ──
  let currentStep = 1;
  const totalSteps = 5;
  const stepLabels = ['Mandat', 'Research', 'Portfolio', 'Risque', 'Exécution'];
  let excludedIdeas = new Set();

  // ── Tab Bar ──
  var _tabsBuilt = false;

  var _LOCK_SVG = '<svg width="9" height="11" viewBox="0 0 9 11" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="1" y="4.5" width="7" height="6" rx="1.5" stroke="currentColor" stroke-width="1.2"/><path d="M3 4.5V3a1.5 1.5 0 0 1 3 0v1.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>';
  var _CHECK_SVG = '<svg width="11" height="9" viewBox="0 0 11 9" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M1 4.5l3 3 6-6" stroke="#3fb950" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function updateTabs() {
    var container = document.getElementById('tabBar');
    if (!container) return;

    if (!_tabsBuilt) {
      container.innerHTML = '';
      for (var i = 1; i <= totalSteps; i++) {
        var tab = document.createElement('div');
        tab.id = 'tab-item-' + i;
        tab.className = 'tab-item';
        tab.onclick = (function(s){ return function(){ goToStep(s); }; })(i);
        var icon = document.createElement('span');
        icon.id = 'tab-icon-' + i;
        icon.className = 'tab-icon';
        var lbl = document.createElement('span');
        lbl.textContent = stepLabels[i - 1];
        tab.appendChild(icon);
        tab.appendChild(lbl);
        container.appendChild(tab);
      }
      // ── Onglet "Marché" — toujours accessible, hors flux verrouillé ──
      var mtab = document.createElement('div');
      mtab.id = 'tab-item-market';
      mtab.className = 'tab-item';
      mtab.onclick = function(){ toggleMarket(); };
      var micon = document.createElement('span');
      micon.className = 'tab-icon';
      micon.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 17 9 11 13 15 21 7"/><polyline points="15 7 21 7 21 13"/></svg>';
      var mlbl = document.createElement('span');
      mlbl.textContent = 'Marché';
      mtab.appendChild(micon);
      mtab.appendChild(mlbl);
      container.appendChild(mtab);
      _tabsBuilt = true;
    }

    for (var j = 1; j <= totalSteps; j++) {
      var state = stepStates[j];
      var isActive = (j === currentStep);
      var tabEl  = document.getElementById('tab-item-' + j);
      var iconEl = document.getElementById('tab-icon-' + j);
      if (!tabEl || !iconEl) continue;

      var newClass, newIcon;
      if (isActive) {
        newClass = 'tab-item active';
        newIcon  = '';
      } else if (state === 'completed') {
        newClass = 'tab-item completed';
        newIcon  = _CHECK_SVG;
      } else if (state === 'locked') {
        newClass = 'tab-item tab-locked';
        newIcon  = _LOCK_SVG;
      } else {
        newClass = 'tab-item';
        newIcon  = '';
      }

      if (tabEl.className  !== newClass)   tabEl.className  = newClass;
      if (iconEl.innerHTML !== newIcon)    iconEl.innerHTML = newIcon;
    }
  }

  // Alias pour compatibilité avec les appels restants
  function buildNav() { updateTabs(); }

  function goToStep(n, forced) {
    if (n < 1 || n > totalSteps) return;
    if (!currentUser) return;
    if (stepStates[n] === 'locked') return;

    // Si l'écran Marché est ouvert, le fermer proprement avant de naviguer
    var mScreen = document.getElementById('screen-market');
    if (mScreen && mScreen.classList.contains('active')) {
      stopAutoRefresh();
      mScreen.classList.remove('active');
      var mTab = document.getElementById('tab-item-market');
      if (mTab) mTab.classList.remove('active');
    }
    if (!forced) {
      var calledByPolling = (n !== currentStep && !_mandateSubmitted);
      if (calledByPolling) return;
      var activeEl = document.activeElement;
      var userIsTyping = activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.tagName === 'SELECT');
      if (userIsTyping && n !== currentStep) return;
    }

    var prevEl = document.getElementById('screen-' + currentStep);

    // Fade out
    prevEl.style.transition = 'opacity 0.15s ease, transform 0.15s ease';
    prevEl.style.opacity    = '0';
    prevEl.style.transform  = 'translateY(-6px)';

    var nextN = n;
    setTimeout(function() {
      prevEl.classList.remove('active');
      prevEl.style.transition = '';
      prevEl.style.opacity    = '';
      prevEl.style.transform  = '';

      currentStep = nextN;
      var nextEl = document.getElementById('screen-' + currentStep);
      nextEl.classList.add('active');

      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
      updateTabs();
      updateFooter();
      window.scrollTo(0, 0);
    }, 150);

    // Mettre à jour les tabs immédiatement (sans attendre le fade)
    updateTabs();
  }

  function nextStep() {
    if (currentStep < totalSteps) {
      // Auto-complete step 5 when user moves forward (last step)
      if (currentStep === 5 && stepStates[currentStep] === 'active') {
        setStepState(currentStep, 'completed');
        const badge = document.getElementById('step-badge-' + currentStep);
        if (badge) { badge.className = 'badge badge-green'; badge.textContent = 'COMPLÉTÉ'; }
        setStepState(currentStep + 1, 'active');
      }
      goToStep(currentStep + 1);
    }
  }
  function prevStep() { if (currentStep > 1) goToStep(currentStep - 1); }

  function updateFooter() {
    document.getElementById('btnPrev').disabled = currentStep === 1;
    // L'étape 1 (mandat) requiert une validation explicite via le bouton "Valider le mandat"
    // avant que le bouton "Suivant" soit actif. Les étapes 2-4 pilotées par le polling
    // permettent la navigation manuelle dès que l'étape est 'active' ou 'completed'.
    const stepDone = stepStates[currentStep] === 'completed';
    const nextLocked = currentStep < totalSteps && stepStates[currentStep + 1] === 'locked';
    var nextDisabled;
    if (currentStep === totalSteps) {
      nextDisabled = true;
    } else if (currentStep === 1) {
      // Étape 1 : Suivant bloqué tant que le mandat n'est pas validé
      nextDisabled = !stepDone;
    } else {
      // Étapes 2+ : Suivant bloqué seulement si l'étape suivante est encore locked
      nextDisabled = nextLocked;
    }
    document.getElementById('btnNext').disabled = nextDisabled;
    document.getElementById('stepInfo').textContent = 'Étape ' + currentStep + ' / ' + totalSteps;
  }

  // ── Idea management ──
  function excludeIdea(id) {
    excludedIdeas.add(id);
    const row = document.querySelector('#ideasTable tr[data-id="' + id + '"]');
    if (row) {
      row.querySelectorAll('td:not(:last-child)').forEach(td => td.classList.add('td-struck'));
      row.style.opacity = '0.45';
    }
    updateIdeaCounter();
  }

  function keepIdea(id) {
    excludedIdeas.delete(id);
    const row = document.querySelector('#ideasTable tr[data-id="' + id + '"]');
    if (row) {
      row.querySelectorAll('td').forEach(td => td.classList.remove('td-struck'));
      row.style.opacity = '1';
    }
    updateIdeaCounter();
  }

  function updateIdeaCounter() {
    const selected = 10 - excludedIdeas.size;
    document.getElementById('ideaCounter').textContent = selected + '/10 titres sélectionnés';
  }

  // ── Sub tabs ──
  function switchSubTab(group, id, el) {
    const parentScreen = el.closest('.screen');
    parentScreen.querySelectorAll('.sub-tab').forEach(t => t.classList.remove('active'));
    parentScreen.querySelectorAll('.sub-tab-content').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
    document.getElementById(group + '-' + id).classList.add('active');
  }

  // ── Export format ──
  function selectFormat(el) {
    document.querySelectorAll('#exportFormat .radio-option').forEach(o => {
      o.classList.remove('selected');
      o.innerHTML = o.innerHTML.replace('&#9679;', '&#9675;');
    });
    el.classList.add('selected');
    el.innerHTML = el.innerHTML.replace('&#9675;', '&#9679;');
  }

  // ── PM Validation ──
  function checkApproveBtn() {
    const nameEl = document.getElementById('pmName');
    const consentEl = document.getElementById('pmConsent');
    const approveEl = document.getElementById('btnApprove');
    if (!nameEl || !consentEl || !approveEl) return;
    approveEl.disabled = !(nameEl.value.trim() && consentEl.checked);
  }

  function approveOrders() {
    setTimeout(() => {
      document.getElementById('successOverlay').classList.add('show');
    }, 200);
  }

  // ── Reject modal ──
  function openRejectModal() {
    document.getElementById('rejectModal').classList.add('show');
  }

  function closeRejectModal() {
    document.getElementById('rejectModal').classList.remove('show');
  }

  function confirmReject() {
    document.getElementById('rejectModal').classList.remove('show');
    // Reset to step 1
    document.getElementById('pmName').value = '';
    document.getElementById('pmConsent').checked = false;
    document.getElementById('pmComment').value = '';
    document.getElementById('rejectReason').value = '';
    checkApproveBtn();
    // Reset all step states
    for (let i = 1; i <= 5; i++) { stepStates[i] = 'locked'; }
    setStepState(1, 'active');
    // Reset séquençage des agents : verrou relâché, pipeline remis à zéro
    _mandateSubmitted = false;
    agentRunning = false;
    _agentCompleted = { 2:false, 3:false, 4:false, 5:false };
    // Reset all badges
    for (let i = 1; i <= 5; i++) {
      const b = document.getElementById('step-badge-' + i);
      if (b) { b.className = 'badge badge-locked'; b.textContent = 'VERROUILLÉ'; }
      const vb = document.getElementById('btn-validate-' + i);
      if (vb) { vb.textContent = vb.getAttribute('data-orig') || vb.textContent; vb.classList.remove('done'); vb.disabled = false; }
      const lb = document.getElementById('launch-btn-' + i);
      if (lb) { delete lb.dataset.running; lb.textContent = 'Lancer l\'agent'; lb.title = ''; }
    }
    refreshLaunchButtons();
    goToStep(1);
    // Visual feedback
    alert('Workflow rejeté. Retour à l\'étape 1 — Mandate Agent.');
  }

  // ── Init ──
  buildNav();
  updateFooter();
  refreshLaunchButtons(); // au chargement : tous les boutons "Lancer" désactivés tant que le mandat n'est pas validé

  // ── Report modals ──
  // Les modales de rapports de demonstration ont ete retirees : on ouvre
  // desormais le rapport HTML reellement produit par l'agent (defaut F1).
  function openReport(id) {
    window.open(API_BASE + '/api/report/' + encodeURIComponent(String(id).toUpperCase()), '_blank');
  }

  function closeReport(id) {
    const el = document.getElementById('report-' + id);
    if (el) {
      el.classList.remove('show');
      document.body.style.overflow = '';
    }
  }

  // Close on Escape key
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      document.querySelectorAll('.report-modal.show').forEach(function(m) {
        m.classList.remove('show');
        document.body.style.overflow = '';
      });
    }
  });
