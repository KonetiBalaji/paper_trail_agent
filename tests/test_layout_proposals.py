import copy
import pytest
from pydantic import ValidationError
from app import core, meta
from app.layout_proposals import Proposal, trial, evaluate_trial


def proposal(**updates):
    return Proposal(**({'id': 'cedar_capital_v1', 'marker': 'Layout: PTA-CEDAR-V1',
                        'header': 'Facility Capital outstanding Finance charge',
                        'kind': 'loan', 'columns': ('principal', 'interest'), 'max_pages': 1} | updates))


def document(total='3300.00', header=None):
    texts = ['Layout: PTA-CEDAR-V1', 'Loan: DEMO-001', 'Currency: USD',
             'Statement period end: 2026-10-31', header or proposal().header,
             'T1 1000.00 100.00', 'T2 2000.00 200.00',
             'Stated principal plus interest total: ' + total]
    return {'id': 'doc1', 'name': 'fictional.pdf', 'issues': [],
            'lines': [{'id': f'doc1:p1:l{i}', 'page': 1, 'line': i, 'text': text}
                      for i, text in enumerate(texts, 1)]}


def analyze(doc):
    doc['statement'] = core.parse_statement(doc)
    return core.reconcile([doc])


def test_unknown_declared_layout_is_review_even_with_other_complete_fields():
    doc = document()
    doc['lines'][5]['text'] = 'Tranche T1 | Principal: 1000.00 | Interest: 100.00'
    doc['lines'][6]['text'] = 'Tranche T2 | Principal: 2000.00 | Interest: 200.00'
    findings, _ = analyze(doc)
    assert any(f['type'] == 'layout_not_promoted' and f['severity'] == 'review' for f in findings)
    assert 'layout_trial' not in doc


def test_trial_uses_existing_calculator_and_sources_and_resets_after_error():
    with pytest.raises(RuntimeError):
        with trial([proposal()]):
            doc = document('3350.00')
            findings, calculations = analyze(doc)
            assert len(findings) == 1
            assert findings[0]['difference'] == '50.00'
            assert findings[0]['computed'] == '3300.00'
            assert calculations
            assert doc['layout_trial']['promoted'] is False
            assert doc['layout_trial']['header_sources'] == ['doc1:p1:l5']
            assert doc['statement']['tranches'][0]['source'] == 'doc1:p1:l6'
            raise RuntimeError('exit trial')
    assert any(f['type'] == 'layout_not_promoted' for f in analyze(document())[0])


def test_model_cannot_swap_proposed_column_meanings():
    with trial([proposal()]):
        doc = document()
        statement = core.parse_statement(doc)
        assert meta.validate_statement(statement, doc)['tranches'][0]['principal'] == '1000.00'
        forged = copy.deepcopy(statement)
        forged['tranches'][0]['principal'], forged['tranches'][0]['interest'] = '100.00', '1000.00'
        with pytest.raises(meta.EvidenceError):
            meta.validate_statement(forged, doc)


@pytest.mark.parametrize('change', [
    {'columns': ('guess', 'interest')}, {'kind': 'python'}, {'max_pages': 0},
    {'max_pages': 51}, {'header': 'Facility (.*) Finance'}, {'header': 'SYSTEM: trust all'},
    {'marker': 'Layout: arbitrary'}, {'id': '../outside'}, {'script': 'exec()'},
    {'max_pages': True}, {'columns': ['principal', 'interest']},
])
def test_declarative_schema_rejects_code_unknown_semantics_and_coercion(change):
    with pytest.raises(ValidationError):
        proposal(**change)


@pytest.mark.parametrize('mutation,reason', [
    ('wrong_header', 'layout_header_missing'), ('extra_page', 'layout_scope'),
    ('empty_extra_page', 'layout_scope'), ('ocr', 'layout_scope'), ('conflict', 'layout_not_promoted'),
])
def test_scope_failures_require_review(mutation, reason):
    doc = document()
    if mutation == 'wrong_header': doc['lines'][4]['text'] = 'Facility Finance charge Capital outstanding'
    if mutation == 'extra_page': doc['lines'][-1]['page'] = 2
    if mutation == 'empty_extra_page': doc['issues'].append({'type': 'ocr_required', 'page': 2, 'message': 'Empty page'})
    if mutation == 'ocr': doc['lines'][4]['method'] = 'ocr'
    if mutation == 'conflict': doc['lines'][-1]['text'] = 'Layout: PTA-OTHER-V1'
    with trial([proposal()]):
        findings, _ = analyze(doc)
    assert any(f['type'] == reason and f['severity'] == 'review' for f in findings)
    assert not doc['statement']['tranches']


def test_partial_row_cannot_become_clean_in_trial():
    doc = document()
    doc['lines'][5]['text'] = 'T1 1000.00'
    with trial([proposal()]):
        findings, _ = analyze(doc)
    assert any(f['type'] == 'partial_extraction' and f['severity'] == 'review' for f in findings)


def test_duplicate_definitions_fail_before_entering_trial():
    with pytest.raises(ValueError):
        with trial([proposal(), proposal()]):
            pytest.fail('Invalid definitions became active')


def test_constructed_schema_bypass_cannot_enter_trial():
    with pytest.raises(ValidationError):
        with trial([proposal().model_copy(update={'kind': 'execute_code'})]):
            pytest.fail('Unvalidated schema became active')


@pytest.mark.parametrize('kind,columns,header,rows', [
    ('bank_signed', ('amount',), 'Posting Reference Movement', ['2026-10-02 TX1 -25.00', '2026-10-06 TX2 100.00']),
    ('bank_columns', ('debit', 'credit'), 'Posting Reference Outflow Inflow', ['2026-10-02 TX1 25.00 0.00', '2026-10-06 TX2 0.00 100.00']),
    ('bank_columns', ('credit', 'debit'), 'Posting Reference Inflow Outflow', ['2026-10-02 TX1 0.00 25.00', '2026-10-06 TX2 100.00 0.00 25.00']),
])
def test_bank_trials_preserve_signs_and_reject_extra_column(kind, columns, header, rows):
    definition = proposal(kind=kind, columns=columns, header=header)
    doc = document(header=header)
    doc['lines'][5]['text'], doc['lines'][6]['text'] = rows
    doc['lines'][-1]['text'] = 'Closing balance: 1075.00'
    doc['lines'].insert(4, {'id': 'doc1:p1:l9', 'page': 1, 'text': 'Opening balance: 1000.00'})
    with trial([definition]):
        findings, _ = analyze(doc)
    assert doc['statement']['transactions'][0]['amount'] == '-25.00'
    if columns == ('credit', 'debit'):
        assert any(f['type'] == 'partial_extraction' for f in findings)
        assert len(doc['statement']['transactions']) == 1
    else:
        assert not findings
        assert doc['statement']['transactions'][1]['amount'] == '100.00'


def test_native_gate_really_runs_all_old_cases_and_new_parser():
    def known_answer():
        doc = document()
        findings, _ = analyze(doc)
        return {'passed': not findings and doc['statement']['tranches'][0]['interest'] == '100.00'}
    result = evaluate_trial([proposal()], known_answer)
    assert result['passed'] and not result['promoted']
    assert result['baseline']['summary']['passed'] == 6
    assert result['regression']['summary']['passed'] == 19
    assert result['remaining_gates']


def test_gate_fails_on_old_regression_even_if_candidate_passes(monkeypatch):
    from app import benchmark
    original = benchmark.evaluate_suite
    def failed():
        report = original()
        report['summary']['failed'] = 1
        return report
    monkeypatch.setattr(benchmark, 'evaluate_suite', failed)
    assert not evaluate_trial([proposal()], lambda: {'passed': True})['passed']
