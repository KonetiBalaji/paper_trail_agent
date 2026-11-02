"""Admission fault tests use a labelled synthetic receipt root, never production proof."""
import copy
import io
import json
from pathlib import Path
import shutil
import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from app import layout_registry as registry, main, meta

PROJECT = Path(__file__).resolve().parents[1]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8', newline='\n')


@pytest.fixture
def admitted(tmp_path):
    # Deliberately synthetic validator fixture. Rebind historical observations to
    # this fake root to exercise admission mutations, not claim new evaluations.
    for folder in ('synthetic', 'benchmark', 'ocr', 'layout_packages'):
        shutil.copytree(PROJECT / 'data' / folder, tmp_path / 'data' / folder)
    (tmp_path / 'app').mkdir()
    (tmp_path / 'app/unit_fixture.py').write_text('# Synthetic validator unit root only\n')
    report = json.loads((PROJECT / registry.REPORT).read_text())
    report['source_sha256'] = registry.runtime_sources(tmp_path)
    report['fixture_sha256'] = registry.fixture_hashes(tmp_path)
    report['runtime_dependencies'] = registry.runtime_dependencies()
    report['admitted_inventory_valid'] = True
    # Review record changed only its activation note after the old observation.
    review = registry.read(tmp_path / 'data/layout_packages/cedar_v1/review.json')
    report['review_records'][0]['record'] = review
    report['review_records'][0]['record_sha256'] = registry.digest(tmp_path / 'data/layout_packages/cedar_v1/review.json')
    def save():
        write(tmp_path / registry.REPORT, report)
        write(tmp_path / registry.REGISTRY, {'schema_version': 1, 'packages': ['cedar_v1'],
                                           'report_sha256': registry.digest(tmp_path / registry.REPORT)})
    save()
    return tmp_path, report, save


def test_valid_receipt_enables_exact_native_mapping_and_real_calculation(admitted, monkeypatch):
    root, _, _ = admitted
    monkeypatch.setattr(registry, 'ROOT', root)
    status = registry.load()
    assert status['status'] == 'active' and len(status['definitions']) == 2 and status['corpus_cases'] == 41
    path = root / 'data/layout_packages/cedar_v1/cases/loan_math_error/statement_1.pdf'
    report = main.analyze_files([UploadFile(filename='fictional.pdf', file=io.BytesIO(path.read_bytes()))], 'local', persist=False)
    assert report['status'] == 'discrepancies'
    finding = report['findings'][0]
    assert finding['difference'] == '50.00' and finding['computed'] == '2437.10'
    doc = report['documents'][0]
    assert doc['layout_support']['promoted'] and doc['layout_support']['review_kind'] == 'assistant'
    assert doc['layout_support']['receipt_sha256'] == status['receipt_sha256']
    assert 'reviewed:cedar_capital_v1' in doc['layouts']


@pytest.mark.parametrize('mutation', ['source', 'static', 'pdf', 'truth', 'review', 'definition', 'missing_package', 'extra_package', 'report'])
def test_any_stale_input_disables_support_without_cached_success(admitted, mutation):
    root, _, _ = admitted
    assert registry.load(root)['status'] == 'active'
    package = root / 'data/layout_packages/cedar_v1'
    paths = {'source': root / 'app/unit_fixture.py', 'pdf': package / 'cases/loan_clean/statement_1.pdf',
             'truth': package / 'cases/loan_clean/ground_truth.json', 'review': package / 'review.json',
             'definition': package / 'definitions.json', 'report': root / registry.REPORT}
    if mutation == 'missing_package': (package / 'definitions.json').unlink()
    elif mutation == 'extra_package': write(root / 'data/layout_packages/new_candidate/definitions.json', {})
    elif mutation == 'static':
        path = root / 'app/static/added.js'; path.parent.mkdir(); path.write_text('/* unverified source */')
    else:
        path = paths[mutation]; path.write_bytes(path.read_bytes() + b'changed')
    result = registry.load(root)
    assert result['status'] == 'stale' and not result['definitions']


@pytest.mark.parametrize('mutation', ['ocr_missing', 'ocr_confirmed', 'old_case_missing', 'old_case_failed',
    'false_clean', 'candidate_missing', 'review_missing', 'review_not_valid', 'definition_hash', 'full_flag', 'dependency'])
def test_rehashed_but_inconsistent_evidence_cannot_promote(admitted, mutation):
    root, report, save = admitted
    if mutation == 'ocr_missing': report['ocr']['cases'].pop()
    if mutation == 'ocr_confirmed': report['ocr']['cases'][0]['findings'][0]['severity'] = 'confirmed'
    if mutation == 'old_case_missing': report['native']['regression']['cases'].pop()
    if mutation == 'old_case_failed': report['native']['baseline']['cases'][0]['passed'] = False
    if mutation == 'false_clean': report['native']['regression']['summary']['false_clean_count'] = 1
    if mutation == 'candidate_missing': report['native']['candidate']['packages'] = []
    if mutation == 'review_missing': report['review_records'] = []
    if mutation == 'review_not_valid': report['review_records_valid'] = False
    if mutation == 'definition_hash': report['definition_sha256']['cedar_capital_v1'] = '0' * 64
    if mutation == 'full_flag': report['full_regression_passed'] = False
    if mutation == 'dependency': report['runtime_dependencies']['pdfplumber'] = '0.0.0'
    save()
    assert registry.load(root)['status'] == 'stale'


def test_missing_or_malformed_registry_is_inactive_or_stale(tmp_path):
    assert registry.load(tmp_path)['status'] == 'inactive'
    write(tmp_path / registry.REGISTRY, ['not a registry'])
    write(tmp_path / registry.REPORT, {})
    assert registry.load(tmp_path)['status'] == 'stale'


def test_status_api_is_read_only_and_never_calls_a_provider(admitted, monkeypatch):
    root, _, _ = admitted
    monkeypatch.setattr(registry, 'ROOT', root)
    monkeypatch.setenv('PAPER_TRAIL_MODE', 'local'); monkeypatch.delenv('VERCEL', raising=False)
    monkeypatch.setattr(meta, 'request', lambda *a, **k: pytest.fail('Receipt read called provider'))
    with TestClient(main.app) as client:
        response = client.get('/api/layouts')
        assert response.status_code == 200 and response.json()['status'] == 'active'
        assert len(response.json()['layouts']) == 2
        assert response.json()['layouts'][0]['ocr_supported'] is False
        assert client.post('/api/layouts', json={'promoted': True}).status_code == 405


def test_stale_receipt_produces_review_through_actual_parser(admitted, monkeypatch):
    root, _, _ = admitted
    monkeypatch.setattr(registry, 'ROOT', root)
    (root / 'app/unit_fixture.py').write_text('# changed after evaluation\n')
    path = root / 'data/layout_packages/cedar_v1/cases/loan_clean/statement_1.pdf'
    report = main.analyze_files([UploadFile(filename='fictional.pdf', file=io.BytesIO(path.read_bytes()))], 'local', persist=False)
    assert report['status'] == 'review'
    assert not any(f['severity'] == 'confirmed' for f in report['findings'])
    assert any(f['type'] == 'layout_not_promoted' for f in report['findings'])
    assert not report['documents'][0].get('layout_support')


def test_direct_model_validation_preserves_receipt_and_rejects_swapped_fields(admitted, monkeypatch):
    from app.core import parse_statement, read_pdf
    root, _, _ = admitted
    monkeypatch.setattr(registry, 'ROOT', root)
    path = root / 'data/layout_packages/cedar_v1/cases/loan_clean/statement_1.pdf'
    doc = read_pdf(path.read_bytes(), 'fictional.pdf', 'doc1')
    statement = parse_statement(copy.deepcopy(doc))
    assert 'layout_support' not in doc
    meta.validate_statement(statement, doc)
    assert doc['layout_support']['id'] == 'cedar_capital_v1'
    forged = copy.deepcopy(statement)
    row = forged['tranches'][0]; row['principal'], row['interest'] = row['interest'], row['principal']
    with pytest.raises(meta.EvidenceError):meta.validate_statement(forged, doc)


def test_registry_cannot_select_an_arbitrary_package_path(admitted):
    root, _, _ = admitted
    data = registry.read(root / registry.REGISTRY); data['packages'] = ['../../private']
    write(root / registry.REGISTRY, data)
    assert registry.load(root)['status'] == 'stale'


def test_publisher_validates_before_atomic_write_and_can_verify_without_writes(admitted, monkeypatch):
    from scripts import promote_layouts
    root, report, _ = admitted
    monkeypatch.setattr(registry, 'ROOT', root)
    monkeypatch.setattr(promote_layouts, 'sources', lambda: report['source_sha256'])
    monkeypatch.setattr(promote_layouts, 'fixtures', lambda: registry.fixture_hashes(root))
    (root / registry.REGISTRY).unlink()
    assert promote_layouts.publish()['status'] == 'active'
    original = (root / registry.REGISTRY).read_bytes()
    assert promote_layouts.publish(check=True)['check_only'] is True
    assert (root / registry.REGISTRY).read_bytes() == original


def test_failed_receipt_cannot_replace_registry(admitted, monkeypatch):
    from scripts import promote_layouts
    root, report, _ = admitted
    monkeypatch.setattr(registry, 'ROOT', root)
    monkeypatch.setattr(promote_layouts, 'sources', lambda: report['source_sha256'])
    monkeypatch.setattr(promote_layouts, 'fixtures', lambda: registry.fixture_hashes(root))
    previous = (root / registry.REGISTRY).read_bytes()
    report['full_regression_passed'] = False; write(root / registry.REPORT, report)
    with pytest.raises(ValueError):promote_layouts.publish()
    assert (root / registry.REGISTRY).read_bytes() == previous


def test_materialized_or_virtual_negative_fixture_has_identical_binding(admitted):
    root, _, _ = admitted
    path = root / 'data/benchmark/oversized_pdf/statement_1.pdf'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'%PDF-1.7\n' + b'0' * (10 * 1024 * 1024))
    materialized = registry.fixture_hashes(root)
    path.unlink()
    assert registry.fixture_hashes(root) == materialized
    assert materialized['virtual:benchmark/oversized_pdf/statement_1.pdf'] == registry.oversized_hash()
    assert registry.load(root)['status'] == 'active'
    path.write_bytes(b'%PDF-wrong-negative-fixture')
    assert registry.load(root)['status'] == 'stale'
