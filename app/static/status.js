async function checkEndpoint(path, expected) {
  try {
    const response = await fetch(path, {cache: 'no-store', signal: AbortSignal.timeout(10000)});
    return response.ok && (await response.json()).status === expected;
  } catch {
    return false;
  }
}

async function showStatus() {
  const [api, layouts] = await Promise.all([
    checkEndpoint('/api/health', 'ok'),
    checkEndpoint('/api/layouts', 'active'),
  ]);
  document.getElementById('api').textContent = api ? 'Responding' : 'Check failed';
  document.getElementById('layouts').textContent = layouts ? 'Active' : 'Check failed';
  document.getElementById('status').textContent = api && layouts ? 'Public checks passed.' : 'A public check failed.';
  document.getElementById('checked').textContent = `Checked ${new Date().toLocaleString()}`;
}

showStatus();
