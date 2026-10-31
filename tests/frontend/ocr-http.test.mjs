// Executes the real frontend handlers against a disposable loopback FastAPI
// service. jsdom supplies DOM behavior, not browser layout or visual evidence.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM, CookieJar, VirtualConsole} from 'jsdom';

const base = process.env.PAPER_TRAIL_UI_BASE;
assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/, 'Use only the owned loopback test server');
const offline = process.env.PAPER_TRAIL_UI_OFFLINE === '1';
const origin = 'https://frontend.test.invalid';
// Resolve explicitly relative to this file; no web-supplied script is executed.
const actualHtml = await readFile(new URL('../../app/static/index.html', import.meta.url), 'utf8');

async function waitFor(predicate, message, timeout = 20000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 40));
  }
  throw Error(message);
}

async function frontend(t) {
  const errors = []; const requests = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error.message));
  const jar = new CookieJar();
  const dom = new JSDOM(actualHtml, {url: origin + '/', runScripts: 'outside-only', cookieJar: jar, virtualConsole});
  const w = dom.window; const doc = w.document;
  t.after(() => { dom.window.close(); assert.deepEqual(errors, []); });
  w.Element.prototype.scrollIntoView = function () {};
  w.FormData = globalThis.FormData;
  w.fetch = async (url, options = {}) => {
    const target = new URL(url, origin);
    assert.equal(target.origin, origin, 'Frontend requests must stay in this test origin');
    const headers = new Headers(options.headers);
    const cookies = jar.getCookieStringSync(origin + '/');
    if (cookies) headers.set('Cookie', cookies);
    const response = await fetch(base + target.pathname + target.search, {...options, headers});
    for (const cookie of response.headers.getSetCookie()) jar.setCookieSync(cookie, origin + '/');
    const entry = {method: options.method || 'GET', path: target.pathname, status: response.status};
    if (entry.method === 'PATCH') entry.expectedCaseVersion = JSON.parse(options.body).expected_case_version;
    requests.push(entry);
    return response;
  };
  const code = await readFile(new URL('../../app/static/app.js', import.meta.url), 'utf8');
  w.eval(code);
  await waitFor(() => !doc.getElementById('service-auth').hidden, 'Service setup did not complete');
  doc.getElementById('login-email').value = 'reviewer@example.invalid';
  doc.getElementById('login-password').value = 'synthetic-frontend-password-123';
  doc.getElementById('login-form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await waitFor(() => doc.getElementById('identity-status').textContent.includes('· reviewer'), 'Synthetic reviewer sign-in failed');
  const scan = await readFile(new URL('../../data/ocr/labeled_error.pdf', import.meta.url));
  Object.defineProperty(doc.getElementById('files'), 'files', {configurable: true, value: [new File([scan], 'fictional-scan.pdf', {type: 'application/pdf'})]});
  doc.getElementById('upload').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await waitFor(() => !doc.getElementById('results').hidden && !doc.getElementById('ocr-panel').hidden, 'Uploaded scan did not render');
  const button = text => [...doc.querySelectorAll('button')].find(node => node.textContent === text);
  const panelText = () => doc.getElementById('ocr-panel').textContent;
  const api = async (path, options) => w.fetch(path, options);
  return {w, doc, requests, button, panelText, api};
}

test('real frontend queues OCR and reopens reviewed candidates through HTTP', {skip: offline, timeout: 120000}, async t => {
  const ui = await frontend(t);
  await waitFor(() => ui.button('Request OCR · new report version') && !ui.button('Request OCR · new report version').disabled, 'A live OCR worker was not available');
  ui.button('Request OCR · new report version').click();
  await waitFor(() => ui.requests.some(r => r.method === 'POST' && r.path.endsWith('/ocr') && r.status === 202), 'OCR was not queued');
  const until = Date.now() + 90000;
  while (!ui.button('Open latest report') && Date.now() < until) {
    const refresh = ui.button('Refresh OCR status');
    if (refresh) refresh.click();
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  assert.ok(ui.button('Open latest report'), 'Completed OCR report was not discoverable');
  ui.button('Open latest report').click();
  await waitFor(() => ui.panelText().includes('derived from version 1'), 'Derived OCR version did not open');
  assert.match(ui.panelText(), /unverified/);
  assert.match(ui.panelText(), /97\.3%/);
  assert.match(ui.doc.getElementById('calculations-title').textContent, /OCR candidates require review/);
  assert.match(ui.doc.getElementById('calculations').textContent, /1000\.00 \+ 100\.00 = 1100\.00/);
  assert.match(ui.doc.getElementById('findings').textContent, /50\.00/);
  assert.equal(ui.doc.getElementById('status').textContent, 'Manual review needed');
  const source = ui.doc.querySelector('#ocr-panel button.source');
  assert.ok(source); source.click();
  assert.match(ui.doc.getElementById('citation').textContent, /OCR candidate/);
  assert.match(ui.doc.getElementById('lines').textContent, /uncalibrated/);
  const imageUrl = new URL(ui.doc.getElementById('pdf').src);
  const image = await ui.api(imageUrl.pathname + imageUrl.search);
  assert.equal(image.status, 200); assert.equal(Buffer.from(await image.arrayBuffer()).subarray(0, 4).toString('hex'), '89504e47');
  const caseId = ui.doc.getElementById('case-id').textContent;
  ui.doc.getElementById('note-F1').value = 'Synthetic frontend verification';
  ui.doc.querySelector('[aria-label="Save note F1"]').click();
  await waitFor(() => ui.doc.getElementById('findings').textContent.includes('revision 1'), 'Frontend review did not save');
  assert.equal(ui.requests.find(r => r.method === 'PATCH').expectedCaseVersion, 2);
  const current = await (await ui.api('/api/cases/' + caseId)).json();
  assert.equal(current.report_version, 3);
  assert.equal(current.findings[0].human_review.history[0].note, 'Synthetic frontend verification');
  assert.equal(current.status, 'review');
  const prior = await (await ui.api('/api/cases/' + caseId + '/export?format=json&version=1')).json();
  assert.equal(prior.report_version, 1); assert.equal(prior.documents[0].lines.length, 0);
  const markdown = await (await ui.api('/api/cases/' + caseId + '/export?format=md')).text();
  assert.match(markdown, /Provisional OCR arithmetic/); assert.match(markdown, /uncalibrated/);
  assert.equal((await (await ui.api('/api/cases/' + caseId + '/audit')).json()).verified, true);
  ui.doc.getElementById('logout').click();
  await waitFor(() => ui.doc.getElementById('results').hidden, 'Logout did not hide the report');
  assert.equal((await ui.api('/api/cases/' + caseId)).status, 401);
});

test('offline worker is visible and cannot queue a dead OCR job', {skip: !offline, timeout: 30000}, async t => {
  const ui = await frontend(t);
  await waitFor(() => ui.panelText().includes('worker is offline'), 'Offline OCR state did not render');
  const request = ui.button('Request OCR · new report version');
  assert.ok(request?.disabled);
  assert.equal(ui.requests.filter(r => r.method === 'POST' && r.path.endsWith('/ocr')).length, 0);
});

test('approved lender draft uses real backend evidence and is removed after rejection', {skip: offline, timeout: 45000}, async t => {
  const ui = await frontend(t);
  const files = await Promise.all(['statement_A.pdf', 'statement_B.pdf'].map(async name => {
    const bytes = await readFile(new URL('../../data/synthetic/math_error/' + name, import.meta.url));
    return new File([bytes], name, {type: 'application/pdf'});
  }));
  Object.defineProperty(ui.doc.getElementById('files'), 'files', {configurable: true, value: files});
  const oldCase = ui.doc.getElementById('case-id').textContent;
  ui.doc.getElementById('upload').dispatchEvent(new ui.w.Event('submit', {bubbles: true, cancelable: true}));
  await waitFor(() => ui.doc.getElementById('case-id').textContent !== oldCase, 'Native math case did not open');
  const prepare = () => ui.doc.querySelector('[aria-label="Prepare lender draft F1"]');
  assert.ok(prepare()?.disabled, 'Draft requires human approval');
  ui.doc.querySelector('[aria-label="Approve F1"]').click();
  await waitFor(() => prepare() && !prepare().disabled, 'Approval did not enable the draft');
  prepare().click();
  await waitFor(() => ui.doc.getElementById('draft-F1'), 'Backend draft did not render');
  const text = ui.doc.getElementById('draft-F1');
  assert.ok(text.readOnly); assert.match(text.value, /50\.00 USD/);
  assert.match(text.value, /3300\.00 USD; statement says 3350\.00 USD/);
  assert.match(text.value, /doc2:p1:/); assert.doesNotMatch(text.value, /DEMO-001/);
  ui.button('Select draft text').click();
  assert.equal(text.selectionEnd - text.selectionStart, text.value.length);
  assert.ok(ui.requests.some(r => r.path.endsWith('/draft') && r.status === 200));
  const purpose = ui.doc.getElementById('draft-kind-F1'); purpose.value = 'statement_dispute';
  purpose.dispatchEvent(new ui.w.Event('change'));
  assert.equal(ui.doc.getElementById('draft-F1'), null);
  prepare().click();
  await waitFor(() => ui.doc.getElementById('draft-F1'), 'Dispute draft did not render');
  assert.match(ui.doc.getElementById('draft-F1').value, /I dispute the statement figure/);
  assert.equal(ui.requests.filter(r => /send|payment/.test(r.path)).length, 0);
  ui.doc.querySelector('[aria-label="Reject F1"]').click();
  await waitFor(() => prepare()?.disabled && !ui.doc.getElementById('draft-F1'), 'Rejected finding retained an actionable draft');
});

test('admin issues and revokes an API key with real PDF submission and CSV exports', {skip: offline, timeout: 45000}, async t => {
  const ui = await frontend(t);
  assert.ok(ui.doc.getElementById('api-keys-panel').hidden, 'Reviewer must not administer keys');
  ui.doc.getElementById('logout').click();
  await waitFor(() => !ui.doc.getElementById('login-form').hidden, 'Reviewer sign out failed');
  ui.doc.getElementById('login-email').value = 'admin@example.invalid';
  ui.doc.getElementById('login-password').value = 'synthetic-frontend-password-123';
  ui.doc.getElementById('login-form').dispatchEvent(new ui.w.Event('submit', {cancelable: true}));
  await waitFor(() => !ui.doc.getElementById('api-keys-panel').hidden, 'Admin key controls missing');
  ui.doc.getElementById('api-key-label').value = 'Fictional CSV connector';
  ui.doc.getElementById('api-key-scope').value = 'cases:read,cases:submit';
  ui.doc.getElementById('api-key-form').dispatchEvent(new ui.w.Event('submit', {cancelable: true}));
  await waitFor(() => ui.doc.getElementById('api-key-secret'), 'One-time key missing');
  const secret = ui.doc.getElementById('api-key-secret'); assert.equal(secret.type, 'password');
  const token = secret.value; const auth = {Authorization: 'Bearer ' + token};
  const form = new FormData();
  for (const name of ['statement_A.pdf','statement_B.pdf']) {
    const bytes = await readFile(new URL('../../data/synthetic/math_error/' + name, import.meta.url));
    form.append('files', new File([bytes], name, {type: 'application/pdf'}));
  }
  const result = await ui.api('/api/integrations/v1/cases', {method: 'POST',headers: auth,body: form});
  assert.equal(result.status, 201); const receipt = await result.json();
  const path = '/api/integrations/v1/cases/' + receipt.id;
  const report = await (await ui.api(path, {headers: auth})).json();
  assert.equal(report.findings[0].difference, '50.00');
  assert.equal(report.documents[0].statement.loan_id, '[REDACTED]');
  assert.equal((await ui.api(path)).status, 401);
  const exported = await ui.api(path + '/export?format=csv', {headers: auth});
  assert.equal(exported.status, 200); assert.match(await exported.text(), /3300\.00,3350\.00,50\.00/);
  ui.button('Select new key').click(); assert.equal(secret.selectionEnd-secret.selectionStart, token.length);
  await waitFor(() => ui.button('Revoke Fictional CSV connector'), 'Issued key list missing');
  ui.button('Revoke Fictional CSV connector').click();
  await waitFor(() => !ui.doc.getElementById('api-key-secret') && !ui.button('Revoke Fictional CSV connector'), 'Revocation did not update the UI');
  assert.equal((await ui.api(path, {headers: auth})).status, 401);
  ui.doc.getElementById('api-key-label').value = 'Logout cleanup';
  ui.doc.getElementById('api-key-form').dispatchEvent(new ui.w.Event('submit', {cancelable: true}));
  await waitFor(() => ui.doc.getElementById('api-key-secret'), 'Second one-time key missing');
  ui.doc.getElementById('logout').click();
  await waitFor(() => ui.doc.getElementById('api-keys-panel').hidden, 'Key panel remained after sign out');
  assert.equal(ui.doc.getElementById('api-key-secret'), null);
});
