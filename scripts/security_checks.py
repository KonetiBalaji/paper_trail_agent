"""Bounded, redacted security gates; no provider credentials or production writes.

Audit the pinned core/OCR dependency inventories, frontend lock, full reachable
Git history, and tracked working files. Test the secret scanner with a fresh
synthetic canary. Only counts/IDs/versions/hashes enter the public evidence.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'scripts/security/gitleaks.toml'
INPUTS = ('requirements-lock.txt', 'requirements-ocr-lock.txt',
          'tests/frontend/package-lock.json', 'tests/requirements-security.txt',
          'scripts/security/gitleaks.toml', 'scripts/security_checks.py')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(command, timeout=180, cwd=ROOT):
    # Never echo scanner output: even scanner bugs must not disclose a match.
    result = subprocess.run(command, cwd=cwd, capture_output=True, timeout=timeout)
    return result.returncode, result.stdout


def scan(binary, mode, target, output):
    command = [binary, mode, str(target), '--config', str(CONFIG),
               '--ignore-gitleaks-allow', '--redact=100', '--no-banner',
               '--report-format', 'json', '--report-path', str(output), '--timeout', '90']
    if mode == 'git':
        command.append('--log-opts=--all')
    code, _ = execute(command, timeout=120)
    if code not in (0, 1) or not output.exists():
        raise RuntimeError('Secret scanner failed operationally; inspect only local redacted output.')
    findings = json.loads(output.read_text(encoding='utf-8')) or []
    if (code == 0) != (len(findings) == 0):
        raise RuntimeError('Secret scanner exit/result mismatch')
    # Deliberately omit matches, file content, paths, commit messages and authors.
    return {'passed': code == 0, 'finding_count': len(findings),
            'rule_ids': sorted({item['RuleID'] for item in findings})}


def run(binary, audit_python):
    version_code, raw = execute([binary, 'version'])
    if version_code or raw.decode().strip() != '8.30.1':
        raise RuntimeError('Use the checksum-verified Gitleaks 8.30.1 binary')
    if subprocess.check_output(['git', 'rev-parse', '--is-shallow-repository'], cwd=ROOT, text=True).strip() != 'false':
        raise RuntimeError('Full history is required; fetch with depth 0')
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    with tempfile.TemporaryDirectory(prefix='paper-trail-security-') as directory:
        temporary = Path(directory)
        canary = temporary / 'canary'; canary.mkdir()
        (canary / 'synthetic.txt').write_text('token=pta_api_' + secrets.token_urlsafe(32) + ' # gitleaks:allow', encoding='utf-8')
        detected = scan(binary, 'dir', canary, temporary / 'canary.json')
        if detected['passed'] or 'paper-trail-integration-key' not in detected['rule_ids']:
            raise RuntimeError('Secret scanner failed its canary; no scan is accepted')
        history = scan(binary, 'git', ROOT, temporary / 'history.json')
        snapshot = temporary / 'tracked'; snapshot.mkdir()
        manifest = {}
        for name in filter(None, files):
            source = ROOT / name
            if source.is_symlink() or not source.resolve().is_relative_to(ROOT.resolve()):
                raise RuntimeError('Tracked symlink or escaped path cannot be scanned safely')
            if not source.is_file():
                raise RuntimeError('Tracked file missing; secret scan is incomplete')
            target = snapshot / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target); manifest[name] = sha(source)
        working = scan(binary, 'dir', snapshot, temporary / 'tracked.json')
        audit_output = temporary / 'python.json'
        code, _ = execute([audit_python, '-m', 'pip_audit', '-r', 'requirements-lock.txt',
                           '-r', 'requirements-ocr-lock.txt', '--no-deps', '--disable-pip',
                           '--strict', '--format', 'json', '--output', str(audit_output)])
        if code not in (0, 1) or not audit_output.exists():
            raise RuntimeError('Python advisory audit could not complete')
        audit = json.loads(audit_output.read_text(encoding='utf-8'))
        rows = audit['dependencies']
        skipped = [item['name'] for item in rows if item.get('skip_reason')]
        vulnerabilities = [{'name': item['name'], 'version': item.get('version'),
                            'ids': [v['id'] for v in item.get('vulns', [])]}
                           for item in rows if item.get('vulns')]
        if skipped:
            raise RuntimeError('An inventory entry was not audited; do not report a clean audit')
        if (code == 0) != (not vulnerabilities):
            raise RuntimeError('Python advisory audit exit/result mismatch')
        npm = shutil.which('npm')
        if not npm:
            raise RuntimeError('npm is required for the frontend lock audit')
        # npm.cmd is a fixed executable path on Windows, with fixed arguments.
        npm_code, raw = execute([npm, 'audit', '--prefix', 'tests/frontend', '--json', '--audit-level=low'])
        npm_result = json.loads(raw.decode('utf-8-sig'))
        if npm_result.get('error') or 'vulnerabilities' not in npm_result.get('metadata', {}):
            raise RuntimeError('npm advisory audit could not complete')
        npm_counts = npm_result['metadata']['vulnerabilities']
        if (npm_code == 0) != (npm_counts['total'] == 0):
            raise RuntimeError('npm audit exit/result mismatch')
        passed = history['passed'] and working['passed'] and not vulnerabilities and npm_counts['total'] == 0
        return {'schema_version': 1, 'passed': passed, 'checked_at': datetime.now(timezone.utc).isoformat(),
                'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'scope': 'Default Gitleaks rules plus scoped API keys; reachable Git history and tracked working files only. Python/OCR pinned inventories and frontend lock against current advisory services. No proof against unknown vulnerabilities or secrets outside scanner rules. Ignored local secrets are deliberately excluded.',
                'secrets': {'version': '8.30.1', 'canary_detected': True, 'history': history, 'tracked_files': working,
                            'tracked_file_count': len(manifest), 'tracked_manifest_sha256': hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
                            'commits_scanned': int(subprocess.check_output(['git', 'rev-list', '--all', '--count'], cwd=ROOT, text=True))},
                'python': {'auditor': 'pip-audit==2.10.1', 'service': 'PyPI', 'no_dependency_resolution': True,
                           'audited_count': len(rows), 'vulnerabilities': vulnerabilities, 'skipped': skipped},
                'frontend': {'auditor': 'npm audit', 'counts': npm_counts},
                'input_sha256': {name: sha(ROOT / name) for name in INPUTS}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gitleaks', required=True)
    parser.add_argument('--audit-python', default=sys.executable)
    parser.add_argument('--report', default='work/security-results.json')
    args = parser.parse_args()
    try:
        report = run(str(Path(args.gitleaks).resolve()), args.audit_python)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError):
        # Avoid exception representations containing subprocess/scanner content.
        print('Security checks could not complete; no passing evidence was produced.', file=sys.stderr)
        raise SystemExit(2)
    output = Path(args.report); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'passed': report['passed'], 'python_packages': report['python']['audited_count'],
                      'secret_findings': report['secrets']['history']['finding_count'] + report['secrets']['tracked_files']['finding_count'],
                      'npm_vulnerabilities': report['frontend']['counts']['total']}))
    raise SystemExit(0 if report['passed'] else 1)
