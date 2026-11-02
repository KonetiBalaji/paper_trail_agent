"""Read-only, source-bound layout admission. PDFs cannot install definitions.

Repository review and release CI are the trust boundary. Hashes detect stale or
changed evidence; they are not a signature against an administrator rewriting
the repository. No provider, OCR engine or regression executes on a read.
"""
import hashlib
import json
from pathlib import Path
import re
from functools import lru_cache
from importlib.metadata import version, PackageNotFoundError

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = 'data/layout_registry.json'
REPORT = 'docs/layout-package-results.json'
LEGACY_DEMO = {'clean', 'contradiction', 'math_error', 'messy', 'bank_clean', 'bank_error'}
LEGACY_BENCHMARK = {
    'loan_columns_clean', 'loan_columns_error', 'loan_columns_contradiction', 'loan_reverse_columns',
    'loan_cross_page', 'loan_split_row', 'loan_duplicate', 'loan_partial', 'bank_debit_credit',
    'bank_signed', 'bank_cross_page', 'bank_bad_carry', 'injection_note', 'identity_conflict',
    'ambiguous_date', 'currency_guard', 'missing_tranche', 'corrupt_pdf', 'oversized_pdf'}
LEGACY_OCR = {'table_review', 'labeled_error', 'degraded', 'blank'}


def require(condition):
    if not condition:
        raise ValueError('Layout admission evidence is missing, stale or inconsistent')


def raw(path, limit=2_000_000):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit)
    return path.read_bytes()


def read(path):
    return json.loads(raw(path).decode('utf-8'))


def digest(path):
    return hashlib.sha256(raw(path, 12 * 1024 * 1024)).hexdigest()


def runtime_sources(root=ROOT):
    paths = list((root / 'app').rglob('*.py')) + [p for p in (root / 'app/static').rglob('*')
             if p.suffix in ('.js', '.html', '.css') and p.is_file()]
    return {p.relative_to(root).as_posix(): hashlib.sha256(raw(p).decode('utf-8').replace('\r\n', '\n').encode()).hexdigest()
            for p in sorted(paths)}


def fixture_hashes(root=ROOT):
    paths = [p for folder in ('synthetic', 'benchmark', 'ocr', 'layout_packages')
             for p in (root / 'data' / folder).rglob('*') if p.is_file() and p.suffix in ('.json', '.pdf')]
    require(len(paths) <= 512)
    require(sum(p.stat().st_size for p in paths) <= 40 * 1024 * 1024)
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(paths)}


@lru_cache(maxsize=8)
def _versions(names):
    try:
        return tuple((name, version(name)) for name in names)
    except PackageNotFoundError as exc:
        raise ValueError('Layout runtime dependency unavailable') from exc


def runtime_dependencies(names=None):
    if names is None:
        text = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
        names = re.findall(r'^([A-Za-z0-9_.-]+)==', text, re.M)
    require(0 < len(names) <= 100 and all(re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', n) for n in names))
    return dict(_versions(tuple(sorted(names))))


def suite(report, expected):
    rows = report['cases']; summary = report['summary']
    require(len(rows) == len(expected) and {r['case'] for r in rows} == set(expected))
    require(all(r['passed'] is True and not r.get('errors') and not r.get('false_clean') for r in rows))
    require(summary['total'] == len(rows) and summary['passed'] == len(rows) and summary['failed'] == 0)
    require(summary['false_clean_count'] == 0)


def inventory(root, packages):
    """An admitted version cannot disappear merely by deleting its directory."""
    from .layout_proposals import Proposal
    data = read(root / 'inventory.json')
    require(data['schema_version'] == 1 and data['packages'])
    require(set(data['packages']) <= set(packages))
    for name, admitted in data['packages'].items():
        require(isinstance(name, str) and re.fullmatch(r'[a-z][a-z0-9_]{2,47}', name))
        folder = root / name
        manifest = read(folder / 'cases/manifest.json')
        require(digest(folder / 'cases/manifest.json') == admitted['manifest_sha256'])
        require([r['case'] for r in manifest['cases']] == admitted['cases'])
        definitions = [Proposal.model_validate_json(json.dumps(row)) for row in read(folder / 'definitions.json')['definitions']]
        require({p.id: p.fingerprint() for p in definitions} == admitted['definition_sha256'])
    return data


def verify(root, registry, report):
    from .layout_proposals import Proposal, normalize
    require(set(registry) == {'schema_version', 'packages', 'report_sha256'} and registry['schema_version'] == 1)
    names = registry['packages']
    require(isinstance(names, list) and 0 < len(names) <= 32 and len(set(names)) == len(names))
    require(all(isinstance(n, str) and re.fullmatch(r'[a-z][a-z0-9_]{2,47}', n) for n in names))
    actual_packages = sorted(p.parent.name for p in (root / 'data/layout_packages').glob('*/definitions.json'))
    require(sorted(names) == actual_packages)
    admitted_inventory = inventory(root / 'data/layout_packages', names)
    require(set(admitted_inventory['packages']) == set(names))
    require(registry['report_sha256'] == digest(root / REPORT))
    require(report['schema_version'] == 1 and report['full_regression_passed'] is True)
    require(report['inputs_unchanged_during_run'] is True and report['review_records_valid'] is True)
    require(report['admitted_inventory_valid'] is True)
    require(report['legacy_scope_complete'] == {'native': True, 'ocr': True})
    current = runtime_sources(root)
    require(current and {k: v for k, v in report['source_sha256'].items() if k.startswith('app/')} == current)
    require(report['fixture_sha256'] == fixture_hashes(root))
    dependencies = report['runtime_dependencies']
    require({'pdfplumber', 'pdfminer.six', 'pypdfium2', 'pydantic'} <= set(dependencies))
    require(dependencies == runtime_dependencies(tuple(dependencies)))
    native = report['native']; require(native['passed'] is True and native['candidate']['passed'] is True)
    require(native['regression']['manifest_sha256'] == digest(root / 'data/benchmark/manifest.json'))
    suite(native['baseline'], LEGACY_DEMO); suite(native['regression'], LEGACY_BENCHMARK)
    ocr = report['ocr']; require(ocr['passed'] is True)
    require(ocr['manifest_sha256'] == digest(root / 'data/ocr/manifest.json'))
    require(len(ocr['cases']) == 4 and {r['case'] for r in ocr['cases']} == LEGACY_OCR)
    require(all(r['passed'] is True and r['checks'] and all(v is True for v in r['checks'].values())
                and r['findings'] and all(f['severity'] == 'review' for f in r['findings']) for r in ocr['cases']))
    candidates = native['candidate']['packages']; reviews = report['review_records']
    require(len(candidates) == len(names) and {r['package'] for r in candidates} == set(names))
    require(len(reviews) == len(names) and {r['package'] for r in reviews} == set(names))
    definitions = []; provenance = {}; fingerprints = {}
    for name in names:
        folder = root / 'data/layout_packages' / name
        package = read(folder / 'definitions.json'); manifest = read(folder / 'cases/manifest.json')
        require(package['schema_version'] == 1 and package['fictional'] is True)
        require(manifest['schema_version'] == 1 and manifest['fictional'] is True and manifest['cases'])
        require(0 < len(package['definitions']) <= 32)
        proposals = [Proposal.model_validate_json(json.dumps(row)) for row in package['definitions']]
        review = read(folder / 'review.json'); saved = next(r for r in reviews if r['package'] == name)
        expected = {p.id: p.fingerprint() for p in proposals}
        require(review['schema_version'] == 1 and review['review_kind'] in ('assistant', 'human'))
        require(review['decision'] == 'reviewed_for_synthetic_scope' and review['definition_sha256'] == expected)
        require(review['manifest_sha256'] == digest(folder / 'cases/manifest.json'))
        require(saved['reviewed'] is True and saved['record'] == review and saved['record_sha256'] == digest(folder / 'review.json'))
        for case in manifest['cases']:
            require(re.fullmatch(r'[a-z_]+', case['case']))
            require(read(folder / 'cases' / case['case'] / 'ground_truth.json') == case)
        observed = next(r['report'] for r in candidates if r['package'] == name)
        require(observed['manifest_sha256'] == digest(folder / 'cases/manifest.json'))
        suite(observed, {r['case'] for r in manifest['cases']})
        definitions.extend(proposals); fingerprints.update(expected)
        for proposal in proposals:
            provenance[proposal.id] = {'package': name, 'review_kind': review['review_kind'],
                'receipt_sha256': registry['report_sha256'], 'review_sha256': saved['record_sha256'], 'promoted': True}
    require(0 < len(definitions) <= 32 and len({p.id for p in definitions}) == len(definitions))
    require(len({p.marker for p in definitions}) == len(definitions))
    require(len({normalize(p.header) for p in definitions}) == len(definitions))
    require(fingerprints == report['definition_sha256'])
    return {'status': 'active', 'definitions': definitions, 'provenance': provenance,
            'receipt_sha256': registry['report_sha256'],
            'corpus_cases': 6 + 19 + 4 + sum(len(r['report']['cases']) for r in candidates)}


def load(root=None):
    root = Path(root) if root is not None else ROOT
    if not (root / REGISTRY).exists():
        return {'status': 'inactive', 'definitions': [], 'provenance': {}}
    try:
        return verify(root, read(root / REGISTRY), read(root / REPORT))
    except (ValueError, OSError, KeyError, TypeError, AttributeError, StopIteration):
        return {'status': 'stale', 'definitions': [], 'provenance': {}}


def public_status():
    result = load()
    return {'status': result['status'], 'receipt_sha256': result.get('receipt_sha256'),
            'corpus_cases': result.get('corpus_cases', 0), 'scope': 'Reviewed fictional native-text layouts only.',
            'layouts': [{'id': p.id, 'header': p.header, 'kind': p.kind, 'max_pages': p.max_pages,
                         'ocr_supported': False, 'review_kind': result['provenance'][p.id]['review_kind']}
                        for p in result['definitions']]}
