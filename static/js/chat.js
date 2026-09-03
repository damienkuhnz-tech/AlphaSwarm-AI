
  // ── Chat - per-agent conversation histories ──
  var _chatHistories = { 2: [], 3: [], 4: [], 5: [] };
  var _agentNames = { 2: 'research', 3: 'portfolio', 4: 'risk', 5: 'execution' };

  function switchAgentTab(tabEl, panelId) {
    var container = tabEl.closest('.agent-sub-tabs');
    if (!container) return;
    container.querySelectorAll('.agent-sub-tab').forEach(function(t) { t.classList.remove('active'); });
    tabEl.classList.add('active');
    var screen = tabEl.closest('.screen');
    if (!screen) return;
    screen.querySelectorAll('.agent-tab-content').forEach(function(p) { p.classList.remove('active'); });
    var panel = document.getElementById(panelId);
    if (panel) panel.classList.add('active');
  }

  // Mini parser Markdown → HTML. Couvre : gras, italique, code inline, code blocks,
  // titres h1-h4, listes -/*/+ et 1., tableaux | | |, liens [txt](url), citations >,
  // sauts de ligne et paragraphes. Échappe le HTML en entrée.
  function _mdToHtml(src) {
    if (!src) return '';
    // 0. Supprimer tous les emojis (plages Unicode standard) et caractères de présentation
    var s = String(src).replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}\u{FE00}-\u{FE0F}\u{2700}-\u{27BF}\u{2300}-\u{23FF}\u{2B00}-\u{2BFF}\u{2900}-\u{297F}\u{2190}-\u{21FF}\u{25A0}-\u{25FF}]/gu, '');
    // Nettoyer les espaces orphelins laissés par les emojis retirés
    s = s.replace(/  +/g, ' ').replace(/^[ \t]+/gm, function(m){ return m; });
    // 1. Échapper HTML
    // Le guillemet DOIT etre echappe : l'etape 7 construit href="$2" a partir
    // d'un lien markdown, et une URL contenant un guillemet sortait de
    // l'attribut - injection possible via une reponse du modele (defaut A5).
    s = s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');

    // 2. Code blocks ```…```
    s = s.replace(/```([\s\S]*?)```/g, function(_, code) {
      return '<pre class="md-pre"><code>' + code.replace(/^\n/, '') + '</code></pre>';
    });

    // 3. Tableaux (détecter blocs | col | col |)
    s = s.replace(/((?:^\|.*\|\s*\n)+)/gm, function(block) {
      var lines = block.trim().split('\n');
      if (lines.length < 2) return block;
      // La 2e ligne doit être un séparateur |---|---|
      if (!/^\|[\s\-:|]+\|\s*$/.test(lines[1])) return block;
      var headers = lines[0].split('|').slice(1, -1).map(function(c){ return c.trim(); });
      var rows = lines.slice(2).map(function(ln) {
        return ln.split('|').slice(1, -1).map(function(c){ return c.trim(); });
      });
      // Enveloppe defilante : les colonnes d'un tableau markdown viennent du LLM
      // et peuvent etre arbitrairement larges. Sans ce conteneur, c'est le corps
      // de page qui defile horizontalement sur mobile.
      var out = '<div class="md-table-wrap"><table class="md-table"><thead><tr>';
      headers.forEach(function(h){ out += '<th>' + h + '</th>'; });
      out += '</tr></thead><tbody>';
      rows.forEach(function(r) {
        out += '<tr>';
        r.forEach(function(c){ out += '<td>' + c + '</td>'; });
        out += '</tr>';
      });
      out += '</tbody></table></div>';
      return out;
    });

    // 4. Titres
    s = s.replace(/^#### (.+)$/gm, '<h4 class="md-h4">$1</h4>');
    s = s.replace(/^### (.+)$/gm,  '<h3 class="md-h3">$1</h3>');
    s = s.replace(/^## (.+)$/gm,   '<h2 class="md-h2">$1</h2>');
    s = s.replace(/^# (.+)$/gm,    '<h1 class="md-h1">$1</h1>');

    // 5. Citations > ...
    s = s.replace(/^&gt; (.+)$/gm, '<blockquote class="md-quote">$1</blockquote>');

    // 6. Listes - on regroupe les lignes consécutives qui commencent par - * + ou 1.
    s = s.replace(/((?:^[ \t]*[-*+] .+(?:\n|$))+)/gm, function(block) {
      var items = block.trim().split(/\n/).map(function(l) {
        return '<li>' + l.replace(/^[ \t]*[-*+] /, '') + '</li>';
      }).join('');
      return '<ul class="md-list">' + items + '</ul>';
    });
    s = s.replace(/((?:^[ \t]*\d+\. .+(?:\n|$))+)/gm, function(block) {
      var items = block.trim().split(/\n/).map(function(l) {
        return '<li>' + l.replace(/^[ \t]*\d+\. /, '') + '</li>';
      }).join('');
      return '<ol class="md-list">' + items + '</ol>';
    });

    // 7. Liens [texte](url)
    // Seuls http(s) et mailto sont acceptes : javascript: et data: sont rendus
    // en texte, jamais en lien cliquable (defaut A5).
    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (whole, label, url) {
      var clean = String(url).trim();
      if (!/^(https?:|mailto:)/i.test(clean)) return label;
      return '<a href="' + clean + '" target="_blank" rel="noopener noreferrer" class="md-link">' + label + '</a>';
    });

    // 8. Gras ** ** et __ __
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/__([^_]+)__/g,      '<strong>$1</strong>');

    // 9. Italique * * et _ _  (éviter de toucher les ** déjà remplacés)
    s = s.replace(/(^|[^*])\*([^*\n]+)\*([^*]|$)/g, '$1<em>$2</em>$3');
    s = s.replace(/(^|[^_])_([^_\n]+)_([^_]|$)/g,    '$1<em>$2</em>$3');

    // 10. Code inline `…`
    s = s.replace(/`([^`\n]+)`/g, '<code class="md-code">$1</code>');

    // 11. Séparateurs horizontaux
    s = s.replace(/^---+$/gm, '<hr class="md-hr">');

    // 12. Paragraphes : wrap les lignes qui ne sont pas déjà dans un bloc HTML
    var lines = s.split(/\n\n+/);
    s = lines.map(function(block) {
      var trimmed = block.trim();
      if (!trimmed) return '';
      // Si déjà un bloc HTML, ne pas wrapper
      // `div` couvre l'enveloppe defilante des tableaux (.md-table-wrap) : sans
      // lui, la table serait re-enveloppee dans un <p>, ce qui est invalide.
      if (/^<(h[1-6]|ul|ol|table|pre|blockquote|hr|div)/.test(trimmed)) return trimmed;
      // Remplacer les \n simples par <br>
      return '<p class="md-p">' + trimmed.replace(/\n/g, '<br>') + '</p>';
    }).join('');

    return s;
  }

  function _appendChatMessage(screenNum, role, text) {
    var msgs = document.getElementById('chat-messages-' + screenNum);
    if (!msgs) return;
    var wrap = document.createElement('div');
    wrap.className = 'chat-msg ' + (role === 'user' ? 'user' : 'agent');
    var avatar = document.createElement('div');
    avatar.className = 'chat-avatar ' + (role === 'user' ? 'avatar-user' : 'avatar-agent');
    avatar.textContent = role === 'user' ? 'PM' : 'AI';
    var body = document.createElement('div');
    var sender = document.createElement('div');
    sender.className = 'chat-sender';
    sender.textContent = role === 'user' ? 'Portfolio Manager' : (_agentNames[screenNum] === 'research' ? 'Assistant Analyste' : _agentNames[screenNum] === 'portfolio' ? 'Portfolio Manager AI' : _agentNames[screenNum] === 'risk' ? 'Risk Analyst' : 'Execution Trader');
    var bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    // User en texte brut, agent en markdown rendu
    if (role === 'user') {
      bubble.textContent = text;
    } else {
      bubble.innerHTML = _mdToHtml(text);
    }
    body.appendChild(sender);
    body.appendChild(bubble);
    wrap.appendChild(avatar);
    wrap.appendChild(body);
    msgs.appendChild(wrap);
    msgs.scrollTop = msgs.scrollHeight;
  }

  // Contexte de chat - RESUME, pas l'etat complet.
  // Auparavant portfolio/risk/execution etaient serialises entiers et joints a
  // CHAQUE message : volume reseau et tokens payes a chaque question, alors que
  // le serveur tronque de toute facon ce bloc a 2500 caracteres (api.py,
  // other_ctx). Un portefeuille complet depassant ce seuil, le contexte partait
  // coupe au milieu d'un JSON et les donnees utiles (risque, execution) etaient
  // perdues. On n'envoie donc que ce qui sert reellement au dialogue.
  // Exclus volontairement : backtest.courbe_valeur (points base 100),
  // validation_quantitative complete, narratifs de recherche, justifications.
  function _buildChatContext(screenNum) {
    var ctx = {};

    // ── Portefeuille : positions reduites a l'identite + le poids ──
    if (_lastPortfolioJSON) {
      try {
        var p = JSON.parse(_lastPortfolioJSON);
        ctx.portfolio = {
          capital_total:     p.capital_total,
          nombre_positions:  p.nombre_positions || (p.positions || []).length,
          cash_poids:        p.cash_poids,
          positions: (p.positions || []).map(function (x) {
            return {
              ticker:  x.ticker,
              nom:     x.nom,
              secteur: x.secteur,
              poids:   x.poids
            };
          })
        };
      } catch (e) {}
    }

    // ── Risque : statut, violations et metriques cles ──
    if (_lastRiskJSON) {
      try {
        var r = JSON.parse(_lastRiskJSON);
        var m = r.metriques_risque || {};
        ctx.risk = {
          statut:              r.statut,
          score_risque_global: r.score_risque_global,
          metriques: {
            volatilite_estimee:     m.volatilite_estimee,
            tracking_error_estimee: m.tracking_error_estimee,
            beta_estime:            m.beta_estime,
            concentration_top1:     m.concentration_top1,
            concentration_top5:     m.concentration_top5,
            concentration_top10:    m.concentration_top10
          },
          violations: (r.violations || []).map(function (v) {
            return { type: v.type, severite: v.severite, detail: v.detail };
          })
        };
      } catch (e) {}
    }

    // ── Execution : volumetrie et cout, pas le detail des ordres ──
    if (_lastExecutionJSON) {
      try {
        var e2 = JSON.parse(_lastExecutionJSON);
        var c = e2.couts_transaction || {};
        ctx.execution = {
          nombre_ordres:   e2.nombre_ordres || (e2.ordres || []).length,
          capital_investi: e2.capital_investi,
          statut:          e2.statut,
          cout_total_usd:  c.total_estime_usd,
          cout_total_bps:  c.total_bps
        };
      } catch (e) {}
    }

    return ctx;
  }

  function sendChatMessage(screenNum) {
    var input = document.getElementById('chat-input-' + screenNum);
    if (!input) return;
    var text = input.value.trim();
    if (!text) return;

    // Hide suggestions after first message
    var suggestions = document.getElementById('chat-suggestions-' + screenNum);
    if (suggestions) suggestions.style.display = 'none';

    _appendChatMessage(screenNum, 'user', text);
    _chatHistories[screenNum].push({ role: 'user', content: text });
    input.value = '';
    input.style.height = 'auto';

    // Typing indicator
    var msgs = document.getElementById('chat-messages-' + screenNum);
    var typingId = 'typing-' + screenNum + '-' + Date.now();
    if (msgs) {
      var typing = document.createElement('div');
      typing.id = typingId;
      typing.className = 'chat-msg agent';
      typing.innerHTML = '<div class="chat-avatar avatar-agent">AI</div><div><div class="chat-sender">...</div><div class="chat-bubble"><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span></div></div>';
      msgs.appendChild(typing);
      msgs.scrollTop = msgs.scrollHeight;
    }

    var agentName = _agentNames[screenNum] || 'research';
    var context = _buildChatContext(screenNum);

    // Détection côté frontend : demande de rapport sur un ticker ?
    var reportTicker = _detectReportRequest(text);
    if (agentName === 'research' && reportTicker) {
      // Court-circuit : on ne passe pas par le LLM, on génère directement
      var typingEl = document.getElementById(typingId);
      if (typingEl) typingEl.remove();
      var ackMsg = 'Génération du rapport equity research pour **' + reportTicker + '** en cours. Cela prend quelques secondes...';
      _chatHistories[screenNum].push({ role: 'assistant', content: ackMsg });
      _appendChatMessage(screenNum, 'assistant', ackMsg);
      _appendReportButtons(screenNum, reportTicker);
      return;
    }

    fetch(API_BASE + '/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent: agentName, messages: _chatHistories[screenNum], context: context })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var typingEl = document.getElementById(typingId);
      if (typingEl) typingEl.remove();
      var reply = data.reply || data.error || 'Erreur de réponse.';
      _chatHistories[screenNum].push({ role: 'assistant', content: reply });
      _appendChatMessage(screenNum, 'assistant', reply);

      // Si la réponse de l'agent mentionne un ticker + rapport, afficher boutons
      var replyTicker = _detectReportRequest(reply);
      if (agentName === 'research' && replyTicker) {
        _appendReportButtons(screenNum, replyTicker);
      }
    })
    .catch(function(err) {
      var typingEl = document.getElementById(typingId);
      if (typingEl) typingEl.remove();
      _appendChatMessage(screenNum, 'assistant', 'Erreur de connexion. Vérifiez que l\'API est démarrée.');
    });
  }

  // Détecte si un message demande un rapport sur un ticker précis.
  // Retourne le ticker (ex: "NVDA") ou null.
  function _detectReportRequest(text) {
    if (!text) return null;
    var lower = text.toLowerCase();
    var reportKeywords = ['rapport', 'report', 'analyse', 'analyze', 'research', 'fiche', 'étude', 'genere', 'génère', 'génér', 'crée', 'produis', 'make', 'generate', 'create', 'détail', 'detail'];
    var hasReportWord = reportKeywords.some(function(k) { return lower.indexOf(k) !== -1; });
    if (!hasReportWord) return null;
    // Cherche un ticker : mot en majuscules 2-6 chars (ex: NVDA, MSFT, BRK.B)
    var tickerMatch = text.match(/\b([A-Z]{2,6}(?:\.[A-Z]{1,2})?)\b/);
    if (tickerMatch) return tickerMatch[1];
    // Cherche des noms d'entreprises connus
    var companyMap = {
      'nvidia': 'NVDA', 'apple': 'AAPL', 'microsoft': 'MSFT', 'amazon': 'AMZN',
      'google': 'GOOGL', 'alphabet': 'GOOGL', 'meta': 'META', 'tesla': 'TSLA',
      'asml': 'ASML', 'visa': 'V', 'jpmorgan': 'JPM', 'jp morgan': 'JPM',
      'eli lilly': 'LLY', 'novo nordisk': 'NVO', 'sap': 'SAP', 'caterpillar': 'CAT',
      'tsmc': 'TSM', 'nestlé': 'NESN', 'nestle': 'NESN', 'reliance': 'RELIANCE',
    };
    for (var name in companyMap) {
      if (lower.indexOf(name) !== -1) return companyMap[name];
    }
    return null;
  }

  function _appendReportButtons(screenNum, ticker) {
    var msgs = document.getElementById('chat-messages-' + screenNum);
    if (!msgs) return;

    var wrap = document.createElement('div');
    wrap.className = 'chat-msg agent';
    wrap.innerHTML =
      '<div class="chat-avatar avatar-agent">AI</div>' +
      '<div style="flex:1">' +
        '<div class="chat-sender">Génération du rapport</div>' +
        '<div class="chat-bubble" id="report-status-' + screenNum + '-' + ticker + '">' +
          'Génération du rapport <strong>' + ticker + '</strong> en cours...' +
          '<span style="margin-left:8px"><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span></span>' +
        '</div>' +
      '</div>';
    msgs.appendChild(wrap);
    msgs.scrollTop = msgs.scrollHeight;

    // Appel API génération rapport
    fetch(API_BASE + '/api/chat-report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker: ticker, lang: 'fr' })
    })
    .then(function(r) { return r.json(); })
    .then(function(result) {
      var statusEl = document.getElementById('report-status-' + screenNum + '-' + ticker);
      if (result.error) {
        if (statusEl) statusEl.innerHTML = '⚠ Erreur : ' + result.error;
        return;
      }
      var htmlUrl = result.html_url ? (API_BASE + result.html_url) : null;
      var pdfUrl  = result.pdf_url  ? (API_BASE + result.pdf_url)  : null;
      if (statusEl) {
        statusEl.innerHTML =
          'Rapport <strong>' + (result.name || ticker) + '</strong> prêt.' +
          '<div style="margin-top:10px;display:flex;gap:10px;flex-wrap:wrap;">' +
          (htmlUrl ? '<button type="button" class="btn-report-dl btn-report-html" data-url="' + htmlUrl + '">Ouvrir HTML</button> ' : '') +
          (pdfUrl  ? '<button type="button" class="btn-report-dl btn-report-pdf"  data-url="' + pdfUrl  + '">Télécharger PDF</button>' : '') +
          '</div>';
        statusEl.querySelectorAll('button[data-url]').forEach(function(btn) {
          btn.addEventListener('click', function(e) {
            e.preventDefault(); e.stopPropagation();
            window.open(btn.getAttribute('data-url'), '_blank');
          });
        });
      }
    })
    .catch(function() {
      var statusEl = document.getElementById('report-status-' + screenNum + '-' + ticker);
      if (statusEl) statusEl.innerHTML = '⚠ Erreur de connexion lors de la génération.';
    });
  }

  function injectSuggestion(screenNum, el) {
    var input = document.getElementById('chat-input-' + screenNum);
    if (!input) return;
    input.value = el.textContent;
    input.focus();
  }

  function handleChatKey(event, screenNum) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      event.stopPropagation();
      sendChatMessage(screenNum);
    }
  }
