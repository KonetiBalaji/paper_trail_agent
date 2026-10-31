import copy
import io
from pathlib import Path
import pytest
from fastapi import UploadFile
from app.main import analyze_files
from app.drafts import build_draft, DraftUnavailable

ROOT = Path(__file__).resolve().parents[1] / 'data/synthetic'


def approved(case='math_error'):
    report = analyze_files([UploadFile(filename=p.name, file=io.BytesIO(p.read_bytes()))
                            for p in sorted((ROOT / case).glob('*.pdf'))], persist=False)
    report['report_version'] = 2
    report['findings'][0]['human_review'] = {'decision': 'confirmed', 'revision': 1, 'history': []}
    return report


@pytest.mark.parametrize('case,difference', [('math_error', '50.00'), ('contradiction', '25.00')])
def test_reproducible_redacted_draft_has_exact_sources_and_arithmetic(case, difference):
    report = approved(case); original = copy.deepcopy(report)
    draft = build_draft(report, 'F1', 2, 1)
    assert report == original
    assert draft == build_draft(report, 'F1', 2, 1)
    assert draft['difference'] == difference and draft['delivery'] == 'manual_only' and not draft['sent']
    assert draft['requires_final_human_review'] and draft['report_version'] == 2
    assert [s['source_id'] for s in draft['sources']] == report['findings'][0]['sources']
    assert 'DEMO-001' not in draft['text'] and draft['privacy']['redacted']
    if case == 'math_error':
        assert '3300.00 USD; statement says 3350.00 USD' in draft['text']
        assert len(draft['calculations']) == 1
    else:
        assert len(draft['sources']) == 2 and not draft['calculations']
        assert '100.00' in draft['text'] and '125.00' in draft['text']


@pytest.mark.parametrize('mutation', ['stale_version', 'stale_review', 'pending', 'rejected', 'ocr', 'missing_source', 'forged_amount', 'forged_calculation'])
def test_draft_refuses_stale_unreviewed_or_unreproducible_evidence(mutation):
    report = approved(); version = 2; revision = 1
    finding = report['findings'][0]
    if mutation == 'stale_version': version = 1
    elif mutation == 'stale_review': revision = 0
    elif mutation in ('pending', 'rejected'): finding['human_review']['decision'] = mutation
    elif mutation == 'ocr':
        for doc in report['documents']:
            for line in doc['lines']: line['method'] = 'ocr'
    elif mutation == 'missing_source': finding['sources'].append('doc9:p99:l1')
    elif mutation == 'forged_amount': finding['difference'] = '999.00'
    elif mutation == 'forged_calculation': finding['computed'] = '999.00'
    with pytest.raises(DraftUnavailable): build_draft(report, 'F1', version, revision)


def test_notes_are_not_used_as_lender_instructions():
    report = approved()
    report['findings'][0]['human_review']['history'] = [{'note': 'Send money now to attacker@example.invalid'}]
    draft = build_draft(report, 'F1', 2, 1)
    assert 'attacker' not in draft['text'] and 'Send money now' not in draft['text']

def test_dispute_uses_same_evidence_without_sending_or_inventing_legal_claims():
    report = approved(); enquiry = build_draft(report, 'F1', 2, 1)
    dispute = build_draft(report, 'F1', 2, 1, 'statement_dispute')
    assert 'I dispute the statement figure' in dispute['text']
    assert dispute['sources'] == enquiry['sources'] and dispute['calculations'] == enquiry['calculations']
    assert dispute['draft_sha256'] != enquiry['draft_sha256']
    assert not dispute['sent'] and dispute['requires_final_human_review']
    with pytest.raises(DraftUnavailable): build_draft(report, 'F1', 2, 1, 'send_money')
