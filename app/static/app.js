const $ = id => document.getElementById(id);
let report = null;
let currentRole = 'admin';
function csrfToken() {
  return document.cookie.split('; ').find(part => part.startsWith('pta_csrf='))?.split('=').slice(1).join('=') || '';
}
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
async function jsonRequest(url, options) {
  const settings = {...options};
  if (settings.method && !['GET', 'HEAD'].includes(settings.method)) {
    settings.headers = {...settings.headers, 'X-CSRF-Token': csrfToken()};
  }
  const response = await fetch(url, settings);
  const body = await response.json();
  if (!response.ok) throw Error(typeof body.detail === 'string' ? body.detail : 'Request rejected. Check the supplied values.');
  return body;
}
async function health() {
  try {
    const h = await jsonRequest('/api/health');
    $('health').textContent = h.meta_configured ? 'Meta configured · ' + h.model : 'Local ready · Meta key needed';
  } catch { $('health').textContent = 'Server unavailable'; }
}
health();
$('upload').addEventListener('submit', async event => {
  event.preventDefault();
  $('message').textContent = 'Reading evidence and checking totals…';
  $('analyze').disabled = true;
  const form = new FormData();
  for (const file of $('files').files) form.append('files', file);
  form.append('mode', $('mode').value);
  try {
    report = await jsonRequest('/api/analyze', {method: 'POST', body: form});
    location.hash = 'case=' + report.id;
    render();
    loadHistory();
    $('message').textContent = 'Analysis complete. Review decisions do not change the original machine findings.';
  } catch (error) { $('message').textContent = error.message; }
  finally { $('analyze').disabled = false; }
});
function showDoc(id, source) {
  const doc = report.documents.find(d => d.id === id);
  if (!doc) return;
  $('document').value = id;
  $('original').href = `/api/cases/${report.id}/documents/${id}#page=${source?.page || 1}`;
  $('pdf').src = `/api/cases/${report.id}/documents/${id}/page/${source?.page || 1}?source=${encodeURIComponent(source?.id || '')}`;
  $('source-page').max = pageCount(doc); $('source-page').value = source?.page || 1;
  $('citation').textContent = source ? `${doc.name} · page ${source.page} · line ${source.line}: ${source.text}` : 'Original PDF · choose an evidence line below.';
  $('lines').replaceChildren();
  for (const line of doc.lines) {
    const row = el('div', line.text, 'line' + (line.id === source?.id ? ' active' : ''));
    row.append(el('small', `${line.id} · page ${line.page}`));
    $('lines').append(row);
  }
  renderComparison();
}
function pageCount(doc) { return Math.max(1, ...doc.lines.map(line => line.page), ...(doc.issues || []).map(issue => issue.page || 1)); }
function renderComparison() {
  if (!report) return;
  const enabled = $('compare-enabled').checked;
  $('comparison-secondary').hidden = !enabled;
  $('comparison-images').classList.toggle('side-by-side', enabled);
  const previous = $('compare-document').value;
  $('compare-document').replaceChildren();
  for (const doc of report.documents) { const option = el('option', doc.name); option.value = doc.id; $('compare-document').append(option); }
  const candidate = report.documents.find(doc => doc.id === previous) || report.documents.find(doc => doc.id !== $('document').value) || report.documents[0];
  $('compare-document').value = candidate.id;
  $('compare-page').max = pageCount(candidate);
  const page = Math.max(1, Math.min(pageCount(candidate), Number($('compare-page').value) || 1));
  $('compare-page').value = page;
  $('compare-pdf').src = `/api/cases/${report.id}/documents/${candidate.id}/page/${page}`;
}
function sources(ids) {
  const group = el('div', undefined, 'sources');
  for (const id of ids) {
    const doc = report.documents.find(d => d.lines.some(line => line.id === id));
    if (!doc) continue;
    const line = doc.lines.find(line => line.id === id);
    const button = el('button', `${doc.name} · p${line.page} line ${line.line}`, 'source');
    button.type = 'button';
    button.onclick = () => showDoc(doc.id, line);
    group.append(button);
  }
  return group;
}
function traceTimeline(events) {
  const list = el('ol', undefined, 'timeline');
  for (const event of events) {
    const item = el('li');
    const details = el('details');
    const latency = event.duration_ms === null ? 'not timed' : `${event.duration_ms} ms`;
    const summary = el('summary', `${event.id} · ${event.kind} / ${event.name} · ${event.validation} · ${latency}`);
    details.append(summary, el('small', `${event.timestamp}${event.document ? ' · ' + event.document : ''}`),
      el('pre', JSON.stringify({input: event.input, output: event.output}, null, 2)));
    item.append(details); list.append(item);
  }
  if (!events.length) list.append(el('li', 'No recorded events for this older case.'));
  return list;
}
async function saveReview(finding, action, note, controls, feedback) {
  const caseId = report.id;
  for (const button of controls.querySelectorAll('button')) button.disabled = true;
  feedback.textContent = 'Saving…';
  try {
    const updated = await jsonRequest(`/api/cases/${caseId}/findings/${finding.id}`, {
      method: 'PATCH', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action, note, expected_revision: finding.human_review?.revision || 0})
    });
    if (report?.id !== caseId) return;
    report = updated; render();
    loadHistory();
    $('message').textContent = 'Review saved. Original finding, severity and calculations are unchanged.';
  } catch (error) { feedback.textContent = error.message; }
  finally { for (const button of controls.querySelectorAll('button')) button.disabled = false; }
}
function reviewControls(finding) {
  const review = finding.human_review || {decision: 'pending', revision: 0, history: []};
  const wrapper = el('section', undefined, 'review-controls');
  wrapper.append(el('p', `Human decision: ${review.decision} · revision ${review.revision}`, 'review-state'));
  const label = el('label', `Review note for ${finding.id}`);
  const input = el('textarea'); input.maxLength = 2000; input.rows = 2;
  input.id = 'note-' + finding.id; label.htmlFor = input.id; label.append(input);
  const actions = el('div', undefined, 'actions');
  const feedback = el('p', '', 'note'); feedback.setAttribute('role', 'status');
  for (const [action, text] of [['confirm', 'Approve'], ['reject', 'Reject'], ['note', 'Save note']]) {
    const button = el('button', text, 'secondary'); button.type = 'button';
    button.setAttribute('aria-label', `${text} ${finding.id}`);
    button.disabled = !['admin', 'reviewer', 'demo'].includes(currentRole);
    button.onclick = () => saveReview(finding, action, input.value, wrapper, feedback);
    actions.append(button);
  }
  wrapper.append(label, actions, feedback);
  if (review.history.length) {
    const history = el('details'); history.append(el('summary', `Review history (${review.history.length})`));
    for (const entry of review.history) history.append(el('p', `${entry.timestamp} · ${entry.action}${entry.note ? ': ' + entry.note : ''}`));
    wrapper.append(history);
  }
  return wrapper;
}
function render() {
  const selectedDoc = $('document').value;
  $('results').hidden = false;
  $('case-id').textContent = report.id;
  $('status').textContent = {consistent: 'No discrepancies in supported checks', discrepancies: 'Discrepancies found', review: 'Manual review needed'}[report.status];
  $('metrics').replaceChildren();
  for (const [value, label] of [[report.documents.length, 'documents'], [report.findings.filter(f => f.severity === 'confirmed').length, 'machine discrepancies'], [report.findings.filter(f => f.severity === 'review').length, 'machine review items']]) {
    const metric = el('div', undefined, 'metric'); metric.append(el('strong', value), el('span', label)); $('metrics').append(metric);
  }
  $('findings').replaceChildren();
  if (!report.findings.length) $('findings').append(el('div', 'No discrepancies in the supported checks.', 'finding clear'));
  for (const finding of report.findings) {
    const card = el('article', undefined, 'finding ' + finding.severity);
    card.append(el('span', `${finding.id} · Machine: ${finding.severity}`, 'badge'), el('p', finding.message), sources(finding.sources), reviewControls(finding));
    const related = (report.trace || []).filter(event => (event.finding_ids || []).includes(finding.id) || (event.document && finding.sources.some(source => source.startsWith(event.document + ':'))));
    const details = el('details'); details.append(el('summary', 'Related checks and review events'), traceTimeline(related)); card.append(details);
    const shared = (report.trace || []).filter(event => event.kind === 'model' || event.kind === 'tool' || (event.kind === 'validation' && event.name === 'agent_citations'));
    if (shared.length) {
      const investigation = el('details');
      investigation.append(el('summary', 'Investigation trace (shared across findings)'), traceTimeline(shared));
      card.append(investigation);
    }
    $('findings').append(card);
  }
  $('calculations').replaceChildren();
  for (const calculation of report.calculations) {
    const card = el('div', undefined, 'panel');
    card.append(el('p', `${calculation.operands.join(' + ')} = ${calculation.computed}`), el('p', `Statement says ${calculation.stated}`), sources(calculation.sources));
    $('calculations').append(card);
  }
  if (!report.calculations.length) $('calculations').append(el('p', 'No complete statement total available to verify.'));
  $('agent').replaceChildren();
  if (report.agent) {
    $('agent').append(el('p', report.agent.summary));
    const list = el('ul'); for (const item of report.agent.checklist) list.append(el('li', item));
    $('agent').append(list, sources(report.agent.sources));
  } else $('agent').append(el('p', report.agent_error || 'Local mode: model investigation was not run.'));
  $('trace').replaceChildren();
  $('trace').append(el('p', 'Ordered execution events. Model calls show metadata; tool calls show inputs and outputs with supported personal-data patterns redacted. Cost is not measured. Shared investigation events appear here.', 'note'), traceTimeline(report.trace || []));
  if (report.harness) $('trace').prepend(el('p', `Harness: ${report.harness.max_model_turns} investigation turns · ${report.harness.max_tool_calls_total} total tool calls · ${report.harness.request_timeout_seconds}s per request`, 'note'));
  $('document').replaceChildren();
  for (const doc of report.documents) { const option = el('option', doc.name); option.value = doc.id; $('document').append(option); }
  showDoc(report.documents.some(doc => doc.id === selectedDoc) ? selectedDoc : report.documents[0].id);
  $('json').href = `/api/cases/${report.id}/export?format=json`;
  $('checklist').href = `/api/cases/${report.id}/export?format=md`;
}
$('document').onchange = () => showDoc($('document').value);
$('compare-enabled').onchange = renderComparison;
$('compare-document').onchange = renderComparison;
$('compare-page').onchange = renderComparison;
$('source-page').onchange = () => {
  if (!report) return;
  const doc = report.documents.find(item => item.id === $('document').value);
  const page = Math.max(1, Math.min(pageCount(doc), Number($('source-page').value) || 1));
  $('source-page').value = page;
  $('pdf').src = `/api/cases/${report.id}/documents/${doc.id}/page/${page}`;
  $('original').href = `/api/cases/${report.id}/documents/${doc.id}#page=${page}`;
  $('citation').textContent = `${doc.name} · page ${page} · original page view`;
};
$('delete').onclick = async () => {
  if (!report) return;
  try {
    await jsonRequest(`/api/cases/${report.id}`, {method: 'DELETE'});
    report = null; location.hash = ''; $('results').hidden = true; $('pdf').removeAttribute('src'); $('message').textContent = 'Case deleted.';
    loadHistory();
  } catch (error) { $('message').textContent = error.message; }
};
const percent = value => value === null ? 'N/A' : (value * 100).toFixed(0) + '%';
$('run-evals').onclick = async () => {
  $('run-evals').disabled = true; $('eval-message').textContent = 'Running six offline cases…'; $('eval-results').replaceChildren();
  try {
    const result = await jsonRequest('/api/evals'); const s = result.summary;
    $('eval-message').textContent = `${s.passed}/${s.total} passed · citations ${percent(s.citation_accuracy)} (${s.citation_count} references) · false clean ${s.false_clean_count}/${s.at_risk_count} (${percent(s.false_clean_rate)}) · ${result.model_calls} model calls`;
    const table = el('table'); const head = el('thead'); const row = el('tr');
    for (const label of ['Case', 'Result', 'Confirmed / expected', 'Citations', 'False clean', 'Differences']) row.append(el('th', label));
    head.append(row); table.append(head); const body = el('tbody');
    for (const item of result.cases) {
      const tr = el('tr', undefined, item.passed ? 'eval-pass' : 'eval-fail');
      for (const value of [item.case, item.passed ? 'PASS' : 'FAIL', `${item.confirmed_count ?? 'N/A'} / ${item.expected_confirmed_count ?? 'N/A'}`, percent(item.citation_accuracy), item.false_clean ? 'YES' : 'No', item.differences.map(v => '$' + v).join(', ') || '—']) tr.append(el('td', value));
      body.append(tr);
      if (item.errors.length) { const errors = el('tr'); const td = el('td', item.errors.join('; ')); td.colSpan = 6; errors.append(td); body.append(errors); }
    }
    table.append(body); $('eval-results').append(table, el('p', result.definitions.scope, 'note'), el('p', result.definitions.citation_accuracy, 'note'), el('p', result.definitions.false_clean_rate, 'note'), el('p', 'Evaluated at ' + result.evaluated_at, 'note'));
  } catch (error) { $('eval-message').textContent = 'Evaluation failed: ' + error.message; }
  finally { $('run-evals').disabled = false; }
};
async function restoreCase() {
  const match = location.hash.match(/^#case=([a-f0-9]{32})$/);
  if (!match) return;
  try { report = await jsonRequest('/api/cases/' + match[1]); render(); $('message').textContent = 'Saved case reopened.'; }
  catch (error) { $('message').textContent = 'Cannot reopen case: ' + error.message; }
}
restoreCase();

async function loadHistory() {
  $('history-message').textContent = 'Loading saved cases…';
  try {
    const query = {q: $('history-query').value};
    if ($('history-status').value) query.status = $('history-status').value;
    if ($('history-decision').value) query.decision = $('history-decision').value;
    const data = await jsonRequest('/api/cases/search', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(query)});
    $('history-results').replaceChildren();
    const table = el('table'); const header = el('tr');
    for (const label of ['Case', 'Loan / account', 'Period', 'Machine status', 'Human decision']) header.append(el('th', label));
    const head = el('thead'); head.append(header); table.append(head);
    const body = el('tbody');
    for (const item of data.cases) {
      const row = el('tr'); const cell = el('td'); const open = el('button', 'Open ' + item.id.slice(0, 8), 'secondary'); open.type = 'button';
      open.onclick = async () => {
        try { report = await jsonRequest('/api/cases/' + item.id); location.hash = 'case=' + item.id; render(); $('message').textContent = 'Saved case reopened.'; }
        catch (error) { $('history-message').textContent = error.message; }
      };
      cell.append(open); row.append(cell);
      for (const value of [item.identifiers.join(', ') || 'Unknown', item.periods.join(', ') || 'Unknown', item.status, item.review_decisions.join(', ') || 'No findings']) row.append(el('td', value));
      body.append(row);
    }
    table.append(body); $('history-results').append(table);
    $('history-message').textContent = `${data.total_in_window} matching cases; showing ${data.cases.length}.${data.truncated ? ' Search window limit reached.' : ''}`;
  } catch (error) { $('history-results').replaceChildren(); $('history-message').textContent = error.message; }
}
$('history-form').onsubmit = event => { event.preventDefault(); loadHistory(); };

function updateAccess(actor) {
  currentRole = actor?.role || 'anonymous';
  const canWrite = ['admin', 'reviewer', 'demo'].includes(currentRole);
  $('analyze').disabled = !canWrite || currentRole === 'demo'; $('delete').disabled = !canWrite;
  $('upload-panel').hidden = currentRole === 'demo'; $('demo-cases').hidden = currentRole !== 'demo';
  $('login-form').hidden = !!actor; $('logout').hidden = !actor;
  $('identity-status').textContent = actor ? `${actor.workspace} · ${actor.role}` : 'Sign in to access workspace statements. Public synthetic demo is separate.';
  if (report) render();
}
async function configureService() {
  try {
    const config = await jsonRequest('/api/platform/config');
    $('service-auth').hidden = !config.authentication_required;
    $('public-demo').hidden = !config.public_demo;
    if (config.authentication_required) {
      try { updateAccess(await jsonRequest('/api/platform/auth/me')); }
      catch { report = null; $('results').hidden = true; updateAccess(null); }
    }
    loadHistory();
  } catch (error) { $('history-message').textContent = 'Service setup unavailable: ' + error.message; }
}
$('login-form').onsubmit = async event => {
  event.preventDefault();
  try {
    const actor = await jsonRequest('/api/platform/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email: $('login-email').value, password: $('login-password').value})});
    $('login-password').value = ''; updateAccess(actor); loadHistory(); restoreCase();
  } catch (error) { $('identity-status').textContent = error.message; }
};
$('logout').onclick = async () => {
  try {
    await jsonRequest('/api/platform/auth/logout', {method: 'POST'});
    report = null; $('results').hidden = true; $('history-results').replaceChildren();
    $('pdf').removeAttribute('src'); $('compare-pdf').removeAttribute('src'); updateAccess(null); location.hash = '';
  } catch (error) { $('identity-status').textContent = error.message; }
};
configureService();

$('start-demo').onclick = async () => {
  $('start-demo').disabled = true;
  try {
    const actor = await jsonRequest('/api/platform/demo/start', {method: 'POST'});
    report = null; location.hash = ''; $('results').hidden = true; updateAccess(actor); loadHistory();
    $('demo-message').textContent = 'Your isolated synthetic session is ready. Choose a case; reviews persist for this session.';
  } catch (error) { $('demo-message').textContent = error.message; }
  finally { $('start-demo').disabled = false; }
};
for (const button of document.querySelectorAll('[data-fixture]')) button.onclick = async () => {
  button.disabled = true; $('demo-message').textContent = 'Running calculator checks on fictional statements…';
  try {
    report = await jsonRequest('/api/platform/demo/cases/' + button.dataset.fixture, {method: 'POST'});
    location.hash = 'case=' + report.id; render(); loadHistory();
    $('demo-message').textContent = 'Synthetic case checked. Sources, trace, exports and human review are connected to the backend. No model call was made.';
    $('results').scrollIntoView({behavior: 'smooth', block: 'start'});
  } catch (error) { $('demo-message').textContent = error.message; }
  finally { button.disabled = false; }
};
