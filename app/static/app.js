const $ = id => document.getElementById(id);
let report = null;
let currentRole = 'admin';
let serviceEnabled = false;
let ocrRenderGeneration = 0;
let keyRenderGeneration = 0;
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
  $('citation').textContent = source ? `${doc.name} · page ${source.page} · line ${source.line}: ${source.text}${source.method === 'ocr' ? ' · OCR candidate; verify against the original' : ''}` : 'Original PDF · choose an evidence line below.';
  $('lines').replaceChildren();
  for (const line of doc.lines) {
    const row = el('div', line.text, 'line' + (line.id === source?.id ? ' active' : ''));
    row.append(el('small', `${line.id} · page ${line.page}${line.method === 'ocr' ? ` · recognizer score ${(line.confidence * 100).toFixed(1)}% (uncalibrated)${line.usable ? ' · unverified candidate' : ' · excluded from checks'}` : ''}`));
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
      body: JSON.stringify({action, note, expected_revision: finding.human_review?.revision || 0, expected_case_version: report.report_version})
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
function draftControls(finding) {
  const supported = ['incorrect_statement_total', 'incorrect_closing_balance', 'incorrect_carried_balance',
    'cross_document_principal_mismatch', 'cross_document_interest_mismatch',
    'cross_document_opening_balance_mismatch', 'cross_document_closing_balance_mismatch'];
  if (!supported.includes(finding.type) || finding.severity !== 'confirmed') return null;
  const wrapper = el('section', undefined, 'draft-controls');
  wrapper.append(el('p', 'Lender enquiry draft · approve this finding first. Review the draft and add any private account details yourself before sharing. Nothing is sent.'));
  const kindLabel = el('label', 'Draft purpose');
  const kind = el('select'); kind.id = 'draft-kind-' + finding.id; kindLabel.htmlFor = kind.id;
  for (const [value, text] of [['lender_enquiry', 'Ask lender for an explanation'], ['statement_dispute', 'Dispute this statement figure']]) {
    const option = el('option', text); option.value = value; kind.append(option);
  }
  kindLabel.append(kind);
  const button = el('button', 'Prepare lender draft', 'secondary'); button.type = 'button';
  button.setAttribute('aria-label', `Prepare lender draft ${finding.id}`);
  button.disabled = finding.human_review?.decision !== 'confirmed';
  const feedback = el('p', '', 'note'); feedback.setAttribute('role', 'status');
  const output = el('div');
  button.onclick = async () => {
    const current = report; const revision = finding.human_review?.revision || 0; const purpose = kind.value;
    button.disabled = true; kind.disabled = true; feedback.textContent = 'Checking approved finding and source evidence…';
    try {
      const draft = await jsonRequest(`/api/cases/${current.id}/findings/${finding.id}/draft?version=${current.report_version || 0}&revision=${revision}&kind=${purpose}`);
      if (report !== current || kind.value !== purpose) return;
      output.replaceChildren();
      const label = el('label', `Lender draft for ${finding.id}`);
      const text = el('textarea'); text.id = 'draft-' + finding.id; text.rows = 14; text.readOnly = true; text.value = draft.text;
      label.htmlFor = text.id; label.append(text);
      const select = el('button', 'Select draft text', 'secondary'); select.type = 'button';
      select.onclick = () => { text.focus(); text.select(); feedback.textContent = 'Text selected. Copy it, review it, and choose where to send it yourself.'; };
      output.append(label, select, el('p', `Report version ${draft.report_version} · review revision ${draft.review_revision} · draft SHA-256 ${draft.draft_sha256}`, 'note'));
      feedback.textContent = 'Draft ready for your final review. Supported personal-data patterns are redacted; inspect any remaining details. Nothing was sent.';
    } catch (error) { feedback.textContent = error.message; }
    finally { if (report === current) { button.disabled = false; kind.disabled = false; } }
  };
  kind.onchange = () => { output.replaceChildren(); feedback.textContent = 'Prepare a new draft for the selected purpose.'; };
  wrapper.append(kindLabel, button, feedback, output); return wrapper;
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
    const draft = draftControls(finding); if (draft) card.append(draft);
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
  $('calculations-title').textContent = report.calculations.some(item => item.provisional) ? 'Calculator checks · OCR candidates require review' : 'Verified calculations';
  for (const calculation of report.calculations) {
    const card = el('div', undefined, 'panel');
    if (calculation.provisional) card.append(el('strong', 'Provisional OCR arithmetic: verify recognized values against the PDF.'));
    card.append(el('p', `${calculation.operands.join(' + ')} = ${calculation.computed}`), el('p', `Statement says ${calculation.stated}`), sources(calculation.sources));
    $('calculations').append(card);
  }
  if (!report.calculations.length) $('calculations').append(el('p', 'No complete statement total available to verify.'));
  $('agent').replaceChildren();
  if (report.agent) {
    $('agent').append(el('p', report.agent.summary));
    const list = el('ul'); for (const item of report.agent.checklist) list.append(el('li', item));
    $('agent').append(list, sources(report.agent.sources));
  } else $('agent').append(el('p', report.agent_error || report.agent_status || 'Local mode: model investigation was not run.'));
  $('trace').replaceChildren();
  $('trace').append(el('p', 'Ordered execution events. Model calls show metadata; tool calls show inputs and outputs with supported personal-data patterns redacted. Token usage and cost estimates, when available, are shown separately. Shared investigation events appear here.', 'note'), traceTimeline(report.trace || []));
  if (report.metrics) {
    const metrics = report.metrics; const tokens = metrics.reported_tokens;
    const usage = tokens ? `reported tokens: input ${tokens.prompt_tokens ?? 'unreported'}, output ${tokens.completion_tokens ?? 'unreported'} (${metrics.calls_with_reported_usage}/${metrics.attempted_model_calls} calls report usage)` : 'Token usage unreported';
    $('trace').prepend(el('p', `Analysis ${metrics.analysis_ms} ms · ${metrics.attempted_model_calls} model calls · ${usage} · Cost estimate ${metrics.estimated_cost_usd === null ? 'unmeasured' : '$' + metrics.estimated_cost_usd + ' (configured rates)'}`, 'note'));
    $('trace').prepend(el('p', report.documents.map(doc => `${doc.name}: ${doc.routing?.selected || 'legacy'} extraction`).join(' · '), 'note'));
  }
  if (report.harness) $('trace').prepend(el('p', `Harness: ${report.harness.max_model_turns} investigation turns · ${report.harness.max_tool_calls_total} total tool calls · ${report.harness.request_timeout_seconds}s per request`, 'note'));
  $('document').replaceChildren();
  for (const doc of report.documents) { const option = el('option', doc.name); option.value = doc.id; $('document').append(option); }
  showDoc(report.documents.some(doc => doc.id === selectedDoc) ? selectedDoc : report.documents[0].id);
  $('json').href = `/api/cases/${report.id}/export?format=json`;
  $('checklist').href = `/api/cases/${report.id}/export?format=md`;
  for (const [id, format, label] of [['csv', 'csv', 'Export redacted CSV'], ['accounting-csv', 'accounting_csv', 'Accounting transaction worksheet']]) {
    let link = $(id);
    if (!link) { link = el('a', label, 'button secondary'); link.id = id; $('checklist').after(link); }
    link.href = `/api/cases/${report.id}/export?format=${format}`;
  }
  renderOCR();
}

async function renderOCR() {
  const generation = ++ocrRenderGeneration;
  const panel = $('ocr-panel'); panel.replaceChildren();
  const current = report; if (!current) { panel.hidden = true; return; }
  const pages = current.documents.reduce((count, doc) => count + new Set((doc.issues || []).filter(issue => issue.type === 'ocr_required').map(issue => issue.page)).size, 0);
  const scanned = current.documents.filter(doc => doc.ocr?.performed);
  panel.hidden = !pages && !scanned.length;
  if (panel.hidden) return;
  panel.append(el('h2', 'OCR review workflow'));
  panel.append(el('p', 'OCR recognizes candidate text. Scores are uncalibrated; every OCR result needs human verification. Approval of a finding does not verify all recognized fields.', 'note'));
  if (current.derived_from?.kind === 'ocr') {
    panel.append(el('p', `Report version ${current.report_version}; derived from version ${current.derived_from.version}. Previous reviews remain in that immutable version. New findings start pending.`));
    const previous = el('a', `Export prior report · version ${current.derived_from.version}`);
    previous.href = `/api/cases/${current.id}/export?format=json&version=${current.derived_from.version}`; panel.append(previous);
  }
  for (const doc of scanned) {
    panel.append(el('h3', doc.name), el('p', `${doc.ocr.usable_lines}/${doc.ocr.total_lines} recognized lines meet the score threshold. Recognizer score threshold ${Math.round(doc.ocr.threshold * 100)}%; this is not a probability of financial correctness.`));
    const list = el('ul');
    for (const field of doc.ocr.field_candidates || []) {
      const item = el('li', `${field.field.replaceAll('.', ' · ')}: ${field.value} · score ${(field.confidence * 100).toFixed(1)}% · unverified`);
      item.append(sources([field.source])); list.append(item);
    }
    panel.append(list);
  }
  const message = el('p', '', 'note'); message.setAttribute('role', 'status'); panel.append(message);
  if (!serviceEnabled) { message.textContent = 'OCR jobs require an authenticated database workspace. Review this scan manually in local mode.'; return; }
  if (currentRole === 'demo') { message.textContent = 'The public synthetic demo requests manual review; it cannot queue OCR jobs.'; return; }
  try {
    const info = await jsonRequest(`/api/platform/cases/${current.id}/ocr`);
    if (report?.id !== current.id || generation !== ocrRenderGeneration) return;
    const job = info.latest_job;
    message.textContent = job ? `OCR job: ${job.state}${job.result?.error ? ' · ' + job.result.error : ''}` : `${pages} image-only page${pages === 1 ? '' : 's'} awaiting review.`;
    const refresh = el('button', 'Refresh OCR status', 'secondary'); refresh.type = 'button'; refresh.onclick = () => renderOCR(); panel.append(refresh);
    if (info.version !== current.report_version) {
      const open = el('button', 'Open latest report', 'secondary'); open.type = 'button';
      open.onclick = async () => {
        open.disabled = true;
        try { const latest = await jsonRequest(`/api/cases/${current.id}`); if (report?.id === current.id) { report = latest; render(); loadHistory(); } }
        catch (error) { message.textContent = error.message; }
        finally { open.disabled = false; }
      };
      panel.append(el('p', 'The case changed. Open the latest report before reviewing or requesting OCR.'), open);
      return;
    }
    if (!pages) return;
    if (pages > 5) { panel.append(el('p', 'This case exceeds the five image-only page OCR limit. Review it manually.')); return; }
    if (!info.worker_available) panel.append(el('p', 'OCR worker is offline. The original PDF remains available for manual review.'));
    if (!['admin', 'reviewer'].includes(currentRole)) { panel.append(el('p', 'A workspace reviewer must request OCR.')); return; }
    const request = el('button', 'Request OCR · new report version', 'secondary'); request.type = 'button';
    request.disabled = !info.worker_available || ['queued', 'running'].includes(job?.state);
    panel.append(el('p', 'OCR creates a new report version. Previous findings and review history remain in the prior version; newly calculated findings start pending.'));
    request.onclick = async () => {
      request.disabled = true; message.textContent = 'Queuing OCR…';
      try {
        await jsonRequest(`/api/platform/cases/${current.id}/ocr`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expected_version: current.report_version})});
        if (report?.id === current.id) renderOCR();
      } catch (error) { message.textContent = error.message; request.disabled = false; }
    };
    panel.append(request);
  } catch (error) { if (report?.id === current.id && generation === ocrRenderGeneration) message.textContent = 'OCR status unavailable: ' + error.message; }
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

function renderAPIKeys() {
  const generation = ++keyRenderGeneration;
  let panel = $('api-keys-panel');
  if (!panel) { panel = el('section', undefined, 'panel'); panel.id = 'api-keys-panel'; document.querySelector('main').append(panel); }
  panel.replaceChildren(); panel.hidden = !serviceEnabled || currentRole !== 'admin';
  if (panel.hidden) return;
  panel.append(el('h2', 'Integration API keys'), el('p', 'Keys are shown once. Choose only the access your tool needs. Keys expire and can be revoked here. They cannot review findings, delete cases, run OCR or call Meta.'));
  const form = el('form', undefined, 'history-controls'); form.id = 'api-key-form';
  const label = el('label', 'Key label'); const name = el('input'); name.id = 'api-key-label'; name.required = true; name.maxLength = 80; label.append(name);
  const scopeLabel = el('label', 'Allowed access'); const scope = el('select'); scope.id = 'api-key-scope';
  for (const [value, text] of [['cases:read', 'Read redacted reports'], ['cases:submit', 'Submit PDFs with local checks'], ['cases:read,cases:submit', 'Submit and read reports']]) {
    const option = el('option', text); option.value = value; scope.append(option);
  }
  scopeLabel.append(scope);
  const daysLabel = el('label', 'Expires in'); const days = el('select'); days.id = 'api-key-days';
  for (const n of [7, 30, 90]) { const option = el('option', `${n} days`); option.value = n; days.append(option); }
  days.value = '30'; daysLabel.append(days);
  const create = el('button', 'Create API key', 'secondary'); create.type = 'submit'; form.append(label, scopeLabel, daysLabel, create);
  const feedback = el('p', '', 'note'); feedback.setAttribute('role', 'status');
  const secret = el('div'); const list = el('div');
  const fresh = () => generation === keyRenderGeneration && currentRole === 'admin';
  async function load() {
    try {
      const result = await jsonRequest('/api/platform/api-keys'); if (!fresh()) return;
      list.replaceChildren();
      for (const key of result.keys) {
        const row = el('div', undefined, 'panel');
        row.append(el('p', `${key.label} · ${key.scopes.join(', ')} · expires ${new Date(key.expires_at * 1000).toISOString()} · ${key.revoked ? 'revoked' : 'not revoked'}`));
        if (!key.revoked) {
          const revoke = el('button', 'Revoke ' + key.label, 'secondary'); revoke.type = 'button';
          revoke.onclick = async () => {
            revoke.disabled = true;
            try { await jsonRequest('/api/platform/api-keys/' + key.id, {method: 'DELETE'}); if (fresh()) { secret.replaceChildren(); feedback.textContent = 'Key revoked. New requests using it will be rejected.'; await load(); } }
            catch (error) { if (fresh()) feedback.textContent = error.message; }
            finally { revoke.disabled = false; }
          }; row.append(revoke);
        }
        list.append(row);
      }
    } catch (error) { if (fresh()) feedback.textContent = error.message; }
  }
  form.onsubmit = async event => {
    event.preventDefault(); create.disabled = true; secret.replaceChildren();
    try {
      const result = await jsonRequest('/api/platform/api-keys', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({label: name.value, scopes: scope.value.split(','), days: Number(days.value)})});
      if (!fresh()) return;
      const label = el('label', 'New key · copy now; it cannot be retrieved again'); const input = el('input');
      input.id = 'api-key-secret'; input.type = 'password'; input.readOnly = true; input.autocomplete = 'off'; input.value = result.token; label.append(input);
      const select = el('button', 'Select new key', 'secondary'); select.type = 'button'; select.onclick = () => { input.focus(); input.select(); };
      const clear = el('button', 'Clear shown key', 'secondary'); clear.type = 'button'; clear.onclick = () => secret.replaceChildren();
      secret.append(label, select, clear); feedback.textContent = 'Store this key in your tool’s secret settings. It is cleared here on sign out or access changes.'; await load();
    } catch (error) { if (fresh()) feedback.textContent = error.message; }
    finally { create.disabled = false; }
  };
  panel.append(form, feedback, secret, list); load();
}
function updateAccess(actor) {
  currentRole = actor?.role || 'anonymous';
  const canWrite = ['admin', 'reviewer', 'demo'].includes(currentRole);
  $('analyze').disabled = !canWrite || currentRole === 'demo'; $('delete').disabled = !canWrite;
  $('upload-panel').hidden = currentRole === 'demo'; $('demo-cases').hidden = currentRole !== 'demo';
  $('login-form').hidden = !!actor; $('logout').hidden = !actor;
  $('identity-status').textContent = actor ? `${actor.workspace} · ${actor.role}` : 'Sign in to access workspace statements. Public synthetic demo is separate.';
  renderAPIKeys();
  if (report) render();
}
async function configureService() {
  try {
    const config = await jsonRequest('/api/platform/config');
    serviceEnabled = config.authentication_required;
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

$('run-benchmark').onclick = async () => {
  $('run-benchmark').disabled = true; $('benchmark-message').textContent = 'Checking the extended known-answer PDF corpus…'; $('benchmark-results').replaceChildren();
  try {
    const result = await jsonRequest('/api/benchmark'); const summary = result.summary;
    $('benchmark-message').textContent = `${summary.passed}/${summary.total} passed · field precision ${percent(summary.field_metrics.precision)} · recall ${percent(summary.field_metrics.recall)} · grounded references ${percent(summary.grounded_reference_accuracy)} · false clean ${summary.false_clean_count}/${summary.at_risk_count} · review rate ${percent(summary.review_rate)} · zero model calls`;
    const table = el('table'); const head = el('thead'); const header = el('tr');
    for (const label of ['Case', 'Result', 'Status', 'Precision', 'Recall', 'Grounded references', 'False clean']) header.append(el('th', label));
    head.append(header); table.append(head); const body = el('tbody');
    for (const item of result.cases) {
      const row = el('tr', undefined, item.passed ? 'eval-pass' : 'eval-fail');
      for (const value of [item.case, item.passed ? 'PASS' : 'FAIL', item.status, percent(item.field_summary?.precision ?? null), percent(item.field_summary?.recall ?? null), `${item.grounded_citations}/${item.citation_count}`, item.false_clean ? 'YES' : 'No']) row.append(el('td', value));
      body.append(row);
      if (item.errors.length) { const errors = el('tr'); const cell = el('td', item.errors.join('; ')); cell.colSpan = 7; errors.append(cell); body.append(errors); }
    }
    table.append(body); $('benchmark-results').append(table, el('p', result.definitions.scope, 'note'), el('p', result.definitions.fields, 'note'), el('p', result.definitions.citations, 'note'), el('p', result.definitions.review_rate, 'note'));
  } catch (error) { $('benchmark-message').textContent = 'Benchmark failed: ' + error.message; }
  finally { $('run-benchmark').disabled = false; }
};
