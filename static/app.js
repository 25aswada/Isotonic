
'use strict';

// ── Theme ───────────────────────────────────────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem('isotonic-theme');
  if (saved === 'light') document.body.classList.add('light');
}

function toggleTheme() {
  const isLight = document.body.classList.toggle('light');
  localStorage.setItem('isotonic-theme', isLight ? 'light' : 'dark');
  if (window.lucide) lucide.createIcons();
  if (window.Plotly) {
    const _pt = _plotTheme();
    document.querySelectorAll('.js-plotly-plot').forEach(el => {
      try { Plotly.relayout(el, { paper_bgcolor: _pt.paper_bgcolor, plot_bgcolor: _pt.plot_bgcolor }); } catch(e) {}
    });
  }
}

function _createIcons() {
  if (window.lucide) lucide.createIcons();
}

function _plotTheme() {
  const l = document.body.classList.contains('light');
  return {
    template: l ? 'plotly_white' : 'plotly_dark',
    paper_bgcolor: l ? '#ffffff' : '#000000',
    plot_bgcolor: l ? '#f2f2f7' : '#111111'
  };
}


// ── NCAA Team Colors ─────────────────────────────────────────────────────────
const NCAA_TEAM_COLORS = {
  // ACC
  'Duke':'#003087','North Carolina':'#7BAFD4','NC State':'#CC0000',
  'Clemson':'#F56600','Miami (FL)':'#005030','Virginia':'#232D4B',
  'Louisville':'#AD0000','Syracuse':'#D44500','Georgia Tech':'#B3A369',
  'Wake Forest':'#9E7E38','Boston College':'#8B0000','Notre Dame':'#C99700',
  'Pittsburgh':'#003594','Florida St.':'#782F40',
  // Big Ten
  'Michigan':'#00274C','Michigan St.':'#18453B','Ohio St.':'#BB0000',
  'Illinois':'#E84A27','Indiana':'#990000','Iowa':'#FFCD00',
  'Maryland':'#E03A3E','Minnesota':'#7A0019','Nebraska':'#E41C38',
  'Northwestern':'#4E2A84','Penn St.':'#041E42','Purdue':'#CEB888',
  'Rutgers':'#CC0033','Wisconsin':'#C5050C',
  // Big 12
  'Kansas':'#0051A5','Kansas St.':'#512888','Oklahoma':'#841617',
  'Oklahoma St.':'#FF7300','Texas':'#BF5700','Texas Tech':'#CC0000',
  'Baylor':'#003015','TCU':'#4D1979','Iowa St.':'#C8102E',
  'West Virginia':'#002855','UCF':'#FFC904','BYU':'#002E5D',
  'Cincinnati':'#E00122','Houston':'#C8102E',
  // SEC
  'Alabama':'#9E1B32','Arkansas':'#9D2235','Auburn':'#03244D',
  'Florida':'#0021A5','Georgia':'#BA0C2F','Kentucky':'#0033A0',
  'LSU':'#461D7C','Mississippi St.':'#660000','Missouri':'#F1B82D',
  'Ole Miss':'#CE1126','South Carolina':'#73000A','Tennessee':'#FF8200',
  'Texas A&M':'#500000','Vanderbilt':'#866D4B',
  // Big East
  'Connecticut':'#000E2F','Villanova':'#00205B','Marquette':'#003087',
  'Georgetown':'#041E42','Providence':'#002147','Creighton':'#005CA9',
  "St. John's":'#BA0C2F','Butler':'#13294B','DePaul':'#005EB8',
  'Seton Hall':'#005EB8','Xavier':'#0C2340',
  // Pac-12 / West
  'Arizona':'#003366','Arizona St.':'#8C1D40','UCLA':'#2D68C4',
  'USC':'#990000','Oregon':'#154733','Oregon St.':'#DC4405',
  'Washington':'#4B2E83','Washington St.':'#981E32','Utah':'#CC0000',
  'Colorado':'#CFB87C','Stanford':'#8C1515','Cal':'#003262',
  // AAC / American
  'Memphis':'#003087','SMU':'#0038A8','Tulsa':'#004371',
  'South Florida':'#006747','Temple':'#9D2235','Wichita St.':'#003460',
  // Mountain West
  'San Diego St.':'#C41230','UNLV':'#CF0A2C','Utah St.':'#0F1E7A',
  'Boise St.':'#0033A0','Nevada':'#003366','Air Force':'#003087',
  'New Mexico':'#BA0C2F','Wyoming':'#492F24','Colorado St.':'#1E4D2B',
  // A-10 / Atlantic 10
  'Saint Louis':'#003DA5',"Saint Mary's":'#002147','Dayton':'#CE1141',
  'VCU':'#000000','Richmond':'#990000','George Mason':'#006633',
  'La Salle':'#00539B','Fordham':'#780023','Davidson':'#CC0000',
  'Rhode Island':'#002147',
  // HBCU / Mid-Major
  'Howard':'#003A86','Florida A&M':'#FF8C00','Grambling':'#000000',
  'Tennessee St.':'#4B92DB','Sam Houston':'#F77F00','Santa Clara':'#862633',
  'North Carolina A&T':'#004684',
  // Misc
  'Gonzaga':'#002868',"Saint Peter's":'#004A97','Murray St.':'#002B5C',
  'Norfolk St.':'#005030','Texas Southern':'#9C1C31','Loyola Chicago':'#82001E',
  'Belmont':'#C8102E','Oral Roberts':'#F0AB00','Iona':'#8B0000',
  'Yale':'#00356B','Harvard':'#A51C30','Princeton':'#E87722',
  'Penn':'#011F5B','Cornell':'#B31B1B','Brown':'#4E3629',
  'Colgate':'#821019','Bucknell':'#002663',
};

// NCAA abbreviation → color (for live game cards)
const NCAA_ABBREV_COLORS = {
  'ALA':'#9E1B32','ARK':'#9D2235','ARIZ':'#003366','ASU':'#8C1D40',
  'AUB':'#03244D','BAY':'#003015','BC':'#8B0000','BYU':'#002E5D',
  'CLEM':'#F56600','COLO':'#CFB87C','CONN':'#000E2F','CIN':'#E00122',
  'COL':'#B31B1B','CORN':'#B31B1B','CRE':'#005CA9',
  'DAV':'#CC0000','DAY':'#CE1141','DEP':'#005EB8',
  'DUKE':'#003087','FLA':'#0021A5','FSU':'#782F40',
  'GEO':'#BA0C2F','GT':'#B3A369','GONZ':'#002868','GTWN':'#041E42',
  'HALL':'#005EB8','HAR':'#A51C30','HOU':'#C8102E','HOW':'#003A86',
  'ILL':'#E84A27','IND':'#990000','ISU':'#C8102E',
  'KAN':'#0051A5','KU':'#0051A5','KSU':'#512888','UK':'#0033A0','KY':'#0033A0',
  'LA':'#461D7C','LOU':'#AD0000','LSU':'#461D7C',
  'MAR':'#E03A3E','MIA':'#005030','MICH':'#00274C','MSU':'#18453B',
  'MISS':'#CE1126','MIZZ':'#F1B82D','MEM':'#003087','MARQ':'#003087',
  'NEB':'#E41C38','NW':'#4E2A84','ND':'#C99700',
  'NCST':'#CC0000','UNC':'#7BAFD4',
  'OKL':'#841617','OU':'#841617','OSU':'#BB0000','OKS':'#FF7300',
  'ORE':'#154733','PSU':'#041E42','PITT':'#003594','PROV':'#002147',
  'PUR':'#CEB888','RICE':'#00205B','RUT':'#CC0033',
  'SC':'#73000A','SJU':'#BA0C2F','SMU':'#0038A8','STAN':'#8C1515',
  'SYR':'#D44500','TCU':'#4D1979','TENN':'#FF8200','TTU':'#CC0000',
  'TA&M':'#500000','TXAM':'#500000',
  'UCLA':'#2D68C4','USC':'#990000','UTAH':'#CC0000','USF':'#006747',
  'UVA':'#232D4B','VAN':'#866D4B','VCU':'#000000','VILL':'#00205B',
  'WAKE':'#9E7E38','WASH':'#4B2E83','WSU':'#981E32',
  'WIS':'#C5050C','WVU':'#002855','WYO':'#492F24',
  'XAV':'#0C2340','YALE':'#00356B',
};

const ncaaTeamColor = t => {
  if (!t) return '#3b82f6';
  return NCAA_ABBREV_COLORS[t?.toUpperCase()] || NCAA_TEAM_COLORS[t] || NCAA_TEAM_COLORS[t.replace(' St.', ' State')] || '#3b82f6';
};

// ── Brand logos ──────────────────────────────────────────────────────────────
const KALSHI_LOGO = '<img src="https://www.google.com/s2/favicons?sz=16&domain=kalshi.com" style="width:13px;height:13px;vertical-align:middle;border-radius:2px;margin-right:4px;position:relative;top:-1px" alt="">';

const POLYMARKET_LOGO = '<img src="https://www.google.com/s2/favicons?sz=16&domain=polymarket.com" style="width:13px;height:13px;vertical-align:middle;border-radius:2px;margin-right:4px;position:relative;top:-1px" alt="">';

// ── Constants ────────────────────────────────────────────────────────────────
const TEAM_COLORS = {
  ATL:'#E03A3E',BOS:'#00C45A',BKN:'#BBBBBB',CHA:'#8B7FD4',CHI:'#E8475F',
  CLE:'#FDBB30',DAL:'#4B9CD3',DEN:'#4FA8D5',DET:'#E03A3E',GSW:'#4B90D9',
  HOU:'#E8475F',IND:'#FDBB30',LAC:'#E03A3E',LAL:'#9B72CF',MEM:'#7B9FC4',
  MIA:'#F9A01B',MIL:'#00C45A',MIN:'#4B90D9',NOP:'#4B90D9',NYK:'#F58426',
  OKC:'#44AADD',ORL:'#3399DD',PHI:'#3A8FD4',PHX:'#8B7FD4',POR:'#E03A3E',
  SAC:'#9966CC',SAS:'#CCCCCC',TOR:'#E8475F',UTA:'#3A8FD4',WAS:'#E03A3E',
};
const teamColor = t => TEAM_COLORS[t?.toUpperCase()] || ncaaTeamColor(t);


// ── State ────────────────────────────────────────────────────────────────────
const STATE = {
  currentPage: null,
  sseSource: null,
  prevScores: new Map(),       // gameId -> {home, away}
  matchupTeamA: 'BOS',
  matchupTeamB: 'LAL',
  explorerTeam: 'BOS',
  _liveRefreshInterval: null,
  _liveRefreshInFlight: false,
  autoRefreshEnabled: false,   // off by default — user toggles on
};

// ── API helpers ───────────────────────────────────────────────────────────────
const api = {
  async get(path, params = {}) {
    const url = new URL(path, window.location.origin);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const r = await fetch(url);
    if (!r.ok) throw new Error(`API ${path} returned ${r.status}`);
    return r.json();
  },
  async post(path, params = {}) {
    const url = new URL(path, window.location.origin);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const r = await fetch(url, { method: 'POST' });
    if (!r.ok) throw new Error(`API ${path} returned ${r.status}`);
    return r.json();
  },
};

// ── Formatters ────────────────────────────────────────────────────────────────
const pct  = v => v == null ? '—' : (v * 100).toFixed(1) + '%';
const pct0 = v => v == null ? '—' : (v * 100).toFixed(0) + '%';
const money = v => v == null ? '—' : `$${Math.abs(v).toFixed(2)}`;
const moneySign = v => v == null ? '—' : `${v >= 0 ? '+' : '−'}$${Math.abs(v).toFixed(2)}`;
const num1  = v => v == null ? '—' : Number(v).toFixed(1);
const elo   = v => v == null ? '—' : Number(v).toFixed(0);
const colorGR = v => v == null ? '' : (v >= 0 ? 'color:var(--good)' : 'color:var(--bad)');

function badge(confidence) {
  if (!confidence) return '';
  const cl = confidence.toLowerCase();
  if (cl.includes('strong'))   return `<span class="badge badge-strong">${confidence}</span>`;
  if (cl.includes('moderate')) return `<span class="badge badge-moderate">${confidence}</span>`;
  if (cl.includes('marginal')) return `<span class="badge badge-marginal">${confidence}</span>`;
  return `<span class="badge badge-nobet">${confidence}</span>`;
}

function metricCard(label, value, delta = null, deltaClass = '', sublabel = '') {
  return `<div class="metric">
    <div class="label">${label}</div>
    <div class="value">${value}</div>
    ${delta ? `<div class="delta ${deltaClass}">${delta}</div>` : ''}
    ${sublabel ? `<div class="sublabel">${sublabel}</div>` : ''}
  </div>`;
}

function loading() {
  return `<div class="skeleton-page">
    <div class="skeleton-title"></div>
    <div class="skeleton-grid">
      <div class="skeleton-card"></div><div class="skeleton-card"></div>
      <div class="skeleton-card"></div><div class="skeleton-card"></div>
    </div>
    <div class="skeleton-block"></div>
    <div class="skeleton-block sk-short"></div>
  </div>`;
}

function empty(msg = 'No data available', icon = 'inbox') {
  return `<div class="empty-state"><div class="icon">${icon}</div><div>${msg}</div></div>`;
}

// ── Router ────────────────────────────────────────────────────────────────────
const ROUTES = {
  picks:      renderTodaysPicks,
  live:       renderLiveGames,
  matchup:    renderMatchupLab,
  paper:      renderPaperTrader,
  accuracy:   renderModelAccuracy,
  team:       renderTeamExplorer,
  tracker:    renderBetTracker,
  'nc-picks':    renderNcPicks,
  'nc-live':     renderNcLive,
  'nc-matchup':  renderNcMatchup,
  'nc-trader':   renderNcTrader,
  'nc-accuracy': renderNcAccuracy,
  'nc-teams':    renderNcTeams,
  'nc-tracker':  renderNcTracker,
  'nc-bracket':  renderNcBracket,
  system:     renderSystem,
};

function navigate(page) {
  // Clear live auto-refresh when leaving live pages
  if (STATE._liveRefreshInterval) {
    clearInterval(STATE._liveRefreshInterval);
    STATE._liveRefreshInterval = null;
  }
  if (STATE.currentPage !== 'live' && page !== 'live') {
    sseDisconnect();
  }
  STATE.currentPage = page;
  document.querySelectorAll('#sidebar a').forEach(a => {
    a.classList.toggle('active', a.dataset.page === page);
  });
  const fn = ROUTES[page] || renderTodaysPicks;
  const _main = document.getElementById('main');
  if (_main) { _main.style.opacity = '0'; _main.style.transform = 'translateY(10px)'; }
  requestAnimationFrame(() => {
    const _r = fn();
    const _fin = () => {
      if (_main) {
        _main.style.transition = 'opacity 0.22s ease, transform 0.22s ease';
        _main.style.opacity = '1'; _main.style.transform = 'translateY(0)';
        setTimeout(() => { if (_main) _main.style.transition = ''; }, 280);
      }
      _createIcons();
    };
    if (_r && typeof _r.then === 'function') _r.then(_fin).catch(_fin); else _fin();
  });
}

// ── SSE Manager ───────────────────────────────────────────────────────────────
function sseConnect() {
  if (STATE.sseSource) return;
  STATE.sseSource = new EventSource('/api/live/stream');
  STATE.sseSource.addEventListener('games', e => {
    try {
      const data = JSON.parse(e.data);
      if (STATE.currentPage === 'live') updateLiveBoard(data);
    } catch(err) { console.warn('SSE parse error', err); }
  });
  STATE.sseSource.onerror = () => {
    STATE.sseSource?.close();
    STATE.sseSource = null;
    setTimeout(() => { if (STATE.currentPage === 'live') sseConnect(); }, 8000);
  };
}

function sseDisconnect() {
  STATE.sseSource?.close();
  STATE.sseSource = null;
}

function updateLiveBoard(data) {
  const allGames = [...(data.in_progress || []), ...(data.upcoming || []), ...(data.final || [])];
  allGames.forEach(game => {
    const prev = STATE.prevScores.get(game.game_id) || {};
    const hChanged = prev.home != null && prev.home !== game.home_score;
    const aChanged = prev.away != null && prev.away !== game.away_score;
    STATE.prevScores.set(game.game_id, { home: game.home_score, away: game.away_score });

    const card = document.querySelector(`[data-game-id="${game.game_id}"]`);
    if (!card) return;

    // Update scores with animation
    const hEl = card.querySelector('.home-score');
    const aEl = card.querySelector('.away-score');
    if (hEl && hChanged) { hEl.textContent = game.home_score; flashScore(hEl); }
    if (aEl && aChanged) { aEl.textContent = game.away_score; flashScore(aEl); }

    // Update probs
    const hp = card.querySelector('.home-prob');
    const ap = card.querySelector('.away-prob');
    if (hp && game.live_home_prob != null) {
      hp.textContent = pct0(game.live_home_prob) + ' to win';
      hp.style.color = game.live_home_prob > game.live_away_prob ? 'var(--good)' : 'var(--bad)';
    }
    if (ap && game.live_away_prob != null) {
      ap.textContent = pct0(game.live_away_prob) + ' to win';
      ap.style.color = game.live_away_prob > game.live_home_prob ? 'var(--good)' : 'var(--bad)';
    }

    // Update clock
    const clk = card.querySelector('.clock-time');
    if (clk && game.clock_display) clk.textContent = game.clock_display;
  });
}

function flashScore(el) {
  el.classList.remove('score-flash');
  void el.offsetWidth;              // trigger reflow
  el.classList.add('score-flash');
}

// ─────────────────────────────────────────────────────────────────────────────
// Page: Today's Picks
// ─────────────────────────────────────────────────────────────────────────────
async function renderTodaysPicks() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  let data;
  try { data = await api.get('/api/picks'); }
  catch(e) { main.innerHTML = `<h1>Today's Picks</h1>
  <p class="page-subtitle">Games where our model finds value vs. the market — sorted by edge size</p><div class="error-state">Failed to load picks: ${e.message}</div>`; return; }

  const srcTags = (data.odds_sources || []).map(s =>
    `<span class="badge badge-moderate">${s}</span>`).join(' ');

  let html = `<h1>Today's Picks</h1>
  <div class="metrics metrics-4" style="margin-bottom:20px">
    ${metricCard('Games Today', data.games_analyzed ?? 0)}
    ${metricCard('Edge Bets Found', data.bets_found ?? 0, null)}
    ${metricCard('Avg Edge', data.avg_edge != null ? pct(data.avg_edge) : '—')}
    ${metricCard('Markets', srcTags || '—')}
  </div>`;

  const picks = data.picks || [];
  STATE._latestPicks = picks;
  if (!picks.length) {
    html += empty('No games found for today or model not trained yet.', 'inbox');
    main.innerHTML = html; return;
  }

  // Build tabs
  const bets     = picks.filter(p => p.bet).sort((a, b) => ((b.kelly || 0) - (a.kelly || 0)) || ((b.best_edge || 0) - (a.best_edge || 0)));
  const favs     = picks.filter(p => (p.home_win_prob || 0) >= 0.5 || (p.away_win_prob || 0) >= 0.5).sort((a,b) => Math.max(b.home_win_prob||0,b.away_win_prob||0) - Math.max(a.home_win_prob||0,a.away_win_prob||0));
  const all      = picks;

  const _minEdge = STATE._edgeThreshold ?? 0.04;
  const edgeBets = picks.filter(p => p.bet && (p.best_edge||0) >= _minEdge)
    .sort((a,b) => ((b.kelly||0)-(a.kelly||0))||((b.best_edge||0)-(a.best_edge||0)));
  const _ePct = Math.round((_minEdge*100 - 1) / 19 * 100);
  html += `<div class="edge-slider-wrap">
    <label>Min Edge</label>
    <input type="range" class="edge-slider" id="edge-slider" min="1" max="20" step="0.5"
      value="${(_minEdge*100).toFixed(1)}" style="--pct:${_ePct}%"
      oninput="onEdgeSlider(this)">
    <span class="edge-val" id="edge-val">${(_minEdge*100).toFixed(1)}%</span>
  </div>`;

  html += `<div class="tabs">
    <button class="tab-btn active" onclick="switchTab(this,'tab-bets')">Edge Bets (${edgeBets.length})</button>
    <button class="tab-btn" onclick="switchTab(this,'tab-favs')">Favorites to Win</button>
    <button class="tab-btn" onclick="switchTab(this,'tab-all')">All Games (${all.length})</button>
  </div>
  <div id="tab-bets" class="tab-panel active">${edgeBets.length ? edgeBets.map(buildPickCard).join('') : empty('No bets meet edge threshold. Try lowering the slider.','sliders-horizontal')}</div>
  <div id="tab-favs" class="tab-panel">${favs.map(buildPickCard).join('')}</div>
  <div id="tab-all"  class="tab-panel">${all.map(buildPickCard).join('')}</div>`;

  main.innerHTML = html;
}


// ── Edge slider ─────────────────────────────────────────────────────────────
function onEdgeSlider(input) {
  const val = parseFloat(input.value) / 100;
  STATE._edgeThreshold = val;
  const valEl = document.getElementById('edge-val');
  if (valEl) valEl.textContent = (val * 100).toFixed(1) + '%';
  const pct = Math.round((parseFloat(input.value) - 1) / 19 * 100);
  input.style.setProperty('--pct', pct + '%');
  const picks = STATE._latestPicks || [];
  const edgeBets = picks.filter(p => p.bet && (p.best_edge||0) >= val)
    .sort((a,b) => ((b.kelly||0)-(a.kelly||0))||((b.best_edge||0)-(a.best_edge||0)));
  const panel = document.getElementById('tab-bets');
  if (panel) {
    panel.innerHTML = edgeBets.length ? edgeBets.map(buildPickCard).join('')
      : empty('No bets meet edge threshold. Try lowering the slider.', 'sliders-horizontal');
    _createIcons();
  }
  const btn = document.querySelector('[onclick*="tab-bets"]');
  if (btn) btn.textContent = 'Edge Bets (' + edgeBets.length + ')';
}

function buildPickCard(p) {
  const h = p.home_team, a = p.away_team;
  const hProb = p.home_win_prob, aProb = p.away_win_prob;
  const edge = p.best_edge;
  const edgeColor = edge > 0 ? 'color: var(--good);' : 'color: var(--bad);';
  const stakePct = p.kelly != null ? pct(p.kelly) : '—';
  const stakePer100 = p.kelly != null ? `$${((p.kelly || 0) * 100).toFixed(2)}` : '—';
  const marketLabel = p.bet_market != null ? pct0(p.bet_market) : '—';
  const sourceLabel = p.best_source ? p.best_source.charAt(0).toUpperCase() + p.best_source.slice(1) : 'Best market';
  const modelLabel = p.bet_prob != null ? pct0(p.bet_prob) : '—';

  const actionPanel = p.bet
    ? `<div class="bet-callout bet-callout-yes">
        <div class="bet-callout-row">
          <div class="bet-callout-copy">
            <div class="bet-callout-label">Recommended Position</div>
            <div class="bet-callout-main">
              <span class="bet-callout-verb">Bet</span>
              <span class="bet-callout-team" style="color:${teamColor(p.bet_team)}">${p.bet_team}</span>
            </div>
            <div class="bet-callout-sub">Model gives ${modelLabel} · market gives ${marketLabel}</div>
            ${edge != null ? `<div class="edge-explain">Model sees <span class="edge-num ${(edge||0)>=0?"pos":"neg"}">${(edge||0)>=0?"+":""}${pct(edge)}</span> more value than the market</div>` : ""}
          </div>
          <div class="bet-callout-stats">
            <div class="bet-chip">
              <span>Kelly Size</span>
              <strong>${stakePct}</strong>
            </div>
            <div class="bet-chip">
              <span>Per $100 bankroll</span>
              <strong>${stakePer100}</strong>
            </div>
            <div class="bet-chip">
              <span>Best Market</span>
              <strong>${sourceLabel}</strong>
            </div>
          </div>
        </div>
      </div>`
    : `<div class="bet-callout bet-callout-no">
        <div class="bet-callout-row">
          <div class="bet-callout-copy">
            <div class="bet-callout-label">Recommendation</div>
            <div class="bet-callout-main">
              <span class="bet-callout-team">Pass</span>
            </div>
            <div class="bet-callout-sub">No edge worth betting right now</div>
          </div>
          <div class="bet-callout-stats">
            <div class="bet-chip">
              <span>Best edge</span>
              <strong>${p.best_edge != null ? pct(p.best_edge) : '—'}</strong>
            </div>
            <div class="bet-chip">
              <span>Status</span>
              <strong>Wait</strong>
            </div>
          </div>
        </div>
      </div>`;

  const oddsRow = [
    p.kalshi_home_prob != null ? `<span class="odds-item"><span class="lbl">${KALSHI_LOGO}Kalshi: </span>${a} ${pct0(1-p.kalshi_home_prob)} / ${h} ${pct0(p.kalshi_home_prob)}</span>` : '',
    p.polymarket_home_prob != null ? `<span class="odds-item"><span class="lbl">${POLYMARKET_LOGO}Polymarket: </span>${a} ${pct0(1-p.polymarket_home_prob)} / ${h} ${pct0(p.polymarket_home_prob)}</span>` : '',
    p.best_edge != null ? `<span class="odds-item"><span class="lbl">Edge: </span><b style="${edgeColor}">${p.best_edge >= 0 ? '+' : ''}${pct(p.best_edge)}</b></span>` : '',
  ].filter(Boolean).join('');

  const story = (p.game_story || []).map(s => `<span>· ${s}</span>`).join('');

  const aStreak = (p.away_form||[]).slice(-5).map(g=>g.win?'<div class="streak-dot win"></div>':'<div class="streak-dot loss"></div>').join('');
  const hStreak = (p.home_form||[]).slice(-5).map(g=>g.win?'<div class="streak-dot win"></div>':'<div class="streak-dot loss"></div>').join('');

  return `<div class="game-card fade-in">
    <div class="game-header">
      <div style="display:flex;flex-direction:column;gap:3px">
        <span class="team" style="color:${teamColor(a)}">${a}</span>
        ${aStreak ? `<div class="streak-dots">${aStreak}</div>` : ""}
      </div>
      <span class="vs">@</span>
      <div style="display:flex;flex-direction:column;gap:3px">
        <span class="team" style="color:${teamColor(h)}">${h}</span>
        ${hStreak ? `<div class="streak-dots">${hStreak}</div>` : ""}
      </div>
      ${badge(p.confidence)}
    </div>
    ${actionPanel}
    <div class="probs">
      <div>
        <div class="prob-team">${a}</div>
        <div class="prob-val" style="color:${aProb >= hProb ? 'var(--good)':'var(--bad)'}">${pct0(aProb)}</div>
      </div>
      <div class="vs-sep">vs</div>
      <div>
        <div class="prob-team">${h}</div>
        <div class="prob-val" style="color:${hProb >= aProb ? 'var(--good)':'var(--bad)'}">${pct0(hProb)}</div>
      </div>
    </div>
    ${oddsRow ? `<div class="odds-row">${oddsRow}</div>` : ''}
    ${story ? `<div class="story">${story}</div>` : ''}
  </div>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Page: Live Games
// ─────────────────────────────────────────────────────────────────────────────
function _startLiveRefresh(page, apiPath, onData) {
  if (STATE._liveRefreshInterval) { clearInterval(STATE._liveRefreshInterval); STATE._liveRefreshInterval = null; }
  if (!STATE.autoRefreshEnabled) return;
  STATE._liveRefreshInterval = setInterval(async () => {
    if (STATE.currentPage !== page) { clearInterval(STATE._liveRefreshInterval); STATE._liveRefreshInterval = null; return; }
    if (STATE._liveRefreshInFlight) return;
    STATE._liveRefreshInFlight = true;
    const d = await api.get(apiPath).catch(() => null);
    if (d) onData(d);
    STATE._liveRefreshInFlight = false;
  }, 15000);
}

function toggleAutoRefresh(page) {
  STATE.autoRefreshEnabled = !STATE.autoRefreshEnabled;
  if (STATE.autoRefreshEnabled) {
    // Kick off refresh immediately then start interval
    if (page === 'live') {
      api.get('/api/live').then(d => { if (d) renderLiveData(d); }).catch(() => {});
      _startLiveRefresh('live', '/api/live', d => renderLiveData(d));
    } else {
      api.get('/api/ncaab/live').then(d => { if (d) renderNcLiveContent(d); }).catch(() => {});
      _startLiveRefresh('nc-live', '/api/ncaab/live', d => renderNcLiveContent(d));
    }
  } else {
    if (STATE._liveRefreshInterval) { clearInterval(STATE._liveRefreshInterval); STATE._liveRefreshInterval = null; }
  }
  // Update button label without full re-render
  const btnId = page === 'live' ? 'nba-ar-toggle' : 'nc-ar-toggle';
  const btn = document.getElementById(btnId);
  if (btn) btn.textContent = STATE.autoRefreshEnabled ? '⏸ Auto-refresh on' : '▶ Auto-refresh off';
}

async function renderLiveGames() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  sseConnect();

  let data;
  try { data = await api.get('/api/live'); }
  catch(e) { main.innerHTML = `<h1>Live Games</h1>
  <p class="page-subtitle">Real-time scores with live win-probability updates</p><div class="error-state">${e.message}</div>`; return; }

  renderLiveData(data);

  // SSE handles fast score updates; this slower refresh only re-buckets cards.
  _startLiveRefresh('live', '/api/live', d => renderLiveData(d));
}

function renderLiveData(data) {
  const main = document.getElementById('main');
  const live    = data.in_progress || [];
  const pre     = data.upcoming    || [];
  const final_  = data.final       || [];

  // Seed previous scores (don't overwrite if already tracking)
  [...live, ...pre, ...final_].forEach(g => {
    if (!STATE.prevScores.has(g.game_id)) {
      STATE.prevScores.set(g.game_id, { home: g.home_score, away: g.away_score });
    }
  });

  let html = `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
    <h1 style="margin:0">Live Games</h1>
    <div style="display:flex;gap:10px;align-items:center">
      <button class="btn btn-secondary" onclick="refreshLive()">↺ Refresh</button>
      <button id="nba-ar-toggle" class="btn btn-secondary" onclick="toggleAutoRefresh('live')" style="font-size:.75rem">${STATE.autoRefreshEnabled ? '⏸ Auto-refresh on' : '▶ Auto-refresh off'}</button>
    </div>
  </div>`;

  if (!live.length && !pre.length && !final_.length) {
    html += empty('No NBA games right now. Check back during game time!', 'clock');
    main.innerHTML = html; return;
  }

  if (live.length) {
    html += `<div class="section-label">Live</div>`;
    html += live.map(g => buildLiveCard(g, true)).join('');
  }
  if (pre.length) {
    html += `<div class="section-label">Upcoming</div>`;
    html += pre.map(g => buildLiveCard(g, false)).join('');
  }
  if (final_.length) {
    html += `<div class="section-label">Final</div>`;
    html += final_.map(g => buildLiveCard(g, false)).join('');
  }

  main.innerHTML = html;
}

async function refreshLive() {
  if (STATE._liveRefreshInFlight) return;
  STATE._liveRefreshInFlight = true;
  const data = await api.get('/api/live').catch(() => null);
  if (data) renderLiveData(data);
  STATE._liveRefreshInFlight = false;
}

function buildLiveCard(g, isLive) {
  const h = g.home_team, a = g.away_team;
  const hProb = g.live_home_prob ?? 0.5, aProb = g.live_away_prob ?? 0.5;
  const hBig = hProb >= aProb;
  const kh = g.kalshi_home_prob, ka = g.kalshi_away_prob;
  const ph = g.polymarket_home_prob, pa = g.polymarket_away_prob;
  const pg = g.pregame_home_prob;
  const hEdge = g.live_home_edge, aEdge = g.live_away_edge;

  let clockHtml = '';
  if (isLive && g.period_label) {
    clockHtml = `<div class="clock-center">
      <div style="font-size:.68rem;color:var(--muted)">LIVE</div>
      <div class="period-label">${g.period_label}</div>
      <div class="clock-time">${g.clock_display || '—'}</div>
    </div>`;
  } else {
    clockHtml = `<div class="clock-center"><div class="status-text">${g.game_status_text || ''}</div></div>`;
  }

  const marketHtml = (kh != null || ph != null) ? `
    <div class="market-row">
      ${kh != null ? `<div class="market-panel">
        <div class="mkt-name">${KALSHI_LOGO}Kalshi</div>
        <span style="font-weight:700;color:${ka > kh ? 'var(--good)':'var(--bad)'}">${a} ${pct0(ka)}</span>
        <span style="color:var(--dimmer)"> vs </span>
        <span style="font-weight:700;color:${kh > ka ? 'var(--good)':'var(--bad)'}">${h} ${pct0(kh)}</span>
      </div>` : '<div></div>'}
      ${ph != null ? `<div class="market-panel">
        <div class="mkt-name">${POLYMARKET_LOGO}Polymarket <span style="font-size:.62rem;color:var(--dimmer)">· pre-game</span></div>
        <span style="font-weight:700;color:${pa > ph ? 'var(--good)':'var(--bad)'}">${a} ${pct0(pa)}</span>
        <span style="color:var(--dimmer)"> vs </span>
        <span style="font-weight:700;color:${ph > pa ? 'var(--good)':'var(--bad)'}">${h} ${pct0(ph)}</span>
      </div>` : '<div></div>'}
    </div>` : '';

  const pregameHtml = pg != null ? `
    <div class="pregame-row">
      <div>
        <div class="pg-label">Pre-game model (XGBoost)</div>
        <div class="pg-probs">
          <span style="font-weight:700;font-size:.95rem;color:${(1-pg)>pg?'var(--good)':'var(--bad)'}">${a} ${pct0(1-pg)}</span>
          <span style="color:var(--dim);font-size:.78rem">vs</span>
          <span style="font-weight:700;font-size:.95rem;color:${pg>(1-pg)?'var(--good)':'var(--bad)'}">${h} ${pct0(pg)}</span>
        </div>
      </div>
      <div class="pg-hint">live weight grows<br>as game progresses</div>
    </div>` : '';

  const edgeColor = (hEdge || 0) > 0.03 ? 'var(--good)' : (hEdge || 0) < -0.03 ? 'var(--bad)' : 'var(--muted)';
  const edgeHtml = hEdge != null ? `<div class="edge-row" style="color:${edgeColor}">
    Model edge vs market: ${h} ${hEdge >= 0 ? '+' : ''}${pct(hEdge)}
  </div>` : '';



  return `<div class="live-card fade-in" data-game-id="${g.game_id}">
    <div class="score-row">
      <div class="team-side">
        <div class="team-label">Away</div>
        <div class="team-abbr" style="color:${teamColor(a)}">${a}</div>
        <div class="score away-score">${g.away_score ?? 0}</div>
        <div class="win-prob away-prob" style="color:${aProb > hProb ? 'var(--good)':'var(--bad)'}">
          ${pct0(aProb)} <span class="to-win">to win</span>
        </div>
        ${aProb > hProb ? '<div class="favored-pill">Favored</div>' : ''}
        ${g.pred_away_score != null && !isLive ? `<div class="pred-score-under"><span style="font-size:.58rem;font-weight:500;color:var(--muted);display:block;letter-spacing:.06em">PRED</span>${g.pred_away_score}</div>` : ''}
      </div>
      ${clockHtml}
      <div class="team-side right">
        <div class="team-label">Home</div>
        <div class="team-abbr" style="color:${teamColor(h)}">${h}</div>
        <div class="score home-score">${g.home_score ?? 0}</div>
        <div class="win-prob home-prob" style="color:${hProb > aProb ? 'var(--good)':'var(--bad)'}">
          ${pct0(hProb)} <span class="to-win">to win</span>
        </div>
        ${hProb > aProb ? '<div class="favored-pill">Favored</div>' : ''}
        ${g.pred_home_score != null && !isLive ? `<div class="pred-score-under"><span style="font-size:.58rem;font-weight:500;color:var(--muted);display:block;letter-spacing:.06em">PRED</span>${g.pred_home_score}</div>` : ''}
      </div>
    </div>
    ${marketHtml}
    ${pregameHtml}
    ${edgeHtml}
  </div>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Page: NBA Matchup Lab
// ─────────────────────────────────────────────────────────────────────────────
async function renderMatchupLab() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  let teams = [];
  try { const td = await api.get('/api/matchup/teams'); teams = td.teams || []; }
  catch(e) {}
  const ta = STATE.matchupTeamA, tb = STATE.matchupTeamB;
  renderMatchupShell(teams, ta, tb);
  loadMatchupData(ta, tb);
}

function renderMatchupShell(teams, ta, tb) {
  const main = document.getElementById('main');
  const opts = teams.map(t => `<option value="${t}" ${t===ta?'selected':''}>${t}</option>`).join('');
  const opts2 = teams.map(t => `<option value="${t}" ${t===tb?'selected':''}>${t}</option>`).join('');
  main.innerHTML = `<h1>NBA Matchup Lab</h1>
  <p class="page-subtitle">Head-to-head breakdown — stats, form, Elo history and predicted score</p>
  <div class="form-row">
    <label>Away</label>
    <select id="sel-a" onchange="onMatchupChange()">${opts}</select>
    <span style="color:var(--dim)">@</span>
    <label>Home</label>
    <select id="sel-b" onchange="onMatchupChange()">${opts2}</select>
  </div>
  <div id="matchup-content">${loading()}</div>`;
}

function onMatchupChange() {
  const ta = document.getElementById('sel-a')?.value;
  const tb = document.getElementById('sel-b')?.value;
  if (ta) STATE.matchupTeamA = ta;
  if (tb) STATE.matchupTeamB = tb;
  if (ta && tb) {
    document.getElementById('matchup-content').innerHTML = loading();
    loadMatchupData(ta, tb);
  }
}

async function loadMatchupData(ta, tb) {
  const cont = document.getElementById('matchup-content');
  if (!cont) return;
  let d;
  try { d = await api.get('/api/matchup', { team_a: ta, team_b: tb }); }
  catch(e) { cont.innerHTML = `<div class="error-state">${e.message}</div>`; return; }

  const pa = d.pred_prob_a ?? 0.5, pb = d.pred_prob_b ?? 0.5;
  const mo = d.market_odds || {};
  const sourceLabel = d.prediction_source === 'full_model' ? 'Full model' : 'Elo fallback';

  let html = `<div class="matchup-hero fade-in">
    <div class="teams-row">
      <div class="mh-team">
        <div class="mh-abbr" style="color:${teamColor(ta)}">${ta}</div>
        <div class="mh-prob" style="color:${pa>=pb?'var(--good)':'var(--bad)'}">${pct0(pa)}</div>
        <div style="font-size:.75rem;color:var(--muted)">to win</div>
      </div>
      <div class="vs-divider">vs</div>
      <div class="mh-team">
        <div class="mh-abbr" style="color:${teamColor(tb)}">${tb}</div>
        <div class="mh-prob" style="color:${pb>=pa?'var(--good)':'var(--bad)'}">${pct0(pb)}</div>
        <div style="font-size:.75rem;color:var(--muted)">to win</div>
      </div>
    </div>
    <div class="fav-row">
      ${d.favorite === 'Even'
        ? '<b style="color:var(--muted)">Even matchup</b> — <span style="color:var(--muted)">Coin flip · ' + sourceLabel + '</span>'
        : '<b style="color:' + teamColor(d.favorite) + '">' + d.favorite + '</b> favored — <span style="color:var(--muted)">' + d.confidence_label + ' confidence · ' + sourceLabel + '</span>'
      }
    </div>
    ${d.pred_score_a != null ? `<div class="predicted-score-row">
      <span class="ps-team">${ta}</span>
      <span class="ps-score">${d.pred_score_a}</span>
      <span class="ps-label">Predicted Score</span>
      <span class="ps-score">${d.pred_score_b}</span>
      <span class="ps-team">${tb}</span>
    </div>` : ''}
    ${mo.kalshi_a_prob != null ? `<div style="margin-top:10px;font-size:.8rem;color:var(--muted)">
      ${KALSHI_LOGO}Kalshi: ${ta} ${pct0(mo.kalshi_a_prob)} / ${tb} ${pct0(mo.kalshi_b_prob)}
      ${mo.polymarket_a_prob != null ? ` · ${POLYMARKET_LOGO}Polymarket: ${ta} ${pct0(mo.polymarket_a_prob)} / ${tb} ${pct0(mo.polymarket_b_prob)}` : ''}
    </div>` : ''}
  </div>`;

  // Tabs
  html += `<div class="tabs">
    <button class="tab-btn active" onclick="switchTab(this,'mt-stats')">Stats</button>
    <button class="tab-btn" onclick="switchTab(this,'mt-form')">Recent Form</button>
    <button class="tab-btn" onclick="switchTab(this,'mt-h2h')">Head-to-Head</button>
    <button class="tab-btn" onclick="switchTab(this,'mt-elo')">Elo History</button>
  </div>
  <div id="mt-stats" class="tab-panel active">${buildStatBars(ta, tb, d.stats_a, d.stats_b)}</div>
  <div id="mt-form"  class="tab-panel">${buildFormTab(ta, tb, d.form_a, d.form_b)}</div>
  <div id="mt-h2h"   class="tab-panel">${buildH2HTab(ta, tb, d.h2h, d.h2h_summary)}</div>
  <div id="mt-elo"   class="tab-panel"><div id="elo-chart" class="chart-container" style="height:320px"></div>
    <div class="metrics metrics-3" style="margin-top:12px">
      ${metricCard(`${ta} Elo`, elo(d.stats_a?.elo))}
      ${metricCard('Difference', `${(d.stats_a?.elo||1500) - (d.stats_b?.elo||1500) >= 0 ? '+' : ''}${elo((d.stats_a?.elo||1500)-(d.stats_b?.elo||1500))}`)}
      ${metricCard(`${tb} Elo`, elo(d.stats_b?.elo))}
    </div>
  </div>`;

  cont.innerHTML = html;

  // Render Elo chart
  const eloA = (d.elo_history_a || []).map(r => ({ x: r.game_date, y: r.elo }));
  const eloB = (d.elo_history_b || []).map(r => ({ x: r.game_date, y: r.elo }));
  Plotly.newPlot('elo-chart', [
    { x: eloA.map(r=>r.x), y: eloA.map(r=>r.y), mode:'lines', name:ta, line:{color:teamColor(ta),width:2} },
    { x: eloB.map(r=>r.x), y: eloB.map(r=>r.y), mode:'lines', name:tb, line:{color:teamColor(tb),width:2} },
  ], { ..._plotTheme(), height:300,
       yaxis_title:'Elo Rating', legend:{bgcolor:'rgba(0,0,0,0)'}, margin:{t:10,b:30} });
}

function buildStatBars(ta, tb, sa, sb) {
  if (!sa || !sb) return empty('No stats data available', 'bar-chart-2');
  const rows = [
    ['Off Rating',    sa.off_rtg,      sb.off_rtg,      true,  '1'],
    ['Def Rating',    sa.def_rtg,      sb.def_rtg,      false, '1'],
    ['Net Rating',    sa.net_rtg,      sb.net_rtg,      true,  '1'],
    ['Elo Rating',    sa.elo,          sb.elo,          true,  '0'],
    ['Pace',          sa.pace,         sb.pace,         true,  '1'],
    ['eFG%',          sa.efg_pct,      sb.efg_pct,      true,  '.1%'],
    ['TOV Rate',      sa.tov_rate,     sb.tov_rate,     false, '.1%'],
    ['OREB%',         sa.oreb_pct,     sb.oreb_pct,     true,  '.1%'],
    ['FT Rate',       sa.ft_rate,      sb.ft_rate,      true,  '.1%'],
    ['Pts/G (L10)',   sa.roll_10_pts,  sb.roll_10_pts,  true,  '1'],
    ['Opp Pts (L10)', sa.roll_10_opp_pts, sb.roll_10_opp_pts, false, '1'],
    ['FG% (L10)',     sa.roll_10_fg_pct, sb.roll_10_fg_pct, true, '.1%'],
    ['Rest Days',     sa.rest_days,    sb.rest_days,    true,  '0'],
  ];
  return `<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
    <div>
      <div style="font-size:.7rem;color:var(--dim);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">${ta}</div>
    </div>
    <div>
      <div style="font-size:.7rem;color:var(--dim);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;text-align:right">${tb}</div>
    </div>
  </div>` + rows.map(([lbl, va, vb, hib, fmt]) => statBarRow(lbl, va, vb, hib, fmt, ta, tb)).join('');
}

function statBarRow(label, va, vb, higherIsBetter, fmt, ta, tb) {
  if (va == null && vb == null) return '';
  const a = va ?? 0, b = vb ?? 0;
  const aWins = higherIsBetter ? a >= b : a <= b;
  const aColor = aWins ? 'var(--good)' : 'var(--bad)';
  const bColor = aWins ? 'var(--bad)' : 'var(--good)';
  const total = Math.abs(a) + Math.abs(b) || 1;
  const aW = Math.round(Math.abs(a) / total * 100);
  const bW = Math.round(Math.abs(b) / total * 100);
  const fmtVal = v => {
    if (v == null) return '—';
    if (fmt === '0') return Math.round(v);
    if (fmt === '1') return Number(v).toFixed(1);
    if (fmt.endsWith('%')) return (v * 100).toFixed(1) + '%';
    return Number(v).toFixed(1);
  };
  const _titles={'Off Rating':'Points scored per 100 possessions','Def Rating':'Points allowed per 100 possessions','Net Rating':'Point differential per 100 possessions','Elo Rating':'Elo power rating — higher = stronger team','Pace':'Possessions per 48 min','eFG%':'Effective field goal % (accounts for 3s)','TOV Rate':'Turnovers per 100 possessions — lower is better','OREB%':'Offensive rebound rate','FT Rate':'Free throw attempts per field goal attempt','Pts/G (L10)':'Avg points scored in last 10 games','Opp Pts (L10)':'Avg points allowed in last 10 games','FG% (L10)':'Field goal % in last 10 games','Rest Days':'Days since last game'};
  const _tt = _titles[label] || label;
  return `<div class="stat-bar-row" title="${_tt}">
    <div class="stat-val a" style="color:${aColor}">${fmtVal(va)}</div>
    <div style="flex:1">
      <div style="display:flex;justify-content:space-between;font-size:.68rem;color:var(--dim);margin-bottom:3px">
        <span>${label}</span>
      </div>
      <div style="display:flex;gap:2px">
        <div style="flex:${aW};height:5px;background:${aColor};border-radius:2px"></div>
        <div style="flex:${bW};height:5px;background:${bColor};border-radius:2px;order:1"></div>
      </div>
    </div>
    <div class="stat-val" style="color:${bColor}">${fmtVal(vb)}</div>
  </div>`;
}

function buildFormTab(ta, tb, fa, fb) {
  const dots = (form) => (form || []).map(g =>
    `<div class="form-dot ${g.win ? 'win':'loss'}" title="${g.game_date}: ${g.pts}-${g.opp_pts}"></div>`
  ).join('');
  return `<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px">
    <div>
      <div style="font-size:.82rem;font-weight:700;margin-bottom:8px;color:${teamColor(ta)}">${ta} — Last 10</div>
      <div class="form-dots">${dots(fa)}</div>
      ${(fa||[]).map(g=>`<div style="font-size:.75rem;border-bottom:1px solid var(--line);padding:4px 0;display:flex;justify-content:space-between">
        <span>${g.game_date}</span>
        <span style="color:${g.win?'var(--good)':'var(--bad)'};font-weight:600">${g.win?'W':'L'} ${g.pts}-${g.opp_pts}</span>
      </div>`).join('')}
    </div>
    <div>
      <div style="font-size:.82rem;font-weight:700;margin-bottom:8px;color:${teamColor(tb)}">${tb} — Last 10</div>
      <div class="form-dots">${dots(fb)}</div>
      ${(fb||[]).map(g=>`<div style="font-size:.75rem;border-bottom:1px solid var(--line);padding:4px 0;display:flex;justify-content:space-between">
        <span>${g.game_date}</span>
        <span style="color:${g.win?'var(--good)':'var(--bad)'};font-weight:600">${g.win?'W':'L'} ${g.pts}-${g.opp_pts}</span>
      </div>`).join('')}
    </div>
  </div>`;
}

function buildH2HTab(ta, tb, h2h, summary) {
  if (!h2h || !h2h.length) return empty('No head-to-head history found.', 'git-compare');
  const s = summary || {};
  return `<div class="metrics metrics-3" style="margin-bottom:16px">
    ${metricCard(`${ta} Wins`, s.a_wins ?? 0)}
    ${metricCard(`${tb} Wins`, s.b_wins ?? 0)}
    ${metricCard('Games Played', s.games_played ?? 0)}
  </div>` +
  h2h.map(g => {
    const winner = g.winner;
    return `<div style="border:1px solid var(--line);border-radius:var(--radius);padding:10px 14px;margin-bottom:6px;display:flex;align-items:center;gap:16px;font-size:.82rem">
      <span style="color:var(--muted);min-width:80px">${g.game_date}</span>
      <span style="flex:1;display:flex;gap:12px;align-items:center">
        <span style="color:${teamColor(g.away_team)};font-weight:${winner===g.away_team?700:400}">${g.away_team} ${g.away_pts}</span>
        <span style="color:var(--dim)">@</span>
        <span style="color:${teamColor(g.home_team)};font-weight:${winner===g.home_team?700:400}">${g.home_team} ${g.home_pts}</span>
      </span>
      <span class="badge ${winner===ta?'badge-win':'badge-loss'}">${winner} won</span>
    </div>`;
  }).join('');
}

// ─────────────────────────────────────────────────────────────────────────────
// Page: Paper Trader
// ─────────────────────────────────────────────────────────────────────────────
async function renderPaperTrader() {
  const main = document.getElementById('main');
  main.innerHTML = loading();

  let stateData, candidates, open, settled;
  try {
    [stateData, candidates, open, settled] = await Promise.all([
      api.get('/api/paper-trader/state'),
      api.get('/api/paper-trader/candidates'),
      api.get('/api/paper-trader/open-positions'),
      api.get('/api/paper-trader/settled-positions'),
    ]);
  } catch(e) {
    main.innerHTML = `<h1>Paper Trader</h1>
  <p class="page-subtitle">Simulated bets using Kelly sizing — tracks model performance over time</p><div class="error-state">${e.message}</div>`;
    return;
  }

  const bk = stateData.bankroll || {};
  const totalPnl = (bk.realized_pnl || 0) + (bk.unrealized_pnl || 0);
  const totalRet = bk.starting_bankroll ? totalPnl / bk.starting_bankroll : 0;
  const pnlClass = totalPnl >= 0 ? 'good' : 'bad';
  const pnlColor = totalPnl >= 0 ? 'var(--good)' : 'var(--bad)';

  let html = `<h1>Paper Trader</h1>
  <div class="pnl-card ${pnlClass}">
    <div class="pnl-main">
      <div class="pnl-label">Total P/L</div>
      <div class="pnl-value" style="color:${pnlColor}">${totalPnl >= 0 ? '+' : '−'}$${Math.abs(totalPnl).toFixed(2)}</div>
      <div class="pnl-return" style="color:${pnlColor}">${totalRet >= 0 ? '+' : ''}${(totalRet*100).toFixed(1)}% on $${bk.starting_bankroll?.toFixed(0)} starting</div>
    </div>
    <div class="pnl-breakdown">
      <div class="pnl-breakdown-row"><span class="lbl">Realized </span><span style="color:${(bk.realized_pnl||0)>=0?'var(--good)':'var(--bad)'};font-weight:600">${moneySign(bk.realized_pnl)}</span></div>
      <div class="pnl-breakdown-row"><span class="lbl">Unrealized </span><span style="color:${(bk.unrealized_pnl||0)>=0?'var(--good)':'var(--bad)'};font-weight:600">${moneySign(bk.unrealized_pnl)}</span></div>
    </div>
  </div>
  <div class="metrics metrics-4">
    ${metricCard('Bankroll', money(bk.estimated_equity), null, '', 'Starting $1000 + P&L')}
    ${metricCard('Active Bets', stateData.open_count ?? 0, null, '', 'Open positions')}
    ${metricCard('Settled', stateData.settled_count ?? 0, null, '', 'Completed bets')}
    ${metricCard('Cash Available', money(bk.available_cash), null, '', 'Uncommitted balance')}
  </div>
  <div class="btn-row">
    <button class="btn btn-secondary" onclick="renderPaperTrader()">↺ Refresh</button>
  </div>`;

  // Today's picks
  html += `<div class="section-label">Today's Picks</div>`;
  const cands = candidates.candidates || [];
  if (!cands.length) {
    html += `<div class="empty-state" style="padding:24px 0;text-align:left;color:var(--muted)">No picks meet current edge threshold.</div>`;
  } else {
    const byGame = {};
    cands.forEach(c => {
      const key = `${c.away_team}@${c.home_team}`;
      if (!byGame[key]) byGame[key] = [];
      byGame[key].push(c);
    });
    Object.entries(byGame).forEach(([game, trades]) => {
      html += `<div class="section-label" style="margin-top:12px">${game}</div>`;
      trades.forEach(c => {
        const edge = c.edge || 0;
        const edgeColor = edge > 0 ? 'var(--good)' : 'var(--bad)';
        html += `<div class="trade-card">
          <div class="tc-team"><div class="name">${c.contract_team}</div><div class="sub">${(c.market_source||'').charAt(0).toUpperCase()+(c.market_source||'').slice(1)}</div></div>
          <div class="tc-col"><div class="lbl">Model</div><div class="val">${pct0(c.model_prob)}</div></div>
          <div class="tc-col"><div class="lbl">Market</div><div class="val">${pct0(c.market_prob)}</div></div>
          <div class="tc-col"><div class="lbl">Edge</div><div class="val" style="color:${edgeColor}">${edge>=0?'+':''}${pct(edge)}</div></div>
          <div class="tc-right"><div class="lbl">Bet · Win if right</div><div class="val">$${(c.stake||0).toFixed(0)} · $${(c.payout_if_win||0).toFixed(0)}</div></div>
        </div>`;
      });
    });
    html += `<button class="btn btn-primary" style="margin-top:12px;width:100%" onclick="logTrades()">Log These Trades</button>`;
  }

  // Active bets
  html += `<div class="section-label" style="margin-top:24px">Active Bets</div>`;
  const openPos = open.positions || [];
  if (!openPos.length) {
    html += `<div style="color:var(--muted);font-size:.82rem;padding:12px 0">No active bets right now.</div>`;
  } else {
    const byGame = {};
    openPos.forEach(p => { const k = `${p.away_team}@${p.home_team}`; if(!byGame[k]) byGame[k]=[]; byGame[k].push(p); });
    Object.entries(byGame).forEach(([game, trades]) => {
      html += `<div class="section-label" style="margin-top:10px">${game}</div>`;
      trades.forEach(p => {
        const pnl = p.unrealized_pnl; const pnlCol = pnl == null ? 'var(--muted)' : pnl >= 0 ? 'var(--good)' : 'var(--bad)';
        const stageColor = p.trade_stage === 'live' ? 'var(--good)' : 'var(--muted)';
        html += `<div class="trade-card">
          <div class="tc-team"><div class="name">${p.contract_team}</div><div class="sub">${(p.market_source||'').charAt(0).toUpperCase()+(p.market_source||'').slice(1)} · <span style="color:${stageColor}">${p.trade_stage||'open'}</span></div></div>
          <div class="tc-col"><div class="lbl">Paid</div><div class="val">$${(p.stake||0).toFixed(0)} @ ${pct0(p.entry_price)}</div></div>
          <div class="tc-col"><div class="lbl">Current Value</div><div class="val">${p.current_value != null ? money(p.current_value) : '—'}</div></div>
          <div class="tc-right"><div class="lbl">P/L</div><div class="pnl" style="color:${pnlCol}">${pnl != null ? moneySign(pnl) : '—'}${p.unrealized_return != null ? ` (${(p.unrealized_return*100).toFixed(1)}%)` : ''}</div></div>
        </div>`;
      });
    });
  }

  // Past results
  const settledPos = settled.positions || [];
  html += `<div class="section-label" style="margin-top:24px">Past Results</div>`;
  if (!settledPos.length) {
    html += `<div style="color:var(--muted);font-size:.82rem;padding:12px 0">No settled trades yet.</div>`;
  } else {
    const wins = settledPos.filter(p => p.win === 1 || p.win === true).length;
    const losses = settledPos.length - wins;
    const totalPnlS = settledPos.reduce((acc, p) => acc + (p.pnl || 0), 0);
    html += `<div class="metrics metrics-3" style="margin-bottom:12px">
      ${metricCard('Record', `${wins}W – ${losses}L`)}
      ${metricCard('Total P/L', moneySign(totalPnlS), null, totalPnlS >= 0 ? 'good':'bad')}
      ${metricCard('ROI', settledPos.reduce((a,p)=>a+(p.stake||0),0) > 0 ?
        pct(totalPnlS / settledPos.reduce((a,p)=>a+(p.stake||0),0)) : '—')}
    </div>`;
    html += `<div id="pnl-chart" class="chart-container" style="height:200px;margin-bottom:16px"></div>`;

    const byGame = {};
    settledPos.forEach(p => { const k = `${p.away_team}@${p.home_team}`; if(!byGame[k]) byGame[k]=[]; byGame[k].push(p); });
    Object.entries(byGame).forEach(([game, trades]) => {
      html += `<div class="section-label" style="margin-top:10px">${game}</div>`;
      trades.forEach(p => {
        const isWin = p.win === 1 || p.win === true;
        const col = isWin ? 'var(--good)' : 'var(--bad)';
        html += `<div class="trade-card ${isWin?'win-card':'loss-card'}">
          <div class="tc-team"><div class="name">${p.contract_team}</div><div class="sub">${(p.market_source||'').charAt(0).toUpperCase()+(p.market_source||'').slice(1)} · ${(p.game_date||'').toString().slice(0,10)}</div></div>
          <div class="tc-col"><div class="lbl">Bet</div><div class="val">$${(p.stake||0).toFixed(0)}</div></div>
          <div class="tc-col"><div class="lbl">Payout</div><div class="val">$${(p.realized_payout||0).toFixed(0)}</div></div>
          <div class="tc-right">
            <div style="font-size:.88rem;font-weight:800;color:${col}">${isWin?'WIN':'LOSS'}</div>
            <div class="pnl" style="color:${col}">${moneySign(p.pnl)}</div>
          </div>
        </div>`;
      });
    });
  }

  main.innerHTML = html;

  // Render P/L chart
  if (settledPos.length) {
    const sorted = [...settledPos].sort((a,b) => (a.game_date||'').localeCompare(b.game_date||''));
    let cum = 0; const xs = [], ys = [];
    sorted.forEach(p => { cum += (p.pnl||0); xs.push((p.game_date||'').toString().slice(0,10)); ys.push(cum); });
    Plotly.newPlot('pnl-chart', [{
      x: xs, y: ys, mode:'lines+markers', fill:'tozeroy',
      fillcolor:'rgba(34,197,94,.08)', line:{color:'#22c55e',width:2}, marker:{size:4},
    }], { ..._plotTheme(),
         height:190, margin:{t:10,b:30}, yaxis_title:'P/L ($)', showlegend:false });
  }
}

async function logTrades() {
  const btn = document.querySelector('[onclick="logTrades()"]');
  if (btn) { btn.textContent = 'Logging...'; btn.disabled = true; }
  try {
    const result = await api.post('/api/paper-trader/log-trades');
    alert(`✅ ${result.message}`);
    renderPaperTrader();
  } catch(e) {
    alert('Error logging trades: ' + e.message);
    if (btn) { btn.textContent = 'Log These Trades'; btn.disabled = false; }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Page: Model Accuracy
// ─────────────────────────────────────────────────────────────────────────────
async function renderModelAccuracy() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  let d;
  try { d = await api.get('/api/accuracy'); }
  catch(e) { main.innerHTML = `<h1>Model Accuracy</h1>
  <p class="page-subtitle">How well the XGBoost model predicts outcomes — evaluated on held-out test data</p><div class="error-state">${e.message}</div>`; return; }

  if (d.error) {
    main.innerHTML = `<h1>Model Accuracy</h1><div class="empty-state"><i data-lucide="cpu" style="width:24px;height:24px;display:inline-block;margin-right:8px;opacity:.5"></i><div>${d.error === 'model_not_trained' ? 'Model not trained yet. Run scripts/train.py first.' : d.error}</div></div>`;
    return;
  }

  const m = d.metrics || {};
  let html = `<div style="display:flex;align-items:center;gap:12px;margin-bottom:4px">
    <h1 style="margin:0">Model Accuracy</h1>
    <button id="update-model-btn" class="btn-sm" onclick="startModelUpdate()" style="margin-left:auto">Update Model</button>
  </div>
  <div id="update-model-status" style="display:none;margin-bottom:12px"></div>
  <div class="metrics metrics-4">
    ${metricCard('Accuracy', m.accuracy != null ? pct(m.accuracy) : '—', null, '', 'Correct winner predictions')}
    ${metricCard('AUC-ROC', m.auc_roc != null ? Number(m.auc_roc).toFixed(3) : '—', null, '', 'Discrimination · 1.0 = perfect')}
    ${metricCard('Brier Score', m.brier_score != null ? Number(m.brier_score).toFixed(4) : '—', null, '', 'Calibration error · lower is better')}
    ${metricCard('Games Evaluated', m.n_games ?? '—', null, '', 'Games in test set')}
  </div>`;

  html += `<div class="tabs" style="margin-top:20px">
    <button class="tab-btn active" onclick="switchTab(this,'acc-cal')">Calibration</button>
    <button class="tab-btn" onclick="switchTab(this,'acc-roi')">ROI Backtest</button>
    <button class="tab-btn" onclick="switchTab(this,'acc-fi')">Feature Importance</button>
    <button class="tab-btn" onclick="switchTab(this,'acc-recent')">Recent Predictions</button>
  </div>
  <div id="acc-cal" class="tab-panel active"><div id="cal-chart" class="chart-container" style="height:320px"></div></div>
  <div id="acc-roi" class="tab-panel"><div id="roi-chart" class="chart-container" style="height:320px"></div></div>
  <div id="acc-fi"  class="tab-panel"><div id="fi-chart" class="chart-container" style="height:400px"></div></div>
  <div id="acc-recent" class="tab-panel">${buildRecentPredTable(d.recent_predictions||[])}</div>`;

  main.innerHTML = html;

  // Calibration chart
  const cal = d.calibration || [];
  if (cal.length) {
    Plotly.newPlot('cal-chart', [
      { x: [0,1], y: [0,1], mode:'lines', name:'Perfect', line:{color: document.body.classList.contains('light') ? '#999' : '#555',dash:'dot',width:1} },
      { x: cal.map(r=>r.mean_predicted), y: cal.map(r=>r.fraction_positive),
        mode:'lines+markers', name:'Model', line:{color:'#22c55e',width:2}, marker:{size:7} },
    ], { ..._plotTheme(), height:300,
         xaxis_title:'Predicted Probability', yaxis_title:'Actual Win Rate',
         legend:{bgcolor:'rgba(0,0,0,0)'}, margin:{t:10,b:40} });
  }

  // ROI chart
  const bt = d.backtest || {};
  const roiTraces = Object.entries(bt).map(([thresh, data]) => ({
    x: Array.isArray(data.cumulative_pnl) ? data.cumulative_pnl.map((_,i)=>i) : [],
    y: Array.isArray(data.cumulative_pnl) ? data.cumulative_pnl : [],
    mode:'lines', name:`Edge ≥ ${(parseFloat(thresh)*100).toFixed(0)}%`,
  }));
  if (roiTraces.length) {
    Plotly.newPlot('roi-chart', roiTraces, {
      ..._plotTheme(), height:300,
      xaxis_title:'Bet #', yaxis_title:'Cumulative P/L ($1 flat)',
      legend:{bgcolor:'rgba(0,0,0,0)'}, margin:{t:10,b:40},
    });
  }

  // Feature importance
  const fi = (d.feature_importance || []).slice(0, 20);
  if (fi.length) {
    Plotly.newPlot('fi-chart', [{
      type:'bar', orientation:'h',
      x: fi.map(r => r.importance || r.gain || 0).reverse(),
      y: fi.map(r => r.feature || r.Feature || '').reverse(),
      marker:{color:'#22c55e'},
    }], { ..._plotTheme(), height:380,
          margin:{l:160,t:10,b:30}, xaxis_title:'Importance', showlegend:false });
  }
}

let _updateModelPoller = null;

async function startModelUpdate() {
  const btn = document.getElementById('update-model-btn');
  const statusEl = document.getElementById('update-model-status');
  if (!btn || !statusEl) return;

  btn.disabled = true;
  btn.textContent = 'Starting...';
  statusEl.style.display = 'block';
  statusEl.innerHTML = '<div class="section-label">Update Log</div><pre id="update-log" style="background:var(--panel2);border:1px solid var(--line2);border-radius:6px;padding:12px;font-size:.78rem;max-height:260px;overflow-y:auto;white-space:pre-wrap;color:var(--text2)">Starting...</pre>';

  try {
    const r = await api.post('/api/system/update-model', {});
    if (!r.started && r.reason === 'already_running') {
      btn.textContent = 'Running...';
    }
  } catch(e) {
    statusEl.innerHTML = `<div class="error-state">Failed to start: ${e.message}</div>`;
    btn.disabled = false;
    btn.textContent = 'Update Model';
    return;
  }

  if (_updateModelPoller) clearInterval(_updateModelPoller);
  _updateModelPoller = setInterval(_pollModelUpdate, 3000);
  _pollModelUpdate();
}

async function _pollModelUpdate() {
  let s;
  try { s = await api.get('/api/system/update-model/status'); }
  catch(e) { return; }

  const btn = document.getElementById('update-model-btn');
  const logEl = document.getElementById('update-log');
  if (!btn || !logEl) { clearInterval(_updateModelPoller); return; }

  logEl.textContent = (s.log || []).join('\n') || 'Waiting for output...';
  logEl.scrollTop = logEl.scrollHeight;

  if (s.status === 'running') {
    btn.textContent = 'Updating...';
    btn.disabled = true;
  } else if (s.status === 'done') {
    clearInterval(_updateModelPoller);
    btn.disabled = false;
    btn.textContent = 'Update Model';
    logEl.textContent += '\n\nDone! Reload the page to see updated metrics.';
  } else if (s.status === 'error') {
    clearInterval(_updateModelPoller);
    btn.disabled = false;
    btn.textContent = 'Update Model';
    logEl.textContent += '\n\nUpdate failed. Check the log above for details.';
  }
}

function buildRecentPredTable(rows) {
  if (!rows.length) return empty('No prediction log yet.', 'activity');
  return `<table class="data-table">
    <thead><tr><th>Date</th><th>Away</th><th>Home</th><th>Model Home%</th><th>Market Home%</th><th>Bet</th><th>Result</th></tr></thead>
    <tbody>${rows.map(r => `<tr>
      <td>${(r.game_date||'').toString().slice(0,10)}</td>
      <td>${r.away_team||'—'}</td>
      <td>${r.home_team||'—'}</td>
      <td>${pct0(r.home_win_prob)}</td>
      <td>${pct0(r.market_home_implied)}</td>
      <td>${r.bet ? '✓' : ''}</td>
      <td style="color:${r.home_win===1?'var(--good)':r.home_win===0?'var(--bad)':'var(--muted)'}">${r.home_win===1?'✓ H':r.home_win===0?'✗ A':'—'}</td>
    </tr>`).join('')}</tbody>
  </table>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Page: Team Explorer
// ─────────────────────────────────────────────────────────────────────────────
async function renderTeamExplorer() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  let teams = [];
  try { const td = await api.get('/api/team-explorer/teams'); teams = td.teams || []; }
  catch(e) {}
  const t = STATE.explorerTeam;
  const opts = teams.map(tm => `<option value="${tm}" ${tm===t?'selected':''}>${tm}</option>`).join('');
  main.innerHTML = `<h1>Team Explorer</h1>
    <div class="form-row">
      <label>Team</label>
      <select id="team-sel" onchange="onTeamChange()">${opts}</select>
    </div>
    <div id="team-content">${loading()}</div>`;
  loadTeamData(t);
}

function onTeamChange() {
  const t = document.getElementById('team-sel')?.value;
  if (t) { STATE.explorerTeam = t; document.getElementById('team-content').innerHTML = loading(); loadTeamData(t); }
}

async function loadTeamData(team) {
  const cont = document.getElementById('team-content');
  if (!cont) return;
  let d;
  try { d = await api.get(`/api/team-explorer/${team}`); }
  catch(e) { cont.innerHTML = `<div class="error-state">${e.message}</div>`; return; }
  if (d.error) { cont.innerHTML = empty('No data for this team.', 'users'); return; }

  const rec = d.season_record || {};
  const recordSeason = d.record_season || 'current season';
  let html = `<div class="metrics metrics-4">
    ${metricCard('Current Elo', elo(d.current_elo))}
    ${metricCard(`Record (${recordSeason})`, `${rec.wins||0}–${rec.losses||0}`)}
    ${metricCard('Win %', pct(d.win_pct))}
  </div>
  <div id="team-elo-chart" class="chart-container" style="height:280px;margin-bottom:14px"></div>
  <div id="team-form-chart" class="chart-container" style="height:240px"></div>`;
  cont.innerHTML = html;

  // Elo chart
  const eh = d.elo_history || [];
  Plotly.newPlot('team-elo-chart', [{
    x: eh.map(r=>r.game_date), y: eh.map(r=>r.elo),
    mode:'lines', line:{color:teamColor(team),width:2}, fill:'tozeroy',
    fillcolor: teamColor(team).replace(')',', 0.08)').replace('rgb','rgba').replace('#',
      (() => { const c=teamColor(team).replace('#',''); const r=parseInt(c.substr(0,2),16),g=parseInt(c.substr(2,2),16),b=parseInt(c.substr(4,2),16); return `rgba(${r},${g},${b},0.08`; })()),
  }], { ..._plotTheme(), height:260,
        yaxis_title:'Elo', xaxis_title:'', margin:{t:10,b:30} });

  // Rolling pts chart
  const rf = d.rolling_form || [];
  Plotly.newPlot('team-form-chart', [
    { x: rf.map(r=>r.game_date), y: rf.map(r=>r.roll_10_pts),    mode:'lines', name:'Points Scored', line:{color:'#22c55e',width:2} },
    { x: rf.map(r=>r.game_date), y: rf.map(r=>r.roll_10_opp_pts), mode:'lines', name:'Points Allowed', line:{color:'#ef4444',width:2,dash:'dot'} },
  ], { ..._plotTheme(), height:220,
       legend:{bgcolor:'rgba(0,0,0,0)'}, xaxis_title:'', yaxis_title:'10-Game Rolling Avg', margin:{t:10,b:30} });
}

// ─────────────────────────────────────────────────────────────────────────────
// Page: Bet Tracker
// ─────────────────────────────────────────────────────────────────────────────
async function renderBetTracker() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  let d;
  try { d = await api.get('/api/bet-tracker'); }
  catch(e) { main.innerHTML = `<h1>Bet Tracker</h1>
  <p class="page-subtitle">Settled edge bets — win rate, ROI, and cumulative P&L over time</p><div class="error-state">${e.message}</div>`; return; }

  const s = d.summary || {};
  const pnlColor = (s.flat_roi || 0) >= 0 ? 'var(--good)' : 'var(--bad)';
  let html = `<h1>Bet Tracker</h1>
  <div class="metrics metrics-4">
    ${metricCard('Record', `${s.wins||0}W – ${s.losses||0}L`)}
    ${metricCard('Win Rate', s.win_rate != null ? pct(s.win_rate) : '—')}
    ${metricCard('Flat ROI', s.flat_roi != null ? pct(s.flat_roi) : '—')}
    ${metricCard('Total Bets', s.total_bets || 0)}
  </div>
  <div id="tracker-chart" class="chart-container" style="height:260px;margin-bottom:20px"></div>`;

  const bets = d.bets || [];
  if (bets.length) {
    html += `<h2>Settled Trades</h2><table class="data-table">
      <thead><tr><th>Date</th><th>Game</th><th>Bet</th><th>Market</th><th>Entry</th><th>CLV</th><th>P/L</th><th>Result</th></tr></thead>
      <tbody>${bets.map(b => {
        const isWin = b.win === 1 || b.win === true;
        const col = isWin ? 'var(--good)' : 'var(--bad)';
        return `<tr>
          <td>${(b.game_date||'').toString().slice(0,10)}</td>
          <td>${b.away_team||''}@${b.home_team||''}</td>
          <td style="font-weight:600">${b.contract_team||b.bet_team||'—'}</td>
          <td>${(b.market_source||'')}</td>
          <td>${pct0(b.entry_price)}</td>
          <td style="color:${(b.clv||0)>=0?'var(--good)':'var(--bad)'}">${b.clv != null ? (b.clv>=0?'+':'')+pct(b.clv) : '—'}</td>
          <td style="color:${col}">${b.pnl != null ? moneySign(b.pnl) : '—'}</td>
          <td><span class="badge ${isWin?'badge-win':'badge-loss'}">${isWin?'WIN':'LOSS'}</span></td>
        </tr>`;
      }).join('')}</tbody>
    </table>`;
  }

  main.innerHTML = html;

  const cum = d.cumulative_pnl || [];
  if (cum.length) {
    Plotly.newPlot('tracker-chart', [{
      x: cum.map(r=>r.game_date), y: cum.map(r=>r.cumulative),
      mode:'lines+markers', fill:'tozeroy', fillcolor:'rgba(34,197,94,.08)',
      line:{color:'#22c55e',width:2}, marker:{size:4},
    }], { ..._plotTheme(), height:240,
         yaxis_title:'Cumulative P/L ($)', showlegend:false, margin:{t:10,b:30} });
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Bracket Builder — real tournament tree
// ─────────────────────────────────────────────────────────────────────────────
function buildBracketHTML(games, teamsList) {
  const regionOrder = ['East', 'South', 'West', 'Midwest'];
  const roundOrder = ['First Four','Round of 64','Round of 32','Sweet 16','Elite 8'];
  const roundShort = {'First Four':'Play-In','Round of 64':'R64','Round of 32':'R32','Sweet 16':'Sweet 16','Elite 8':'Elite 8'};

  // Build ELO lookup from teams list
  const eloMap = {};
  (teamsList||[]).forEach(t => { if (t.TeamID != null && t.elo != null) eloMap[t.TeamID] = Math.round(t.elo); });

  // Group: region → round → games[]
  const byRegion = {};
  const ffGames = [];
  games.forEach(g => {
    const round = g.round_name || g.round || '';
    const region = g.region || '';
    if (round === 'Final Four' || round === 'National Championship') { ffGames.push(g); return; }
    if (!byRegion[region]) byRegion[region] = {};
    if (!byRegion[region][round]) byRegion[region][round] = [];
    byRegion[region][round].push(g);
  });

  function teamSlot(name, prob, isW, isL, teamId) {
    const cls = isW ? 'bk-winner' : isL ? 'bk-loser' : '';
    const p = (prob != null && isW) ? `<span class="bk-prob">${(prob*100).toFixed(0)}%</span>` : '';
    const elo = (teamId != null && eloMap[teamId] != null) ? `<span class="bk-elo">${eloMap[teamId]}</span>` : '';
    return `<div class="bk-team ${cls}"><span class="bk-name">${name||'TBD'}</span>${elo}${p}</div>`;
  }

  function matchupHTML(g) {
    const ta = g.team_a_name || g.team_a || 'TBD';
    const tb = g.team_b_name || g.team_b || 'TBD';
    const w  = g.winner_name || g.winner || '';
    const pr = g.win_prob;
    return `<div class="bk-game">
      ${teamSlot(ta, pr, w===ta, w && w!==ta, g.team_a_id)}
      ${teamSlot(tb, w ? 1-(pr||0) : null, w===tb, w && w!==tb, g.team_b_id)}
    </div>`;
  }

  let out = '';

  // ── Render each region as a horizontal bracket tree ──
  regionOrder.forEach(region => {
    const rData = byRegion[region];
    if (!rData) return;
    const rounds = roundOrder.filter(r => rData[r] && rData[r].length);
    if (!rounds.length) return;

    out += `<div class="bk-region">
      <div class="bk-region-label">${region}</div>
      <div class="bk-tree">`;

    rounds.forEach((round, ri) => {
      const gms = rData[round];
      out += `<div class="bk-round" data-round="${ri}">
        <div class="bk-round-title">${roundShort[round]||round}</div>
        <div class="bk-round-games">`;
      gms.forEach(g => { out += matchupHTML(g); });
      out += `</div></div>`;
    });

    out += `</div></div>`;
  });

  // ── Final Four ──
  if (ffGames.length) {
    const semis = ffGames.filter(g => (g.round_name||g.round)==='Final Four');
    const final = ffGames.find(g => (g.round_name||g.round)==='National Championship');
    const champName = final ? (final.winner_name||final.winner||'') : '';

    out += `<div class="bk-ff">
      <div class="bk-region-label" style="--accent:var(--warn)">Final Four</div>
      <div class="bk-ff-grid">`;

    // Left semi
    out += `<div class="bk-ff-semi">`;
    if (semis[0]) out += matchupHTML(semis[0]);
    out += `</div>`;

    // Championship center
    out += `<div class="bk-ff-center">`;
    if (final) {
      out += `<div class="bk-round-title">Championship</div>`;
      out += matchupHTML(final);
    }
    if (champName) {
      out += `<div class="bk-champion">
        <div class="bk-champ-trophy">&#127942;</div>
        <div class="bk-champ-name">${champName}</div>
        <div class="bk-champ-sub">Projected Champion</div>
      </div>`;
    }
    out += `</div>`;

    // Right semi
    out += `<div class="bk-ff-semi">`;
    if (semis[1]) out += matchupHTML(semis[1]);
    out += `</div>`;

    out += `</div></div>`;
  }

  return out;
}

// ─────────────────────────────────────────────────────────────────────────────
// NCAA Shared: load summary + guard
// ─────────────────────────────────────────────────────────────────────────────
async function _ncaaSummary() {
  const [summary, teams] = await Promise.all([
    api.get('/api/ncaab/summary'),
    api.get('/api/ncaab/teams'),
  ]);
  return { summary, teams };
}

function _ncaaHeader(summary, teams, activeTab) {
  const tabs = [
    { page:'nc-picks',    label:"Today's Picks" },
    { page:'nc-live',     label:'Live Games' },
    { page:'nc-matchup',  label:'Matchup Lab' },
    { page:'nc-trader',   label:'Paper Trader' },
    { page:'nc-accuracy', label:'Model Accuracy' },
    { page:'nc-teams',    label:'Team Explorer' },
    { page:'nc-tracker',  label:'Bet Tracker' },
    { page:'nc-bracket',  label:'Bracket' },
  ];
  return `<div class="tabs">
    ${tabs.map(t => `<button class="tab-btn${t.page===activeTab?' active':''}" onclick="navigate('${t.page}')">${t.label}</button>`).join('')}
  </div>`;
}

// ── Page: NC Picks & Odds ──────────────────────────────────────────────────
async function renderNcPicks() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  let summary, picks, teams;
  try {
    [summary, picks, teams] = await Promise.all([
      api.get('/api/ncaab/summary'),
      api.get('/api/ncaab/picks'),
      api.get('/api/ncaab/teams'),
    ]);
  } catch(e) { main.innerHTML = `<div class="error-state">${e.message}</div>`; return; }
  if (!summary.available) {
    main.innerHTML = `<div class="empty-state"><i data-lucide="trophy" style="width:32px;height:32px;display:block;margin:0 auto 14px;opacity:.4"></i><div>${summary.reason||'NCAA data unavailable.'}</div><p style="margin-top:12px;font-size:.8rem;color:var(--muted)">Run: <code>python scripts/update_ncaab_current.py</code></p></div>`;
    return;
  }

  const ps = picks.picks || [];
  const bets  = ps.filter(p => p.bet).sort((a,b) => ((b.kelly||0)-(a.kelly||0))||((b.best_edge||0)-(a.best_edge||0)));
  const favs  = ps.filter(p => (p.home_win_prob||0) >= 0.5 || (p.away_win_prob||0) >= 0.5)
                   .sort((a,b) => Math.max(b.home_win_prob||0,b.away_win_prob||0) - Math.max(a.home_win_prob||0,a.away_win_prob||0));
  const avgEdge = bets.length ? bets.reduce((s,p) => s+(p.best_edge||0), 0)/bets.length : 0;
  const sources = [...new Set(ps.filter(p=>p.best_source).map(p=>p.best_source))];
  const srcTags = sources.map(s => `<span class="badge badge-moderate">${s}</span>`).join(' ');

  let html = '';
  html += `<div class="metrics metrics-4" style="margin-bottom:20px">
    ${metricCard('Games Today', ps.length)}
    ${metricCard('Edge Bets Found', bets.length)}
    ${metricCard('Avg Edge', bets.length ? pct(avgEdge) : '—')}
    ${metricCard('Markets', srcTags || '—')}
  </div>`;

  if (!ps.length) { html += empty('No NCAA games with market prices found today.', 'inbox'); main.innerHTML = html; return; }

  html += `<div class="tabs">
    <button class="tab-btn active" onclick="switchTab(this,'nc-tab-bets')">Edge Bets (${bets.length})</button>
    <button class="tab-btn" onclick="switchTab(this,'nc-tab-favs')">Favorites to Win</button>
    <button class="tab-btn" onclick="switchTab(this,'nc-tab-all')">All Games (${ps.length})</button>
  </div>
  <div id="nc-tab-bets" class="tab-panel active">${bets.length ? bets.map(buildPickCard).join('') : empty('No bets meet edge threshold. Try lowering the slider.','sliders-horizontal')}</div>
  <div id="nc-tab-favs" class="tab-panel">${favs.map(buildPickCard).join('')}</div>
  <div id="nc-tab-all"  class="tab-panel">${ps.map(buildPickCard).join('')}</div>`;

  main.innerHTML = html;
}


// ── Page: NC Live Games ───────────────────────────────────────────────────
async function renderNcLive() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  let liveData;
  try {
    liveData = await api.get('/api/ncaab/live');
  } catch(e) { main.innerHTML = `<div class="error-state">${e.message}</div>`; return; }

  _startLiveRefresh('nc-live', '/api/ncaab/live', d => { liveData = d; renderNcLiveContent(liveData); });
  renderNcLiveContent(liveData);
}

function renderNcLiveContent(liveData) {
  const main = document.getElementById('main');
  let html = '';
  const byTipoffAsc = (a, b) => String(a.tipoff_utc || '').localeCompare(String(b.tipoff_utc || ''));
  const byTipoffDesc = (a, b) => String(b.tipoff_utc || '').localeCompare(String(a.tipoff_utc || ''));
  const byLivePriority = (a, b) => {
    const aRemain = Number.isFinite(Number(a.seconds_remaining)) ? Number(a.seconds_remaining) : Number.POSITIVE_INFINITY;
    const bRemain = Number.isFinite(Number(b.seconds_remaining)) ? Number(b.seconds_remaining) : Number.POSITIVE_INFINITY;
    if (aRemain !== bRemain) return aRemain - bRemain;
    return String(a.tipoff_utc || '').localeCompare(String(b.tipoff_utc || ''));
  };
  const live     = [...(liveData.in_progress || [])].sort(byLivePriority);
  const upcoming = [...(liveData.upcoming || [])].sort(byTipoffAsc);
  const final_   = [...(liveData.final || [])].sort(byTipoffDesc);

  html += `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
    <h1 style="margin:0">Live Games</h1>
    <button id="nc-ar-toggle" class="btn btn-secondary" onclick="toggleAutoRefresh('nc-live')" style="font-size:.75rem">${STATE.autoRefreshEnabled ? '⏸ Auto-refresh on' : '▶ Auto-refresh off'}</button>
  </div>`;
  html += `<div style="margin:-6px 0 16px;font-size:.8rem;color:var(--muted)">
    All live NCAA men's games for today. Market panels appear whenever live prices exist. Pre-game XGBoost panels appear whenever current team features are available.
  </div>`;

  function ncLiveCard(g) {
    const h = g.home_team || '', a = g.away_team || '';
    const hasLiveModel = g.live_home_prob != null && g.live_away_prob != null;
    const liveHProb = g.live_home_prob ?? g.market_home_live ?? g.market_home_implied ?? g.home_win_prob ?? 0.5;
    const liveAProb = g.live_away_prob ?? g.market_away_live ?? g.market_away_implied ?? g.away_win_prob ?? 0.5;
    const preHProb = g.pregame_home_prob ?? g.home_win_prob;
    const preAProb = g.pregame_away_prob ?? g.away_win_prob;
    const showModel = preHProb != null && preAProb != null;
    const isLive = g.game_status === 2;
    const kh = g.kalshi_home_prob, ka = g.kalshi_away_prob;
    const ph = g.polymarket_home_prob, pa = g.polymarket_away_prob;
    const edge = g.edge;
    const edgeTeam = (edge != null) ? (edge >= 0 ? h : a) : null;
    const edgeColor = (edge||0) > 0.03 ? 'var(--good)' : (edge||0) < -0.03 ? 'var(--bad)' : 'var(--muted)';

    let clockHtml = '';
    if (isLive && g.period_label && g.period_label !== 'Halftime' && g.period_label !== 'Final') {
      clockHtml = `<div class="clock-center">
        <div style="font-size:.68rem;color:var(--muted)">LIVE</div>
        <div class="period-label">${g.period_label}</div>
        <div class="clock-time">${g.clock_display || '—'}</div>
      </div>`;
    } else {
      clockHtml = `<div class="clock-center"><div class="status-text">${g.game_status_text || g.game_date || ''}</div></div>`;
    }

    const marketHtml = (kh != null || ph != null) ? `
      <div class="market-row">
        ${kh != null ? `<div class="market-panel">
          <div class="mkt-name">${KALSHI_LOGO}Kalshi</div>
          <span style="font-weight:700;color:${ka > kh ? 'var(--good)':'var(--bad)'}">${a} ${pct0(ka)}</span>
          <span style="color:var(--dimmer)"> vs </span>
          <span style="font-weight:700;color:${kh > ka ? 'var(--good)':'var(--bad)'}">${h} ${pct0(kh)}</span>
        </div>` : '<div></div>'}
        ${ph != null ? `<div class="market-panel">
          <div class="mkt-name">${POLYMARKET_LOGO}Polymarket</div>
          <span style="font-weight:700;color:${pa > ph ? 'var(--good)':'var(--bad)'}">${a} ${pct0(pa)}</span>
          <span style="color:var(--dimmer)"> vs </span>
          <span style="font-weight:700;color:${ph > pa ? 'var(--good)':'var(--bad)'}">${h} ${pct0(ph)}</span>
        </div>` : '<div></div>'}
      </div>` : '';

    const modelHtml = showModel ? `
      <div class="pregame-row">
        <div>
          <div class="pg-label">Pre-game model (XGBoost)</div>
          <div class="pg-probs">
            <span style="font-weight:700;font-size:.95rem;color:${preAProb > preHProb ? 'var(--good)':'var(--bad)'}">${a} ${pct0(preAProb)}</span>
            <span style="color:var(--dim);font-size:.78rem">vs</span>
            <span style="font-weight:700;font-size:.95rem;color:${preHProb > preAProb ? 'var(--good)':'var(--bad)'}">${h} ${pct0(preHProb)}</span>
          </div>
        </div>
        <div class="pg-hint">${isLive ? 'Top number is live<br>strip below is pre-game' : 'Pre-game baseline<br>before tipoff'}</div>
      </div>` : '';

    const edgeHtml = showModel && edge != null ? `<div class="edge-row" style="color:${edgeColor}">
      ${isLive ? 'Live model edge vs market' : 'Model edge vs market'}: ${edgeTeam} ${edge >= 0 ? '+' : ''}${pct(Math.abs(edge))}
    </div>` : '';



    return `<div class="live-card fade-in" data-game-id="${g.game_id || ''}">
      <div class="score-row">
        <div class="team-side">
          <div class="team-label">Away</div>
          <div class="team-abbr" style="color:${teamColor(a)}">${a}</div>
          <div class="score away-score">${g.away_score ?? 0}</div>
          <div class="win-prob away-prob" style="color:${liveAProb > liveHProb ? 'var(--good)':'var(--bad)'}">
            ${pct0(liveAProb)} <span class="to-win">${isLive ? (hasLiveModel ? 'live win %' : 'market live %') : 'to win'}</span>
          </div>
          ${g.pred_away_score != null && !isLive ? `<div class="pred-score-under"><span style="font-size:.58rem;font-weight:500;color:var(--muted);display:block;letter-spacing:.06em">PRED</span>${g.pred_away_score}</div>` : ''}
        </div>
        ${clockHtml}
        <div class="team-side right">
          <div class="team-label">Home</div>
          <div class="team-abbr" style="color:${teamColor(h)}">${h}</div>
          <div class="score home-score">${g.home_score ?? 0}</div>
          <div class="win-prob home-prob" style="color:${liveHProb > liveAProb ? 'var(--good)':'var(--bad)'}">
            ${pct0(liveHProb)} <span class="to-win">${isLive ? (hasLiveModel ? 'live win %' : 'market live %') : 'to win'}</span>
          </div>
          ${g.pred_home_score != null && !isLive ? `<div class="pred-score-under"><span style="font-size:.58rem;font-weight:500;color:var(--muted);display:block;letter-spacing:.06em">PRED</span>${g.pred_home_score}</div>` : ''}
        </div>
      </div>
      ${marketHtml}
      ${modelHtml}
      ${edgeHtml}
    </div>`;
  }

  let cardsHtml = '';
  if (!upcoming.length && !live.length && !final_.length) {
    cardsHtml = empty('No NCAA games found. Odds may not be available yet.', 'clock');
  } else {
    if (live.length) { cardsHtml += `<div class="section-label">Live</div>`; cardsHtml += live.map(ncLiveCard).join(''); }
    if (upcoming.length) { cardsHtml += `<div class="section-label">Upcoming</div>`; cardsHtml += upcoming.map(ncLiveCard).join(''); }
    if (final_.length) { cardsHtml += `<div class="section-label">Final</div>`; cardsHtml += final_.map(ncLiveCard).join(''); }
  }

  const ncContainer = document.getElementById('nc-live-cards');
  if (ncContainer) {
    // Seamless refresh — only swap the cards, keep the header
    ncContainer.innerHTML = cardsHtml;
  } else {
    // First render — build full page shell + cards
    main.innerHTML = html + `<div id="nc-live-cards">${cardsHtml}</div>`;
  }
}

// ── Page: NC Matchup Lab ──────────────────────────────────────────────────
async function renderNcMatchup() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  let summary, teams, teamList;
  try {
    [summary, teams, teamList] = await Promise.all([
      api.get('/api/ncaab/summary'),
      api.get('/api/ncaab/teams'),
      api.get('/api/ncaab/matchup/teams'),
    ]);
  } catch(e) { main.innerHTML = `<div class="error-state">${e.message}</div>`; return; }

  const allTeams = teamList.teams || [];
  const ta = STATE.ncMatchupA || allTeams[0] || '';
  const tb = STATE.ncMatchupB || allTeams[1] || '';

  let html = '';
  html += `<h1>NCAA Matchup Lab</h1>
  <p class="page-subtitle">Head-to-head breakdown with Elo ratings, seed context and predicted score</p>
  <div class="form-row">
    <label>Team A</label>
    <select id="nc-sel-a" onchange="onNcMatchupChange()">${allTeams.map(t=>`<option value="${t}" ${t===ta?'selected':''}>${t}</option>`).join('')}</select>
    <span style="color:var(--dim)">vs</span>
    <label>Team B</label>
    <select id="nc-sel-b" onchange="onNcMatchupChange()">${allTeams.map(t=>`<option value="${t}" ${t===tb?'selected':''}>${t}</option>`).join('')}</select>
  </div>
  <div id="nc-matchup-content">${loading()}</div>`;
  main.innerHTML = html;
  if (ta && tb && ta === tb) {
    document.getElementById('nc-matchup-content').innerHTML = empty('Choose two different teams.', 'git-compare');
    return;
  }
  loadNcMatchupData(ta, tb);
}

function onNcMatchupChange() {
  const ta = document.getElementById('nc-sel-a')?.value;
  const tb = document.getElementById('nc-sel-b')?.value;
  if (ta) STATE.ncMatchupA = ta;
  if (tb) STATE.ncMatchupB = tb;
  if (ta && tb) {
    if (ta === tb) {
      document.getElementById('nc-matchup-content').innerHTML = empty('Choose two different teams.', 'git-compare');
      return;
    }
    document.getElementById('nc-matchup-content').innerHTML = loading();
    loadNcMatchupData(ta, tb);
  }
}

async function loadNcMatchupData(ta, tb) {
  const cont = document.getElementById('nc-matchup-content');
  if (!cont) return;
  let d;
  try { d = await api.get('/api/ncaab/matchup', { team_a: ta, team_b: tb }); }
  catch(e) { cont.innerHTML = `<div class="error-state">${e.message}</div>`; return; }

  const pa = d.team_a_win_prob ?? 0.5, pb = d.team_b_win_prob ?? 0.5;
  const paRaw = d.team_a_win_prob_model ?? pa;
  const pbRaw = d.team_b_win_prob_model ?? pb;
  const seedEdgeA = d.team_a_seed_edge;
  const seedEdgeB = d.team_b_seed_edge;
  const bestSeedEdgeTeam = (seedEdgeA ?? -Infinity) >= (seedEdgeB ?? -Infinity) ? ta : tb;
  const bestSeedEdge = bestSeedEdgeTeam === ta ? seedEdgeA : seedEdgeB;
  const sa = d.stats_a || {}, sb = d.stats_b || {};

  function bar(label, va, vb, higherBetter, fmt) {
    if (va == null && vb == null) return '';
    const a = va ?? 0, b = vb ?? 0;
    const aWins = higherBetter ? a >= b : a <= b;
    const aC = aWins ? 'var(--good)' : 'var(--bad)';
    const bC = aWins ? 'var(--bad)' : 'var(--good)';
    const total = Math.abs(a) + Math.abs(b) || 1;
    const aW = Math.round(Math.abs(a)/total*100), bW = 100 - aW;
    const fv = v => {
      if (v == null) return '—';
      if (fmt === '%') return (v*100).toFixed(1)+'%';
      return Number(v).toFixed(1);
    };
    return `<div class="stat-bar-row">
      <div class="stat-val a" style="color:${aC}">${fv(va)}</div>
      <div style="flex:1">
        <div style="font-size:.68rem;color:var(--dim);margin-bottom:3px">${label}</div>
        <div style="display:flex;gap:2px">
          <div style="flex:${aW};height:5px;background:${aC};border-radius:2px"></div>
          <div style="flex:${bW};height:5px;background:${bC};border-radius:2px;order:1"></div>
        </div>
      </div>
      <div class="stat-val" style="color:${bC}">${fv(vb)}</div>
    </div>`;
  }

  let html = `<div class="matchup-hero fade-in">
    <div class="teams-row">
      <div class="mh-team">
        <div class="mh-abbr">${ta}</div>
        <div class="mh-prob" style="color:${pa>=pb?'var(--good)':'var(--bad)'}">${pct0(pa)}</div>
        <div style="font-size:.75rem;color:var(--muted)">to win${sa.seed?` · Seed ${sa.seed}`:''}</div>
      </div>
      <div class="vs-divider">vs</div>
      <div class="mh-team">
        <div class="mh-abbr">${tb}</div>
        <div class="mh-prob" style="color:${pb>=pa?'var(--good)':'var(--bad)'}">${pct0(pb)}</div>
        <div style="font-size:.75rem;color:var(--muted)">to win${sb.seed?` · Seed ${sb.seed}`:''}</div>
      </div>
    </div>
    <div class="fav-row">${d.favorite === 'Even'
      ? '<b style="color:var(--muted)">Even matchup</b> — <span style="color:var(--muted)">Coin flip</span>'
      : '<b>' + d.favorite + '</b> favored — <span style="color:var(--muted)">' + d.confidence_label + ' confidence</span>'
    }</div>
    <div style="font-size:.78rem;color:var(--muted);margin-top:6px">Win probabilities shown are final matchup-model outputs, not raw historical seed rates.</div>
    ${d.seed_baseline_prob != null ? `<div style="font-size:.8rem;color:var(--muted);margin-top:6px">Seed-baseline: ${pct0(d.seed_baseline_prob)} · Best seed edge: ${bestSeedEdgeTeam} ${pct(bestSeedEdge,1)}</div>` : ''}
    ${(Math.abs(paRaw - pa) > 1e-6 || Math.abs(pbRaw - pb) > 1e-6) ? `<div style="font-size:.75rem;color:var(--muted);margin-top:4px">Raw calibrated model: ${pct0(paRaw)} / ${pct0(pbRaw)} before Elo anchor</div>` : ''}
    ${d.pred_score_a != null ? `<div class="predicted-score-row">
      <span class="ps-team">${ta}</span>
      <span class="ps-score">${d.pred_score_a}</span>
      <span class="ps-label">Predicted Score</span>
      <span class="ps-score">${d.pred_score_b}</span>
      <span class="ps-team">${tb}</span>
    </div>
    <div style="font-size:.65rem;color:var(--muted);text-align:center;margin-top:4px">
      Score predicted by XGBoost regression model trained on historical game results
    </div>` : ''}
  </div>
  <div class="section-label" style="margin-top:16px">Stat Comparison</div>
  ${bar('Elo Rating', sa.elo, sb.elo, true, '1')}
  ${bar('Net Rating', sa.net_rtg, sb.net_rtg, true, '1')}
  ${bar('Off Rating', sa.off_rtg, sb.off_rtg, true, '1')}
  ${bar('Def Rating', sa.def_rtg, sb.def_rtg, false, '1')}
  ${bar('Win %', sa.win_pct, sb.win_pct, true, '%')}
  ${bar('Avg Margin', sa.avg_margin, sb.avg_margin, true, '1')}
  ${bar('SRS', sa.srs, sb.srs, true, '1')}
  ${bar('SOS', sa.sos, sb.sos, true, '1')}
  ${bar('eFG%', sa.efg, sb.efg, true, '%')}
  ${bar('TOV Rate', sa.tov_rate, sb.tov_rate, false, '%')}
  ${bar('Last 10 Win%', sa.last10_win_pct, sb.last10_win_pct, true, '%')}
  ${bar('Last 10 Margin', sa.last10_margin, sb.last10_margin, true, '1')}`;

  cont.innerHTML = html;
}

// ── Page: NC Model Accuracy ───────────────────────────────────────────────
async function renderNcAccuracy() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  let summary, teams, acc;
  try {
    [summary, teams, acc] = await Promise.all([
      api.get('/api/ncaab/summary'),
      api.get('/api/ncaab/teams'),
      api.get('/api/ncaab/accuracy'),
    ]);
  } catch(e) { main.innerHTML = `<div class="error-state">${e.message}</div>`; return; }

  let html = '';
  html += `<h1>NCAA Model Accuracy</h1>
  <p class="page-subtitle">Model evaluated on historical tournament matchups (2003–2025)</p>`;

  if (acc.error) {
    html += empty('Model metrics not available yet. Train the NCAA model first.', 'cpu');
    main.innerHTML = html; return;
  }

  const m = acc.metrics || {};
  html += `<div class="metrics metrics-4">
    ${metricCard('Accuracy', m.accuracy != null ? pct(m.accuracy) : '—', null, '', 'Correct winner predictions')}
    ${metricCard('AUC-ROC', m.auc_roc != null ? Number(m.auc_roc).toFixed(3) : '—', null, '', 'Discrimination · 1.0 = perfect')}
    ${metricCard('Brier Score', m.brier_score != null ? Number(m.brier_score).toFixed(4) : '—', null, '', 'Calibration error · lower is better')}
    ${metricCard('Games Evaluated', m.n_games ?? m.num_games ?? '—', null, '', 'Games in test set')}
  </div>`;

  // Show all other metrics as a table
  const skip = new Set(['accuracy','auc_roc','brier_score','n_games','num_games']);
  const extras = Object.entries(m).filter(([k]) => !skip.has(k));
  if (extras.length) {
    html += `<div class="section-label" style="margin-top:16px">All Metrics</div>
    <table class="data-table"><tbody>`;
    extras.forEach(([k, v]) => {
      const disp = typeof v === 'number' ? (Math.abs(v) < 1 ? pct(v) : Number(v).toFixed(3)) : String(v);
      html += `<tr><td style="color:var(--muted);font-size:.8rem">${k}</td><td style="font-weight:600">${disp}</td></tr>`;
    });
    html += `</tbody></table>`;
  }

  html += `<div class="empty-state" style="margin-top:24px;padding:20px">
    <div class="icon">ℹ️</div>
    <div style="font-size:.85rem;color:var(--muted)">NCAA model trained on historical March Madness tournament data (2003–2025). Evaluates matchup win probability using team features, Elo, and seed-adjusted baselines.</div>
  </div>`;

  main.innerHTML = html;
}

// ── Page: NC Bet Tracker ──────────────────────────────────────────────────
async function renderNcTracker() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  let summary, teams, d;
  try {
    [summary, teams, d] = await Promise.all([
      api.get('/api/ncaab/summary'),
      api.get('/api/ncaab/teams'),
      api.get('/api/ncaab/bet-tracker'),
    ]);
  } catch(e) { main.innerHTML = `<div class="error-state">${e.message}</div>`; return; }

  let html = '';
  html += `<h1>NCAA Bet Tracker</h1>
  <p class="page-subtitle">Track edge-bet results on NCAA games to validate model accuracy</p>`;

  const s = d.summary || {};
  html += `<div class="metrics metrics-4">
    ${metricCard('Record', `${s.wins||0}W – ${s.losses||0}L`)}
    ${metricCard('Win Rate', s.win_rate != null ? pct(s.win_rate) : '—')}
    ${metricCard('Flat ROI', s.flat_roi != null ? pct(s.flat_roi) : '—')}
    ${metricCard('Total Bets', s.total_bets || 0)}
  </div>
  <div id="nc-tracker-chart" class="chart-container" style="height:260px;margin-bottom:20px"></div>`;

  const bets = d.bets || [];
  if (bets.length) {
    html += `<h2>Settled Trades</h2><table class="data-table">
      <thead><tr><th>Date</th><th>Game</th><th>Bet</th><th>Market</th><th>Entry</th><th>P/L</th><th>Result</th></tr></thead>
      <tbody>${bets.map(b => {
        const isWin = b.win === 1 || b.win === true;
        const col = isWin ? 'var(--good)' : 'var(--bad)';
        return `<tr>
          <td>${(b.game_date||'').toString().slice(0,10)}</td>
          <td>${b.away_team||''}@${b.home_team||''}</td>
          <td style="font-weight:600">${b.contract_team||b.bet_side||'—'}</td>
          <td>${b.market_source||''}</td>
          <td>${pct0(b.entry_price)}</td>
          <td style="color:${col}">${b.pnl != null ? moneySign(b.pnl) : '—'}</td>
          <td><span class="badge ${isWin?'badge-win':'badge-loss'}">${isWin?'WIN':'LOSS'}</span></td>
        </tr>`;
      }).join('')}</tbody>
    </table>`;
  } else {
    html += empty('No settled NCAA trades yet. Log picks from the Paper Trader page.', 'clipboard-list');
  }

  main.innerHTML = html;

  const cum = d.cumulative_pnl || [];
  if (cum.length) {
    Plotly.newPlot('nc-tracker-chart', [{
      x: cum.map(r=>r.game_date), y: cum.map(r=>r.cumulative),
      mode:'lines+markers', fill:'tozeroy', fillcolor:'rgba(34,197,94,.08)',
      line:{color:'#22c55e',width:2}, marker:{size:4},
    }], { ..._plotTheme(), height:240,
         yaxis_title:'Cumulative P/L ($)', showlegend:false, margin:{t:10,b:30} });
  }
}

// ── Page: NC Paper Trader ──────────────────────────────────────────────────
async function renderNcTrader() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  let summary, teams, stateData, candidates, positions;
  try {
    [summary, teams, stateData, candidates, positions] = await Promise.all([
      api.get('/api/ncaab/summary'),
      api.get('/api/ncaab/teams'),
      api.get('/api/ncaab/paper-trader/state'),
      api.get('/api/ncaab/paper-trader/candidates').catch(() => ({candidates:[]})),
      api.get('/api/ncaab/paper-trader/positions').catch(() => ({open:[],settled:[]})),
    ]);
  } catch(e) { main.innerHTML = `<div class="error-state">${e.message}</div>`; return; }

  const bk = stateData.bankroll || {};
  const totalPnl = (bk.realized_pnl || 0) + (bk.unrealized_pnl || 0);
  const totalRet = bk.starting_bankroll ? totalPnl / bk.starting_bankroll : 0;
  const pnlClass = totalPnl >= 0 ? 'good' : 'bad';
  const pnlColor = totalPnl >= 0 ? 'var(--good)' : 'var(--bad)';

  let html = '';
  html += `
  <div class="pnl-card ${pnlClass}">
    <div class="pnl-main">
      <div class="pnl-label">NCAAB Paper P/L</div>
      <div class="pnl-value" style="color:${pnlColor}">${totalPnl >= 0 ? '+' : '−'}$${Math.abs(totalPnl).toFixed(2)}</div>
      <div class="pnl-return" style="color:${pnlColor}">${totalRet >= 0 ? '+' : ''}${(totalRet*100).toFixed(1)}% on $${(bk.starting_bankroll||1000).toFixed(0)}</div>
    </div>
    <div class="pnl-breakdown">
      <div class="pnl-breakdown-row"><span class="lbl">Realized </span><span style="color:${(bk.realized_pnl||0)>=0?'var(--good)':'var(--bad)'};font-weight:600">${moneySign(bk.realized_pnl||0)}</span></div>
      <div class="pnl-breakdown-row"><span class="lbl">Unrealized </span><span style="color:${(bk.unrealized_pnl||0)>=0?'var(--good)':'var(--bad)'};font-weight:600">${moneySign(bk.unrealized_pnl||0)}</span></div>
    </div>
  </div>
  <div class="metrics metrics-4">
    ${metricCard('Bankroll', money(bk.estimated_equity || bk.starting_bankroll || 1000))}
    ${metricCard('Open Bets', stateData.open_count ?? 0)}
    ${metricCard('Settled', stateData.settled_count ?? 0)}
    ${metricCard('Cash Available', money(bk.available_cash))}
  </div>
  <div class="btn-row">
    <button class="btn btn-primary" onclick="logNcaabTrades()">Log Today's Trades</button>
    <button class="btn btn-secondary" onclick="renderNcTrader()">↺ Refresh</button>
  </div>`;

  const cands = candidates.candidates || [];
  html += `<div class="section-label">Today's Candidates (${cands.length})</div>`;
  if (!cands.length) {
    html += `<div style="padding:16px 0;color:var(--muted);font-size:.82rem">No candidates meet the edge threshold.</div>`;
  } else {
    const byGame = {};
    cands.forEach(c => { const k = `${c.away_team||'?'} @ ${c.home_team||'?'}`; if (!byGame[k]) byGame[k]=[]; byGame[k].push(c); });
    Object.entries(byGame).forEach(([game, trades]) => {
      html += `<div style="font-size:.72rem;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin-top:12px;margin-bottom:6px">${game}</div>`;
      trades.forEach(t => {
        const edgePct = t.edge || t.best_edge || 0;
        html += `<div class="trade-card fade-in">
          <div class="tc-team"><div class="name">${t.contract_team || t.bet_team || '?'}</div><div class="sub">${t.market_source||'?'} · ${t.bet_side||'?'}</div></div>
          <div class="tc-col"><div class="lbl">Model</div><div class="val">${pct0(t.model_prob)}</div></div>
          <div class="tc-col"><div class="lbl">Market</div><div class="val">${pct0(t.market_prob || t.entry_price)}</div></div>
          <div class="tc-col"><div class="lbl">Edge</div><div class="val" style="color:var(--good)">${edgePct>=0?'+':''}${pct(edgePct)}</div></div>
          <div class="tc-right"><div class="lbl">Stake</div><div class="pnl">${money(t.stake)}</div></div>
        </div>`;
      });
    });
  }

  const openPos = positions.open || [];
  html += `<div class="section-label">Open Positions (${openPos.length})</div>`;
  if (!openPos.length) html += `<div style="padding:16px 0;color:var(--muted);font-size:.82rem">No open NCAAB positions.</div>`;
  else openPos.forEach(t => {
    html += `<div class="trade-card">
      <div class="tc-team"><div class="name">${t.contract_team || t.bet_team || '?'}</div><div class="sub">${t.market_source} · ${(t.game_date||'').slice(0,10)}</div></div>
      <div class="tc-col"><div class="lbl">Entry</div><div class="val">${pct0(t.entry_price)}</div></div>
      <div class="tc-col"><div class="lbl">Edge</div><div class="val" style="color:var(--good)">${pct(t.edge)}</div></div>
      <div class="tc-right"><div class="lbl">Stake</div><div class="pnl">${money(t.stake)}</div></div>
    </div>`;
  });

  const settledPos = positions.settled || [];
  if (settledPos.length) {
    html += `<div class="section-label">Settled (${settledPos.length})</div>`;
    settledPos.forEach(t => {
      const won = t.win || (t.pnl||0) > 0;
      html += `<div class="trade-card ${won?'win-card':'loss-card'}">
        <div class="tc-team"><div class="name">${t.contract_team || t.bet_team || '?'}</div><div class="sub">${t.market_source} · ${(t.game_date||'').slice(0,10)}</div></div>
        <div class="tc-col"><div class="lbl">Entry</div><div class="val">${pct0(t.entry_price)}</div></div>
        <div class="tc-col"><div class="lbl">Result</div><div class="val"><span class="badge ${won?'badge-win':'badge-loss'}">${won?'Win':'Loss'}</span></div></div>
        <div class="tc-right"><div class="lbl">P/L</div><div class="pnl" style="color:${(t.pnl||0)>=0?'var(--good)':'var(--bad)'}">${moneySign(t.pnl)}</div></div>
      </div>`;
    });
  }
  main.innerHTML = html;
}

// ── Page: NC Bracket ───────────────────────────────────────────────────────
async function renderNcBracket() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  let summary, bracket, teams;
  try {
    [summary, bracket, teams] = await Promise.all([
      api.get('/api/ncaab/summary'),
      api.get('/api/ncaab/bracket'),
      api.get('/api/ncaab/teams'),
    ]);
  } catch(e) { main.innerHTML = `<div class="error-state">${e.message}</div>`; return; }
  const br = bracket.bracket || [];
  const ts = teams.teams || [];
  let html = '';
  if (!br.length) html += empty('No bracket data available.', 'trophy');
  else html += buildBracketHTML(br, ts);
  main.innerHTML = html;
}

// ── Page: NC Team Rankings ─────────────────────────────────────────────────
async function renderNcTeams() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  let summary, teams;
  try {
    [summary, teams] = await Promise.all([
      api.get('/api/ncaab/summary'),
      api.get('/api/ncaab/teams'),
    ]);
  } catch(e) { main.innerHTML = `<div class="error-state">${e.message}</div>`; return; }
  let html = '';
  const ts = teams.teams || [];
  if (!ts.length) { html += empty('No team data available.'); }
  else {
    const displayCols = ['TeamName','seed_num','elo','win_pct','avg_margin','net_rtg','off_rtg','def_rtg'];
    const availCols = displayCols.filter(c => c in (ts[0]||{}));
    const colLabels = {TeamName:'Team',seed_num:'Seed',elo:'Elo',win_pct:'Win%',avg_margin:'Margin',net_rtg:'Net Rtg',off_rtg:'Off Rtg',def_rtg:'Def Rtg'};
    html += `<table class="data-table"><thead><tr>${availCols.map(c=>`<th>${colLabels[c]||c}</th>`).join('')}</tr></thead>
      <tbody>${ts.slice(0,100).map(t => `<tr>${availCols.map(c => {
        let v = t[c];
        if (v == null) return '<td>—</td>';
        if (typeof v === 'number') v = c === 'win_pct' ? pct0(v) : Number(v).toFixed(1);
        return `<td>${String(v).slice(0,22)}</td>`;
      }).join('')}</tr>`).join('')}</tbody>
    </table>`;
  }
  main.innerHTML = html;
}

async function logNcaabTrades() {
  try {
    const res = await api.post('/api/ncaab/paper-trader/log-trades');
    alert(res.message || `Logged ${res.logged || 0} trades`);
    renderNcTrader();
  } catch(e) { alert('Error: ' + e.message); }
}
// ─────────────────────────────────────────────────────────────────────────────
// Page: System
// ─────────────────────────────────────────────────────────────────────────────
async function renderSystem() {
  const main = document.getElementById('main');
  main.innerHTML = loading();
  let health, alerts;
  try {
    [health, alerts] = await Promise.all([
      api.get('/api/system/health'),
      api.get('/api/system/alerts'),
    ]);
  } catch(e) {
    main.innerHTML = `<h1>System</h1>
  <p class="page-subtitle">Model status, data freshness, and recent system alerts</p><div class="error-state">${e.message}</div>`;
    return;
  }

  const statusDot = ok => `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${ok?'var(--good)':'var(--bad)'};margin-right:6px"></span>`;
  let html = `<h1>System</h1>
  <div class="metrics metrics-4">
    ${metricCard('NBA Model', `${statusDot(health.model_loaded)}${health.model_loaded ? 'Loaded' : 'Not Loaded'}`)}
    ${metricCard('NCAAB Model', `${statusDot(health.ncaab_model_loaded)}${health.ncaab_model_loaded ? 'Loaded' : 'Not Loaded'}`)}
    ${metricCard('Snapshot Age', health.snapshot_age_seconds != null ? `${Math.round(health.snapshot_age_seconds/60)}m ago` : '—', null, health.snapshot_stale ? 'bad' : 'good')}
    ${metricCard('Alerts (24h)', health.alerts_24h ?? 0, null, (health.alerts_24h||0) > 0 ? 'bad' : 'muted')}
  </div>
  <div class="metrics metrics-3">
    ${metricCard('Model Trained', health.model_trained_at ? health.model_trained_at.slice(0,10) : '—')}
    ${metricCard('Paper Trades', health.paper_trades_count ?? 0)}
    ${metricCard('Latest Snapshot', health.latest_snapshot_at ? health.latest_snapshot_at.slice(0,19).replace('T',' ') : 'Never')}
  </div>
  <div class="btn-row">
    <button class="btn btn-secondary" onclick="settleResults()">Settle Results</button>
  </div>`;

  const als = alerts.alerts || [];
  html += `<h2>Recent Alerts</h2>`;
  if (!als.length) {
    html += `<div style="color:var(--muted);font-size:.82rem">No alerts in the last 24 hours. ✓</div>`;
  } else {
    html += als.map(a => {
      const sev = a.severity || 'info';
      const cls = sev === 'error' ? 'bad' : sev === 'warning' ? 'warn' : 'blue';
      return `<div style="border-left:3px solid var(--${cls});background:var(--${cls}-bg);border-radius:var(--radius);padding:10px 14px;margin-bottom:6px;font-size:.8rem">
        <div style="font-weight:600">${a.code || ''} <span style="color:var(--muted);font-weight:400">· ${(a.created_at||'').slice(0,19).replace('T',' ')}</span></div>
        <div style="margin-top:2px">${a.message || ''}</div>
      </div>`;
    }).join('');
  }
  main.innerHTML = html;
}

async function settleResults() {
  const btn = event.target;
  btn.textContent = 'Running...'; btn.disabled = true;
  try {
    const r = await api.post('/api/system/settle-results');
    alert(r.success ? `✅ ${r.output || 'Done'}` : `❌ ${r.output || 'Failed'}`);
  } catch(e) { alert('Error: ' + e.message); }
  finally { btn.textContent = 'Settle Results'; btn.disabled = false; }
}

// ── Tab helper ────────────────────────────────────────────────────────────────
function switchTab(btn, panelId) {
  const container = btn.closest('.tabs').parentElement;
  container.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  container.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  const panel = document.getElementById(panelId);
  if (panel) panel.classList.add('active');
}

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  initTheme();
  _createIcons();

  document.querySelectorAll('#sidebar a').forEach(a => {
    a.addEventListener('click', e => {
      e.preventDefault();
      const page = a.dataset.page;
      window.location.hash = '#' + page;
      navigate(page);
    });
  });

  const hash = window.location.hash.replace('#','') || 'picks';
  navigate(hash);
});

window.addEventListener('hashchange', () => {
  const page = window.location.hash.replace('#','') || 'picks';
  navigate(page);
});
