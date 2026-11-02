"""Evaluate candidate packages plus all existing cases; never installs a layout."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import benchmark
from app.layout_proposals import Proposal, evaluate_trial, trial
from app.layout_registry import runtime_dependencies, inventory, fixture_hashes

PROJECT = Path(__file__).resolve().parents[1]
PACKAGES = PROJECT / 'data/layout_packages'
LEGACY_BENCHMARK = {
    'loan_columns_clean', 'loan_columns_error', 'loan_columns_contradiction', 'loan_reverse_columns',
    'loan_cross_page', 'loan_split_row', 'loan_duplicate', 'loan_partial', 'bank_debit_credit',
    'bank_signed', 'bank_cross_page', 'bank_bad_carry', 'injection_note', 'identity_conflict',
    'ambiguous_date', 'currency_guard', 'missing_tranche', 'corrupt_pdf', 'oversized_pdf'}
LEGACY_DEMO = {'clean', 'contradiction', 'math_error', 'messy', 'bank_clean', 'bank_error'}
LEGACY_OCR = {'table_review', 'labeled_error', 'degraded', 'blank'}


def complete_scope(rows, expected):
    return len(rows) == len(expected) and {row['case'] for row in rows} == expected


def sources():
    paths = ([p for folder in ('app', 'scripts', 'tests') for p in (PROJECT / folder).rglob('*.py')
              if '__pycache__' not in p.parts] + list((PROJECT / '.github/workflows').glob('*.yml')))
    paths += [p for p in (PROJECT / 'app/static').rglob('*') if p.is_file() and p.suffix in ('.js', '.html', '.css')]
    paths += list((PROJECT / 'tests/frontend').glob('*.mjs')) + list(PROJECT.glob('requirements*.txt'))
    return {p.relative_to(PROJECT).as_posix(): hashlib.sha256(p.read_text(encoding='utf-8').encode()).hexdigest()
            for p in sorted(paths) if p.is_file()}


def fixtures(package_root=PACKAGES):
    package_root = Path(package_root)
    base = fixture_hashes(PROJECT)
    if package_root == PACKAGES: return base
    base = {key: value for key, value in base.items() if not key.startswith('data/layout_packages/')}
    paths = [p for p in package_root.rglob('*') if p.is_file() and p.suffix in ('.json', '.pdf')]
    return base | {(p.relative_to(PROJECT).as_posix() if p.is_relative_to(PROJECT)
             else 'external-package/' + p.relative_to(package_root).as_posix()):
            hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def definitions(root):
    raw = json.loads((root / 'definitions.json').read_text(encoding='utf-8'))
    if raw.get('schema_version') != 1 or raw.get('fictional') is not True:
        raise ValueError('Only cleared fictional version-one packages are accepted')
    rows = raw.get('definitions')
    if not isinstance(rows, list) or not rows or len(rows) > 32:
        raise ValueError('Missing or excessive package definitions')
    return [Proposal.model_validate_json(json.dumps(row)) for row in rows]


def validate_truth(root):
    manifest = json.loads((root / 'cases/manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or manifest.get('fictional') is not True or not manifest.get('cases'):
        raise ValueError('Missing cleared known-answer cases')
    for case in manifest['cases']:
        if not re.fullmatch(r'[a-z_]+', case['case']):
            raise ValueError('Invalid case directory')
        reviewed = json.loads((root / 'cases' / case['case'] / 'ground_truth.json').read_text(encoding='utf-8'))
        if reviewed != case:
            raise ValueError('Reviewable ground truth differs from the evaluated manifest')


def review_record(root):
    path = root / 'review.json'
    if not path.is_file():
        return {'package': root.name, 'reviewed': False, 'reason': 'No review record'}
    data = json.loads(path.read_text(encoding='utf-8'))
    expected = {p.id: p.fingerprint() for p in definitions(root)}
    reviewed = (data.get('schema_version') == 1 and data.get('review_kind') in ('assistant', 'human')
                and data.get('decision') == 'reviewed_for_synthetic_scope'
                and data.get('definition_sha256') == expected
                and data.get('manifest_sha256') == hashlib.sha256((root / 'cases/manifest.json').read_bytes()).hexdigest())
    return {'package': root.name, 'reviewed': reviewed, 'record': data,
            'record_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def evaluate(*, with_ocr=False, package_root=PACKAGES):
    package_root = Path(package_root)
    packages = sorted(p.parent for p in package_root.glob('*/definitions.json'))
    if not packages:
        raise ValueError('No layout packages; an empty run cannot pass')
    proposals = [p for root in packages for p in definitions(root)]
    for root in packages:
        validate_truth(root)

    def candidates():
        rows = []
        # All packages are rerun, including old candidates, not only the new one.
        for root in packages:
            report = benchmark.evaluate_suite(root / 'cases')
            rows.append({'package': root.name, 'report': report})
        passed = all(row['report']['summary']['failed'] == 0 and
                     row['report']['summary']['false_clean_count'] == 0 for row in rows)
        return {'passed': passed, 'packages': rows}

    started_sources, started_fixtures = sources(), fixtures(package_root)
    try:
        inventory(package_root, [p.name for p in packages]); inventory_valid = True
    except (ValueError, OSError, KeyError, TypeError):
        inventory_valid = False
    result = evaluate_trial(proposals, candidates)
    native_scope = (complete_scope(result['baseline']['cases'], LEGACY_DEMO) and
                    complete_scope(result['regression']['cases'], LEGACY_BENCHMARK))
    ocr = None
    if with_ocr:
        from scripts.evaluate_ocr import evaluate as evaluate_ocr
        with trial(proposals):
            ocr = evaluate_ocr(PROJECT / 'data/ocr')
    reviews = [review_record(root) for root in packages]
    unchanged = started_sources == sources() and started_fixtures == fixtures(package_root)
    ocr_scope = ocr is not None and complete_scope(ocr['cases'], LEGACY_OCR)
    full = result['passed'] and native_scope and ocr_scope and ocr['passed'] and unchanged and inventory_valid
    return {'schema_version': 1, 'native_passed': result['passed'] and native_scope,
            'legacy_scope_complete': {'native': native_scope, 'ocr': ocr_scope}, 'full_regression_passed': bool(full),
            'promoted': False, 'human_review': None,
            'review_records': reviews, 'review_records_valid': all(row['reviewed'] for row in reviews),
            'admitted_inventory_valid': inventory_valid,
            'definition_sha256': {p.id: p.fingerprint() for p in proposals},
            'runtime_dependencies': runtime_dependencies(),
            'source_sha256': started_sources, 'fixture_sha256': started_fixtures,
            'inputs_unchanged_during_run': unchanged, 'native': result, 'ocr': ocr,
            'remaining_gates': ([] if inventory_valid else ['admitted package inventory']) +
                               ([] if all(row['reviewed'] for row in reviews) else ['mapping and truth review']) +
                               ['verified promotion receipt and runtime registry',
                                'deployed provenance and release verification']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-ocr', action='store_true', help='Run actual CPU OCR, not a cached report')
    parser.add_argument('--report', type=Path, default=PROJECT / 'work/layout-package-results.json')
    args = parser.parse_args()
    result = evaluate(with_ocr=args.with_ocr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'native_passed': result['native_passed'], 'full_regression_passed': result['full_regression_passed'],
                      'promoted': False, 'packages': [{'package': row['package'], 'summary': row['report']['summary']}
                       for row in result['native']['candidate']['packages']]}))
    raise SystemExit(0 if (result['full_regression_passed'] if args.with_ocr else result['native_passed']) else 1)
