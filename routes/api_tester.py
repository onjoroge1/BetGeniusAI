"""
Interactive API Tester — Purpose-built testing page for major BetGenius APIs.
Served at GET /api-tester (no auth required).
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/api-tester", response_class=HTMLResponse, include_in_schema=False)
async def api_tester_page():
    return HTML_PAGE


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BetGenius API Tester</title>
<style>
  :root {
    --bg: #0f1117; --surface: #1a1d27; --surface2: #252830;
    --border: #2e313a; --text: #e4e4e7; --muted: #8b8d97;
    --accent: #6366f1; --accent2: #818cf8; --green: #22c55e;
    --red: #ef4444; --yellow: #eab308; --blue: #3b82f6;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: var(--bg); color: var(--text); line-height: 1.5; }
  .header { background: var(--surface); border-bottom: 1px solid var(--border);
            padding: 12px 24px; display: flex; align-items: center; gap: 16px; }
  .header h1 { font-size: 18px; font-weight: 600; }
  .header h1 span { color: var(--accent2); }
  .api-key-bar { display: flex; align-items: center; gap: 8px; margin-left: auto; font-size: 13px; }
  .api-key-bar input { background: var(--surface2); border: 1px solid var(--border);
    color: var(--text); padding: 4px 10px; border-radius: 4px; width: 260px; font-size: 12px; font-family: monospace; }
  .tabs { display: flex; background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 24px; }
  .tab { padding: 10px 20px; cursor: pointer; font-size: 13px; font-weight: 500;
         color: var(--muted); border-bottom: 2px solid transparent; transition: all 0.2s; }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--accent2); border-bottom-color: var(--accent); }
  .panel { display: none; padding: 20px 24px; }
  .panel.active { display: block; }
  .controls { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; margin-bottom: 16px; }
  .field { display: flex; flex-direction: column; gap: 4px; }
  .field label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
  .field select, .field input { background: var(--surface2); border: 1px solid var(--border);
    color: var(--text); padding: 6px 10px; border-radius: 4px; font-size: 13px; }
  .field select { min-width: 160px; }
  .field input[type=number] { width: 100px; }
  .field input[type=text] { width: 140px; }
  .btn { background: var(--accent); color: white; border: none; padding: 7px 18px;
         border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: 500; transition: 0.2s; }
  .btn:hover { background: var(--accent2); }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-sm { padding: 3px 10px; font-size: 11px; background: var(--surface2); border: 1px solid var(--border); }
  .btn-sm:hover { background: var(--border); }
  .btn-predict { background: var(--green); }
  .btn-predict:hover { background: #16a34a; }
  .status-bar { font-size: 12px; color: var(--muted); margin-bottom: 12px; }
  .status-bar .time { color: var(--yellow); }
  .results { background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
             padding: 16px; min-height: 100px; }
  .match-card { background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
                padding: 12px 16px; margin-bottom: 10px; }
  .match-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .match-teams { font-weight: 600; font-size: 14px; }
  .match-meta { font-size: 11px; color: var(--muted); }
  .match-odds { display: flex; gap: 8px; margin-top: 6px; font-size: 12px; }
  .match-odds .prob { padding: 2px 8px; border-radius: 3px; background: var(--bg); }
  .match-score { font-size: 16px; font-weight: 700; color: var(--accent2); }
  .prob-bar { display: flex; height: 24px; border-radius: 4px; overflow: hidden; margin: 8px 0; font-size: 11px; font-weight: 600; }
  .prob-bar div { display: flex; align-items: center; justify-content: center; color: white; min-width: 30px; }
  .prob-h { background: var(--blue); }
  .prob-d { background: var(--muted); }
  .prob-a { background: var(--red); }
  .model-table { width: 100%; border-collapse: collapse; font-size: 12px; margin: 8px 0; }
  .model-table th { text-align: left; padding: 6px 10px; background: var(--bg); color: var(--muted);
    font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
  .model-table td { padding: 6px 10px; border-top: 1px solid var(--border); }
  .model-table .status-primary { color: var(--green); font-weight: 600; }
  .model-table .status-shadow { color: var(--muted); }
  .badge { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: 600; }
  .badge-green { background: #16a34a33; color: var(--green); }
  .badge-yellow { background: #eab30833; color: var(--yellow); }
  .badge-red { background: #ef444433; color: var(--red); }
  .badge-blue { background: #3b82f633; color: var(--blue); }
  .info-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; margin-top: 12px; }
  .info-item { background: var(--surface2); padding: 10px; border-radius: 4px; }
  .info-item .label { font-size: 10px; color: var(--muted); text-transform: uppercase; }
  .info-item .value { font-size: 14px; font-weight: 600; margin-top: 2px; }
  .raw-toggle { cursor: pointer; color: var(--accent2); font-size: 12px; margin-top: 8px; }
  .raw-json { display: none; background: var(--bg); border: 1px solid var(--border);
    border-radius: 4px; padding: 10px; margin-top: 6px; font-family: monospace;
    font-size: 11px; max-height: 400px; overflow: auto; white-space: pre-wrap; word-break: break-all; }
  .health-card { background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
    padding: 14px; margin-bottom: 10px; display: flex; align-items: center; gap: 12px; }
  .health-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  .health-dot.green { background: var(--green); }
  .health-dot.red { background: var(--red); }
  .health-dot.yellow { background: var(--yellow); }
  .loading { color: var(--muted); font-style: italic; }
  .checkbox-row { display: flex; gap: 16px; align-items: center; }
  .checkbox-row label { font-size: 12px; display: flex; align-items: center; gap: 4px; cursor: pointer; }
</style>
</head>
<body>
<div class="header">
  <h1><span>BetGenius</span> API Tester</h1>
  <div class="api-key-bar">
    <span>API Key:</span>
    <input type="text" id="apiKey" value="betgenius_secure_key_2024">
  </div>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('market')">Market</div>
  <div class="tab" onclick="switchTab('predict')">Predict</div>
  <div class="tab" onclick="switchTab('performance')">Performance</div>
  <div class="tab" onclick="switchTab('health')">Health</div>
</div>

<!-- MARKET TAB -->
<div id="panel-market" class="panel active">
  <div class="controls">
    <div class="field">
      <label>League</label>
      <select id="mkt-league">
        <option value="">All Leagues</option>
        <option value="39" selected>Premier League</option>
        <option value="140">La Liga</option>
        <option value="135">Serie A</option>
        <option value="78">Bundesliga</option>
        <option value="61">Ligue 1</option>
        <option value="2">Champions League</option>
        <option value="45">FA Cup</option>
        <option value="3">Europa League</option>
      </select>
    </div>
    <div class="field">
      <label>Status</label>
      <select id="mkt-status">
        <option value="upcoming">Upcoming</option>
        <option value="finished" selected>Finished</option>
        <option value="live">Live</option>
        <option value="all">All</option>
      </select>
    </div>
    <div class="field">
      <label>Limit</label>
      <input type="number" id="mkt-limit" value="5" min="1" max="50">
    </div>
    <button class="btn" onclick="fetchMarket()">Fetch Market</button>
  </div>
  <div id="mkt-status-bar" class="status-bar"></div>
  <div id="mkt-results" class="results"><span class="loading">Select options and click Fetch Market</span></div>
  <div class="raw-toggle" onclick="toggleRaw('mkt-raw')">Show raw JSON</div>
  <pre id="mkt-raw" class="raw-json"></pre>
</div>

<!-- PREDICT TAB -->
<div id="panel-predict" class="panel">
  <div class="controls">
    <div class="field">
      <label>Match ID</label>
      <input type="number" id="pred-matchid" placeholder="e.g. 1379260">
    </div>
    <div class="checkbox-row">
      <label><input type="checkbox" id="pred-analysis"> AI Analysis</label>
      <label><input type="checkbox" id="pred-markets"> Additional Markets</label>
      <label><input type="checkbox" id="pred-sgp"> SGP</label>
    </div>
    <button class="btn btn-predict" onclick="fetchPredict()">Predict</button>
  </div>
  <div id="pred-status-bar" class="status-bar"></div>
  <div id="pred-results" class="results"><span class="loading">Enter a match ID or use the Market tab to find one</span></div>
  <div class="raw-toggle" onclick="toggleRaw('pred-raw')">Show raw JSON</div>
  <pre id="pred-raw" class="raw-json"></pre>
</div>

<!-- PERFORMANCE TAB -->
<div id="panel-performance" class="panel">
  <div class="controls">
    <div class="field">
      <label>Window</label>
      <select id="perf-window">
        <option value="7d">7 Days</option>
        <option value="30d" selected>30 Days</option>
        <option value="90d">90 Days</option>
        <option value="all">All Time</option>
      </select>
    </div>
    <button class="btn" onclick="fetchPerformance()">Load Performance</button>
    <button class="btn" onclick="fetchAB()" style="background:var(--blue)">Load A/B Results</button>
  </div>
  <div id="perf-status-bar" class="status-bar"></div>
  <div id="perf-results" class="results"><span class="loading">Click Load Performance to fetch model metrics</span></div>
  <div class="raw-toggle" onclick="toggleRaw('perf-raw')">Show raw JSON</div>
  <pre id="perf-raw" class="raw-json"></pre>
</div>

<!-- HEALTH TAB -->
<div id="panel-health" class="panel">
  <button class="btn" onclick="fetchHealth()">Refresh Health</button>
  <div id="health-status-bar" class="status-bar" style="margin-top:8px"></div>
  <div id="health-results" class="results" style="margin-top:12px"><span class="loading">Click Refresh Health</span></div>
</div>

<script>
const BASE = window.location.origin;
function getKey() { return document.getElementById('apiKey').value; }
function headers() { return { 'Authorization': 'Bearer ' + getKey(), 'Content-Type': 'application/json', 'Accept': 'application/json' }; }

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelector(`.tab[onclick*="${name}"]`).classList.add('active');
  document.getElementById('panel-' + name).classList.add('active');
  if (name === 'health') fetchHealth();
}

function toggleRaw(id) {
  const el = document.getElementById(id);
  el.style.display = el.style.display === 'block' ? 'none' : 'block';
}

function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

// ── MARKET ──
async function fetchMarket() {
  const league = document.getElementById('mkt-league').value;
  const status = document.getElementById('mkt-status').value;
  const limit = document.getElementById('mkt-limit').value;
  let url = `${BASE}/market?status=${status}&limit=${limit}`;
  if (league) url += `&league_id=${league}`;

  document.getElementById('mkt-results').innerHTML = '<span class="loading">Loading...</span>';
  const t0 = performance.now();
  try {
    const res = await fetch(url, { headers: headers() });
    const ms = Math.round(performance.now() - t0);
    const data = await res.json();
    document.getElementById('mkt-status-bar').innerHTML = `<span class="time">${ms}ms</span> &middot; HTTP ${res.status} &middot; ${data.matches?.length || 0} matches`;
    document.getElementById('mkt-raw').textContent = JSON.stringify(data, null, 2);

    if (!res.ok) { document.getElementById('mkt-results').innerHTML = `<span style="color:var(--red)">Error: ${JSON.stringify(data.detail)}</span>`; return; }

    let html = '';
    for (const m of (data.matches || [])) {
      const sc = m.final_result?.score || m.score || {};
      const scoreStr = sc.home != null ? `<span class="match-score">${sc.home} - ${sc.away}</span>` : '';
      const novig = m.odds?.novig_current;
      const model = m.models?.v1_consensus;
      let oddsHtml = '';
      if (novig) {
        oddsHtml = `<div class="match-odds">
          <span class="prob">H ${(novig.home*100).toFixed(1)}%</span>
          <span class="prob">D ${(novig.draw*100).toFixed(1)}%</span>
          <span class="prob">A ${(novig.away*100).toFixed(1)}%</span>
        </div>`;
      }
      let modelHtml = '';
      if (model) {
        modelHtml = `<div style="font-size:11px;color:var(--muted);margin-top:4px">
          Model: ${model.source || 'v1'} | Pick: ${model.pick} | Conf: ${(model.confidence*100).toFixed(0)}%</div>`;
      }
      html += `<div class="match-card">
        <div class="match-header">
          <div>
            <div class="match-teams">${escHtml(m.home?.name||'?')} vs ${escHtml(m.away?.name||'?')}</div>
            <div class="match-meta">ID: ${m.match_id} &middot; ${m.league?.name||''} &middot; ${m.status} &middot; ${new Date(m.kickoff_at).toLocaleDateString()}</div>
          </div>
          <div style="display:flex;gap:8px;align-items:center">
            ${scoreStr}
            <button class="btn btn-sm" onclick="predictMatch(${m.match_id})">Predict &rarr;</button>
          </div>
        </div>
        ${oddsHtml}${modelHtml}
        <div style="font-size:11px;color:var(--muted);margin-top:4px">Books: ${Object.keys(m.odds?.books||{}).length}</div>
      </div>`;
    }
    document.getElementById('mkt-results').innerHTML = html || '<span class="loading">No matches found</span>';
  } catch(e) {
    document.getElementById('mkt-results').innerHTML = `<span style="color:var(--red)">Fetch error: ${e.message}</span>`;
  }
}

function predictMatch(matchId) {
  document.getElementById('pred-matchid').value = matchId;
  switchTab('predict');
  fetchPredict();
}

// ── PREDICT ──
async function fetchPredict() {
  const matchId = parseInt(document.getElementById('pred-matchid').value);
  if (!matchId) { document.getElementById('pred-results').innerHTML = '<span style="color:var(--yellow)">Enter a match ID</span>'; return; }

  const body = {
    match_id: matchId,
    include_analysis: document.getElementById('pred-analysis').checked,
    include_additional_markets: document.getElementById('pred-markets').checked,
    include_sgp: document.getElementById('pred-sgp').checked
  };

  document.getElementById('pred-results').innerHTML = '<span class="loading">Predicting...</span>';
  const t0 = performance.now();
  try {
    const res = await fetch(`${BASE}/predict`, { method: 'POST', headers: headers(), body: JSON.stringify(body) });
    const ms = Math.round(performance.now() - t0);
    const data = await res.json();
    document.getElementById('pred-status-bar').innerHTML = `<span class="time">${ms}ms</span> &middot; HTTP ${res.status} &middot; Server: ${data.processing_time?.toFixed(1)||'?'}s`;
    document.getElementById('pred-raw').textContent = JSON.stringify(data, null, 2);

    if (!res.ok) { document.getElementById('pred-results').innerHTML = `<span style="color:var(--red)">Error: ${JSON.stringify(data.detail)}</span>`; return; }

    const p = data.predictions || {};
    const mi = data.match_info || {};
    const info = data.model_info || {};
    const fd = p.final_decision || {};

    // Probability bar
    const hPct = ((p.home_win||0)*100).toFixed(1);
    const dPct = ((p.draw||0)*100).toFixed(1);
    const aPct = ((p.away_win||0)*100).toFixed(1);

    // Models table
    let modelsHtml = '';
    for (const m of (p.models || [])) {
      const statusCls = m.status === 'primary' ? 'status-primary' : 'status-shadow';
      const preds = m.predictions;
      const badge = m.status === 'primary' ? '<span class="badge badge-green">PRIMARY</span>'
                  : m.status === 'shadow' ? '<span class="badge badge-blue">SHADOW</span>'
                  : `<span class="badge badge-yellow">${m.status}</span>`;
      if (preds) {
        const ag = m.agreement;
        const agreeStr = ag ? (ag.agrees_with_primary ? '&#10003;' : '&#10007;') : '';
        modelsHtml += `<tr>
          <td class="${statusCls}">${m.id} ${badge}</td>
          <td>${(preds.home_win*100).toFixed(1)}%</td>
          <td>${(preds.draw*100).toFixed(1)}%</td>
          <td>${(preds.away_win*100).toFixed(1)}%</td>
          <td>${m.recommended_bet||''}</td>
          <td>${m.confidence?.toFixed(3)||''}</td>
          <td>${agreeStr} ${ag?.confidence_delta!=null ? (ag.confidence_delta>0?'+':'')+ag.confidence_delta.toFixed(3) : ''}</td>
        </tr>`;
      } else {
        modelsHtml += `<tr><td class="${statusCls}">${m.id} ${badge}</td><td colspan="6" style="color:var(--muted)">${m.reason||'unavailable'}</td></tr>`;
      }
    }

    const convBadge = fd.conviction_tier === 'premium' ? 'badge-green'
                    : fd.conviction_tier === 'strong' ? 'badge-blue' : 'badge-yellow';

    const html = `
      <div style="font-size:16px;font-weight:600;margin-bottom:4px">${escHtml(mi.home_team||'?')} vs ${escHtml(mi.away_team||'?')}</div>
      <div style="font-size:12px;color:var(--muted);margin-bottom:12px">${mi.league||''} &middot; ${mi.date ? new Date(mi.date).toLocaleDateString() : ''} &middot; Match ID: ${mi.match_id}</div>

      <div class="prob-bar">
        <div class="prob-h" style="width:${hPct}%">H ${hPct}%</div>
        <div class="prob-d" style="width:${dPct}%">D ${dPct}%</div>
        <div class="prob-a" style="width:${aPct}%">A ${aPct}%</div>
      </div>

      <div style="margin:8px 0;font-size:13px">
        <strong>Recommended:</strong> ${p.recommended_bet||'N/A'}
        <span class="badge ${p.recommendation_tone==='confident'?'badge-green':p.recommendation_tone==='lean'?'badge-yellow':'badge-red'}">${p.recommendation_tone||''}</span>
        &middot; <strong>Confidence:</strong> ${(p.confidence*100).toFixed(1)}%
        &middot; <span class="badge ${convBadge}">${fd.conviction_tier||''}</span>
        ${fd.models_in_agreement ? '<span class="badge badge-green">MODELS AGREE</span>' : ''}
      </div>

      <table class="model-table">
        <thead><tr><th>Model</th><th>Home</th><th>Draw</th><th>Away</th><th>Pick</th><th>Conf</th><th>Agreement</th></tr></thead>
        <tbody>${modelsHtml}</tbody>
      </table>

      <div style="margin-top:10px;font-size:12px;color:var(--muted)">
        <strong>Decision:</strong> ${fd.selected_model} &middot; ${fd.strategy} &middot; ${fd.reason}
      </div>

      <div class="info-grid">
        <div class="info-item"><div class="label">Model Type</div><div class="value">${info.type||'?'}</div></div>
        <div class="info-item"><div class="label">Version</div><div class="value">${info.version||'?'}</div></div>
        <div class="info-item"><div class="label">Features</div><div class="value">${info.features_used||'?'} / ${info.total_features||'?'}</div></div>
        <div class="info-item"><div class="label">Bookmakers</div><div class="value">${info.bookmaker_count||0}</div></div>
        <div class="info-item"><div class="label">Confidence Method</div><div class="value">${info.confidence_method||'?'}</div></div>
        <div class="info-item"><div class="label">Data Quality</div><div class="value">${info.data_quality||'?'}</div></div>
      </div>
    `;
    document.getElementById('pred-results').innerHTML = html;
  } catch(e) {
    document.getElementById('pred-results').innerHTML = `<span style="color:var(--red)">Fetch error: ${e.message}</span>`;
  }
}

// ── PERFORMANCE ──
async function fetchPerformance() {
  const window_ = document.getElementById('perf-window').value;
  document.getElementById('perf-results').innerHTML = '<span class="loading">Loading models...</span>';
  const t0 = performance.now();
  try {
    const res = await fetch(`${BASE}/performance/models?window=${window_}`, { headers: headers() });
    const ms = Math.round(performance.now() - t0);
    const data = await res.json();
    document.getElementById('perf-status-bar').innerHTML = `<span class="time">${ms}ms</span> &middot; HTTP ${res.status}`;
    document.getElementById('perf-raw').textContent = JSON.stringify(data, null, 2);

    if (!res.ok) { document.getElementById('perf-results').innerHTML = `<span style="color:var(--red)">Error: ${JSON.stringify(data.detail)}</span>`; return; }

    const models = data.models || [];
    let html = '<table class="model-table"><thead><tr><th>Model</th><th>Predictions</th><th>Settled</th><th>Hit Rate</th><th>Brier</th><th>LogLoss</th><th>ROI</th></tr></thead><tbody>';
    for (const m of models) {
      const hr = m.hit_rate != null ? `${(m.hit_rate*100).toFixed(1)}%` : '-';
      const hrClass = m.hit_rate > 0.45 ? 'color:var(--green)' : m.hit_rate > 0.35 ? '' : 'color:var(--red)';
      html += `<tr>
        <td><strong>${m.model_version||m.model||'?'}</strong></td>
        <td>${m.total_predictions||m.predictions||0}</td>
        <td>${m.settled||0}</td>
        <td style="${hrClass}">${hr}</td>
        <td>${m.brier_score?.toFixed(3)||'-'}</td>
        <td>${m.log_loss?.toFixed(3)||'-'}</td>
        <td>${m.roi != null ? (m.roi*100).toFixed(1)+'%' : '-'}</td>
      </tr>`;
    }
    html += '</tbody></table>';
    document.getElementById('perf-results').innerHTML = html || '<span class="loading">No model data</span>';
  } catch(e) {
    document.getElementById('perf-results').innerHTML = `<span style="color:var(--red)">Error: ${e.message}</span>`;
  }
}

async function fetchAB() {
  const window_ = document.getElementById('perf-window').value;
  document.getElementById('perf-results').innerHTML = '<span class="loading">Loading A/B results...</span>';
  const t0 = performance.now();
  try {
    const res = await fetch(`${BASE}/performance/ab?window=${window_}`, { headers: headers() });
    const ms = Math.round(performance.now() - t0);
    const data = await res.json();
    document.getElementById('perf-status-bar').innerHTML = `<span class="time">${ms}ms</span> &middot; HTTP ${res.status}`;
    document.getElementById('perf-raw').textContent = JSON.stringify(data, null, 2);

    if (!res.ok) { document.getElementById('perf-results').innerHTML = `<span style="color:var(--red)">Error: ${JSON.stringify(data.detail)}</span>`; return; }

    let html = `<div style="margin-bottom:10px"><strong>A/B Test Results</strong> (${window_})</div>`;
    html += '<pre style="background:var(--bg);padding:12px;border-radius:4px;font-size:12px;max-height:500px;overflow:auto">' + escHtml(JSON.stringify(data, null, 2)) + '</pre>';
    document.getElementById('perf-results').innerHTML = html;
  } catch(e) {
    document.getElementById('perf-results').innerHTML = `<span style="color:var(--red)">Error: ${e.message}</span>`;
  }
}

// ── HEALTH ──
async function fetchHealth() {
  document.getElementById('health-results').innerHTML = '<span class="loading">Checking health...</span>';
  const t0 = performance.now();
  try {
    const endpoints = [
      { name: 'Server', url: '/health' },
      { name: 'Predict Service', url: '/predict/health' },
      { name: 'V3 Model', url: '/predict-v3/status' },
    ];
    let html = '';
    for (const ep of endpoints) {
      try {
        const res = await fetch(BASE + ep.url, { headers: headers() });
        const data = await res.json();
        const ok = res.ok;
        const dot = ok ? 'green' : 'red';
        const status = data.status || (ok ? 'healthy' : 'error');
        const details = [];
        if (data.model_loaded != null) details.push(`Model: ${data.model_loaded ? 'loaded' : 'not loaded'}`);
        if (data.n_models) details.push(`Folds: ${data.n_models}`);
        if (data.n_features) details.push(`Features: ${data.n_features}`);
        if (data.version) details.push(`v${data.version}`);
        if (data.uptime) details.push(`Uptime: ${data.uptime}`);
        html += `<div class="health-card">
          <div class="health-dot ${dot}"></div>
          <div>
            <div style="font-weight:600">${ep.name}</div>
            <div style="font-size:12px;color:var(--muted)">${status} ${details.length ? '&middot; ' + details.join(' &middot; ') : ''}</div>
          </div>
        </div>`;
      } catch(e) {
        html += `<div class="health-card"><div class="health-dot red"></div><div><div style="font-weight:600">${ep.name}</div><div style="font-size:12px;color:var(--red)">Failed: ${e.message}</div></div></div>`;
      }
    }
    const ms = Math.round(performance.now() - t0);
    document.getElementById('health-status-bar').innerHTML = `<span class="time">${ms}ms</span>`;
    document.getElementById('health-results').innerHTML = html;
  } catch(e) {
    document.getElementById('health-results').innerHTML = `<span style="color:var(--red)">Error: ${e.message}</span>`;
  }
}
</script>
</body>
</html>"""
