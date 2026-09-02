
  // ── Mandate Analysis ──
  function analyzeMandate() {
    // Validate required fields
    const required = ['m-strategie','m-capital','m-benchmark','m-horizon','m-te','m-vol','m-dd','m-turnover','m-beta-min','m-beta-max','m-pos-min','m-pos-max','m-cash-max','m-profil','m-perte-max','m-recovery','m-liquidite','m-sensibilite'];
    const missing = required.filter(function(id){ const el = document.getElementById(id); return !el || !el.value; });
    if (missing.length > 0) {
      alert('Veuillez renseigner tous les champs obligatoires avant de lancer l\'analyse.');
      document.getElementById(missing[0]).focus();
      return;
    }
    // Collect values
    const strat   = document.getElementById('m-strategie').value;
    const capital = parseFloat(document.getElementById('m-capital').value);
    const bench   = document.getElementById('m-benchmark').value;
    const horizon = document.getElementById('m-horizon').value;
    const te      = parseFloat(document.getElementById('m-te').value);
    const vol     = parseFloat(document.getElementById('m-vol').value);
    const dd      = parseFloat(document.getElementById('m-dd').value);
    const turnover= parseFloat(document.getElementById('m-turnover').value);
    const betaMin = parseFloat(document.getElementById('m-beta-min').value);
    const betaMax = parseFloat(document.getElementById('m-beta-max').value);
    const posMin  = parseFloat(document.getElementById('m-pos-min').value);
    const posMax  = parseFloat(document.getElementById('m-pos-max').value);
    const cashMax = parseFloat(document.getElementById('m-cash-max').value);
    const esgScore   = document.getElementById('m-esg-score').value;
    const profil     = document.getElementById('m-profil').value;
    const perteMax   = parseFloat(document.getElementById('m-perte-max').value);
    const recovery   = document.getElementById('m-recovery').value;
    const liquidite  = document.getElementById('m-liquidite').value;
    const sensibilite= document.getElementById('m-sensibilite').value;
    const prioriteEl = document.querySelector('input[name="m-priorite"]:checked');
    const priorite   = prioriteEl ? prioriteEl.value : 'Croissance long terme';

    // Show loading
    document.getElementById('mandate-phase1').style.display = 'none';
    document.getElementById('mandate-loading').style.display = '';
    const fill = document.getElementById('aiLoadingFill');
    const txt  = document.getElementById('aiLoadingText');
    const steps_ai = ['Validation des paramètres...','Vérification des contraintes de risque...','Analyse de cohérence du mandat...','Calcul des optimisations...','Finalisation du diagnostic...'];
    let pct = 0; let si = 0;
    const iv = setInterval(function(){
      pct = Math.min(pct + 4, 95);
      fill.style.width = pct + '%';
      if (si < steps_ai.length && pct > si * 20) { txt.textContent = steps_ai[si]; si++; }
    }, 100);
    setTimeout(function(){
      clearInterval(iv);
      fill.style.width = '100%';
      setTimeout(function(){
        document.getElementById('mandate-loading').style.display = 'none';
        // Build KPI summary
        var capStr = '$' + (capital >= 1e9 ? (capital/1e9).toFixed(1)+'Mrd' : (capital/1e6).toFixed(0)+'M');
        var kpiHTML = [
          ['','Stratégie',strat,'white'],
          ['','Capital',capStr,'green'],
          ['','Benchmark',bench,'white'],
          ['','Horizon',horizon,'blue'],
          ['','Tracking Error',te+'%','gold'],
          ['','Volatilité Max',vol+'%','gold'],
          ['','Drawdown Max',dd+'%','gold'],
          ['','Beta Range',betaMin+' – '+betaMax,'blue']
        ].map(function(k){ return '<div class="mandate-kpi-card"><div class="mandate-kpi-body"><div class="mandate-kpi-label">'+k[1]+'</div><div class="mandate-kpi-value '+k[3]+'" style="font-size:12px;">'+k[2]+'</div></div></div>'; }).join('');
        document.getElementById('mandate-kpi-summary').innerHTML = kpiHTML;
        // Build AI critique dynamically
        var forts = [];
        var alertes = [];
        var optims = [];
        if (te <= 6) forts.push(['ok','','Tracking Error de '+te+'% bien calibré pour une gestion active disciplinée.']);
        if (capital >= 50e6) forts.push(['ok','','Taille du fonds ('+capStr+') suffisante pour une diversification optimale.']);
        if (horizon.includes('3-5') || horizon.includes('5-10')) forts.push(['ok','','Horizon '+horizon+' cohérent avec une stratégie actions long-only.']);
        if (esgScore === 'AA' || esgScore === 'A') forts.push(['ok','','Score ESG exigeant ('+esgScore+') — positionnement différenciant sur le marché.']);
        // Cohérence profil vs contraintes
        if (profil === 'Conservateur' && vol <= 15) forts.push(['ok','','Profil '+profil+' cohérent avec une volatilité max de '+vol+'% — bonne adéquation risque/mandat.']);
        if (profil === 'Équilibré' && vol >= 12 && vol <= 20) forts.push(['ok','','Profil '+profil+' aligné avec une volatilité max de '+vol+'% — équilibre rendement/risque respecté.']);
        if (profil === 'Agressif' && vol >= 18) forts.push(['ok','','Profil '+profil+' aligné avec la tolérance volatilité déclarée ('+vol+'%).']);
        if (perteMax >= dd) forts.push(['ok','','Perte max tolérée ('+perteMax+'%) compatible avec le drawdown max fixé ('+dd+'%).']);
        if (liquidite === 'Faible' && posMax <= 8) forts.push(['ok','','Besoin de liquidité faible — cohérent avec des positions concentrées jusqu\'à '+posMax+'%.']);
        if (forts.length === 0) forts.push(['ok','','Paramètres enregistrés. Analyse de cohérence effectuée.']);
        if (te > 8) alertes.push(['warn','','Tracking Error de '+te+'% est élevé — risque de déviation significative du benchmark '+bench+'.']);
        if (vol > 22) alertes.push(['warn','','Volatilité max de '+vol+'% dépasse les standards institutionnels (≤20% recommandé).']);
        if (dd > 25) alertes.push(['warn','','Drawdown de '+dd+'% peut déclencher des clauses de rachat. Limite recommandée : 20%.']);
        if (betaMax - betaMin > 0.6) alertes.push(['warn','','Plage Beta étendue ('+betaMin+'-'+betaMax+') — exposition directionnelle potentiellement forte.']);
        if (posMax > 8) alertes.push(['warn','','Position max de '+posMax+'% est concentrée. Risque idiosyncratique non négligeable.']);
        if (turnover > 60) alertes.push(['warn','','Turnover de '+turnover+'% génère des coûts de transaction significatifs (+15-20 bps estimés).']);
        // Incohérences profil / contraintes
        if (profil === 'Conservateur' && vol > 15) alertes.push(['warn','','Incohérence : profil Conservateur mais volatilité max de '+vol+'% — recommandé ≤ 12%.']);
        if (profil === 'Agressif' && dd < 20) alertes.push(['warn','','Profil Agressif avec drawdown max de '+dd+'% semble restrictif — envisager 25-35%.']);
        if (perteMax < dd) alertes.push(['warn','','Perte max tolérée ('+perteMax+'%) inférieure au drawdown max autorisé ('+dd+'%) — risque de clause de rachat.']);
        if (sensibilite === 'Élevée' && vol > 18) alertes.push(['warn','','Forte sensibilité aux marchés + volatilité max de '+vol+'% — risque comportemental élevé en période de correction.']);
        if (liquidite === 'Élevé' && posMax > 6) alertes.push(['warn','','Besoin de liquidité élevé mais positions jusqu\'à '+posMax+'% — réduire à 5% max pour garantir la liquidité.']);

        // Incohérences priorité principale / contraintes de risque
        if (priorite === 'Préservation du capital') {
          if (vol > 12)    alertes.push(['warn','','Incohérence stratégique : priorité "Préservation du capital" mais volatilité max de '+vol+'% — recommandé ≤ 10-12%.']);
          if (dd  > 10)    alertes.push(['warn','','Incohérence stratégique : priorité "Préservation du capital" mais drawdown max de '+dd+'% — recommandé ≤ 8-10%.']);
          if (betaMax > 0.90) alertes.push(['warn','','Incohérence stratégique : priorité "Préservation du capital" mais beta max de '+betaMax+' — défensif requiert beta ≤ 0.85.']);
          if (profil === 'Agressif') alertes.push(['warn','','Contradiction majeure : priorité "Préservation du capital" incompatible avec profil '+profil+'.']);
          if (perteMax > 10) alertes.push(['warn','','Incohérence : "Préservation du capital" tolère au maximum une perte de 8-10%, pas '+perteMax+'%.']);
        }
        if (priorite === 'Croissance long terme') {
          if (vol < 15)     alertes.push(['warn','','Incohérence stratégique : priorité "Croissance long terme" nécessite une volatilité max ≥ 15-22% (actuel : '+vol+'%).']);
          if (betaMax < 0.95) alertes.push(['warn','','Incohérence stratégique : priorité "Croissance long terme" incompatible avec beta max '+betaMax+' — croissance requiert beta 1.0-1.4.']);
          if (profil === 'Conservateur') alertes.push(['warn','','Contradiction majeure : priorité "Croissance long terme" incompatible avec profil Conservateur.']);
        }
        if (priorite === 'Revenus réguliers' && betaMax > 1.10) alertes.push(['warn','','Incohérence : priorité "Revenus réguliers" privilégie défensif/dividendes, beta max '+betaMax+' trop élevé (≤ 1.10 recommandé).']);
        if (priorite === 'Performance maximale' && profil === 'Conservateur') alertes.push(['warn','','Contradiction majeure : priorité "Performance maximale" incompatible avec profil '+profil+'.']);
        if (alertes.length === 0) alertes.push(['ok','','Aucune anomalie critique détectée dans les contraintes de risque.']);
        optims.push(['info','','Recommandé : réduire Position Max à '+ Math.min(posMax, 7)+'% et Position Min à '+Math.max(posMin,1)+'% pour 25-30 positions cibles.']);
        if (cashMax > 8) optims.push(['info','','Réduire cash max à 8% pour optimiser le taux d\'exposition actions (coût d\'opportunité actuel : ~'+(cashMax-5)*0.12+'% p.a.).']);
        if (turnover > 40) optims.push(['info','','Turnover recommandé : 30-40% pour réduire les coûts de friction tout en maintenant la réactivité.']);
        optims.push(['info','','Ajouter contrainte sectorielle : max 30% par secteur GICS pour éviter la concentration technologie.']);
        if (priorite === 'Préservation du capital') optims.push(['info','','Priorité "Préservation du capital" → envisager une poche obligataire 10-15% ou une overlay de couverture systématique.']);
        if (priorite === 'Revenus réguliers') optims.push(['info','','Priorité "Revenus réguliers" → cibler dividendes ≥ 2.5%, biais value/quality pour stabilité des flux.']);
        if (recovery === '3 mois' || recovery === '6 mois') optims.push(['info','','Horizon de récupération court ('+recovery+') → limiter l\'exposition aux valeurs cycliques et aux small caps.']);
        if (sensibilite === 'Élevée') optims.push(['info','','Sensibilité élevée → activer une règle de stop-loss dynamique à -8% par position pour limiter l\'impact psychologique.']);
        document.getElementById('ai-points-forts').innerHTML = forts.map(function(f){ return '<div class="ai-suggestion-item '+f[0]+'"><span class="ai-suggestion-icon">'+f[1]+'</span><span>'+f[2]+'</span></div>'; }).join('');
        document.getElementById('ai-alertes').innerHTML = alertes.map(function(a){ return '<div class="ai-suggestion-item '+a[0]+'"><span class="ai-suggestion-icon">'+a[1]+'</span><span>'+a[2]+'</span></div>'; }).join('');
        document.getElementById('ai-optimisations').innerHTML = optims.map(function(o){ return '<div class="ai-suggestion-item '+o[0]+'"><span class="ai-suggestion-icon">'+o[1]+'</span><span>'+o[2]+'</span></div>'; }).join('');
        document.getElementById('mandate-phase3').style.display = '';
      }, 200);
    }, 3500);
  }

  function resetAnalysis() {
    document.getElementById('mandate-phase3').style.display = 'none';
    document.getElementById('mandate-phase1').style.display = '';
    document.getElementById('aiLoadingFill').style.width = '0';
  }
