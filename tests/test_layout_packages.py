import json
from pathlib import Path
import pytest
from app import benchmark
from app.layout_proposals import trial
from scripts import evaluate_layout_package as gate
from scripts.generate_layout_package import generate

PACKAGE = gate.PACKAGES / 'cedar_v1'
MANIFEST = json.loads((PACKAGE / 'cases/manifest.json').read_text())
CASES = {case['case']: case for case in MANIFEST['cases']}


@pytest.mark.parametrize('name', list(CASES))
def test_candidate_pdf_truth_through_real_pipeline(name):
    with trial(gate.definitions(PACKAGE)):
        result = benchmark.evaluate_case(CASES[name], PACKAGE / 'cases')
    assert result['passed'], result
    assert not result['false_clean']


def test_candidates_cannot_become_supported_outside_trial():
    for name in ('loan_clean', 'bank_clean', 'loan_math_error'):
        report = benchmark.evaluate_case(CASES[name], PACKAGE / 'cases')
        assert report['status'] == 'review'
        assert not report['passed']


def test_candidate_regeneration_preserves_all_pdf_and_truth_hashes(tmp_path):
    assert generate(tmp_path) == MANIFEST['cases']
    assert json.loads((tmp_path / 'definitions.json').read_text()) == json.loads((PACKAGE / 'definitions.json').read_text())


def test_native_gate_is_not_full_regression_or_approval():
    report = gate.evaluate()
    assert report['native_passed'] and not report['full_regression_passed']
    assert report['promoted'] is False and report['human_review'] is None
    assert report['native']['baseline']['summary']['passed'] == 6
    assert report['native']['regression']['summary']['passed'] == 19
    assert report['native']['candidate']['packages'][0]['report']['summary']['passed'] == 12
    assert report['source_sha256'] and report['fixture_sha256'] and report['inputs_unchanged_during_run']


def test_corrupt_candidate_pdf_blocks_gate(tmp_path):
    generate(tmp_path / 'package')
    (tmp_path / 'package/cases/loan_clean/statement_1.pdf').write_bytes(b'%PDF-invalid')
    report = gate.evaluate(package_root=tmp_path)
    assert not report['native_passed'] and not report['full_regression_passed']
    assert not report['promoted']


def test_reversed_mapping_fails_independent_ground_truth(tmp_path):
    generate(tmp_path / 'package')
    path = tmp_path / 'package/definitions.json'
    data = json.loads(path.read_text()); data['definitions'][0]['columns'] = ['interest', 'principal']
    path.write_text(json.dumps(data))
    report = gate.evaluate(package_root=tmp_path)
    assert not report['native_passed']


def test_an_old_package_failure_blocks_a_new_good_package(tmp_path):
    generate(tmp_path / 'old_package'); generate(tmp_path / 'new_package')
    # Distinct declarations preserve a valid all-package trial while retaining
    # the old package's financial truth failure; a duplicate cannot mask it.
    path = tmp_path / 'old_package/definitions.json'; data = json.loads(path.read_text())
    for row in data['definitions']:
        row['id'] = 'old_' + row['id']; row['marker'] += '-OLD'; row['header'] += ' Legacy'
    path.write_text(json.dumps(data))
    truth = tmp_path / 'old_package/cases/manifest.json'
    manifest = json.loads(truth.read_text())
    manifest['cases'][0]['documents'][0]['truth']['tranches'][0]['principal'] = '1.00'
    truth.write_text(json.dumps(manifest))
    (tmp_path / 'old_package/cases/loan_clean/ground_truth.json').write_text(json.dumps(manifest['cases'][0]))
    report = gate.evaluate(package_root=tmp_path)
    assert len(report['native']['candidate']['packages']) == 2
    assert not report['native_passed']


def test_changed_source_during_evaluation_cannot_pass_full_gate(monkeypatch):
    original = gate.sources; calls = []
    def changed():
        calls.append(1)
        return original() if len(calls) == 1 else {'modified': 'during-run'}
    monkeypatch.setattr(gate, 'sources', changed)
    report = gate.evaluate()
    assert not report['inputs_unchanged_during_run'] and not report['full_regression_passed']


def test_empty_package_run_cannot_pass(tmp_path):
    with pytest.raises(ValueError):
        gate.evaluate(package_root=tmp_path)


def test_dropped_old_case_cannot_make_a_smaller_green_gate(monkeypatch):
    original = gate.benchmark.evaluate_suite
    def shrunk(*args, **kwargs):
        report = original(*args, **kwargs)
        if len(report['cases']) == 19:
            report['cases'].pop()
            report['summary'].update(total=18, passed=18, failed=0)
        return report
    monkeypatch.setattr(gate.benchmark, 'evaluate_suite', shrunk)
    report = gate.evaluate()
    assert not report['legacy_scope_complete']['native']
    assert not report['native_passed'] and not report['full_regression_passed']


def test_cached_or_incomplete_ocr_cannot_claim_full_regression(monkeypatch):
    from scripts import evaluate_ocr
    monkeypatch.setattr(evaluate_ocr, 'evaluate', lambda root: {'passed': True, 'cases': [{'case': 'blank'}]})
    report = gate.evaluate(with_ocr=True)
    assert report['native_passed'] and not report['legacy_scope_complete']['ocr']
    assert not report['full_regression_passed']


def test_reviewed_truth_must_equal_the_truth_actually_evaluated(tmp_path):
    generate(tmp_path / 'package')
    path = tmp_path / 'package/cases/loan_clean/ground_truth.json'
    data = json.loads(path.read_text()); data['expected_status'] = 'review'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='ground truth differs'):
        gate.evaluate(package_root=tmp_path)
