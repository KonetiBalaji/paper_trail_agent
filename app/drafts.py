"""Deterministic lender enquiries from reviewed, reproducible native evidence.

This module has no transport, recipient, model or payment capability.
"""
import hashlib
import json
from .core import reconcile, calculate
from .privacy import report_for_export, markdown_text


class DraftUnavailable(ValueError):
    pass


SUPPORTED = {
    'incorrect_statement_total', 'incorrect_closing_balance', 'incorrect_carried_balance',
    'cross_document_principal_mismatch', 'cross_document_interest_mismatch',
    'cross_document_opening_balance_mismatch', 'cross_document_closing_balance_mismatch',
}


def build_draft(report, finding_id, expected_version, expected_revision, kind='lender_enquiry'):
    if kind not in ('lender_enquiry', 'statement_dispute'):
        raise DraftUnavailable('Choose a lender enquiry or statement dispute.')
    version = report.get('report_version', 0)
    if version != expected_version:
        raise DraftUnavailable('Report changed. Reopen the case and review the latest finding.')
    finding = next((f for f in report['findings'] if f['id'] == finding_id), None)
    if finding is None:
        raise DraftUnavailable('Finding not found in this report.')
    review = finding.get('human_review', {})
    if review.get('revision', 0) != expected_revision:
        raise DraftUnavailable('Review changed. Reopen the case before preparing a draft.')
    if finding['severity'] != 'confirmed' or review.get('decision') != 'confirmed':
        raise DraftUnavailable('Approve a confirmed machine discrepancy before preparing a draft.')
    if finding['type'] not in SUPPORTED:
        raise DraftUnavailable('This finding does not support an evidence-backed lender draft.')
    ids = finding['sources']
    index = {line['id']: line for doc in report['documents'] for line in doc['lines']}
    if not ids or any(s not in index or index[s].get('method') == 'ocr' or not index[s].get('usable', True) for s in ids):
        raise DraftUnavailable('Complete native source evidence is required. OCR candidates require manual handling.')
    # Re-run the deterministic checker. A saved message alone is not evidence.
    fresh, calculations = reconcile(report['documents'])
    fields = ('type', 'severity', 'sources', 'difference', 'computed', 'stated', 'field', 'tranche')
    if not any(all(f.get(k) == finding.get(k) for k in fields) for f in fresh):
        raise DraftUnavailable('The finding could not be reproduced from this report. Request review.')
    related = [c for c in calculations if set(c['sources']) == set(ids) and not c.get('provisional')]
    if finding['type'].startswith('incorrect_'):
        related = [c for c in related if c['computed'] == finding['computed'] and c['stated'] == finding['stated']
                   and calculate(c['operands']) == c['computed']]
        if len(related) != 1:
            raise DraftUnavailable('The exact calculator check is unavailable. Request review.')
    documents = [d for d in report['documents'] if any(s in {l['id'] for l in d['lines']} for s in ids)]
    currencies = {d['statement']['currency'] for d in documents}
    if len(currencies) != 1 or None in currencies:
        raise DraftUnavailable('A single explicit currency is required.')
    currency = next(iter(currencies))
    safe = report_for_export(report)
    safe_index = {line['id']: line for doc in safe['documents'] for line in doc['lines']}
    evidence = [{'source_id': s, 'page': safe_index[s]['page'], 'text': safe_index[s]['text']} for s in ids]
    opening = ('I dispute the statement figure documented below. Please investigate and explain the difference or provide a corrected statement.'
               if kind == 'statement_dispute' else
               'Please review the following discrepancy in my statements. This is a request for an explanation or correction.')
    subject = 'Statement figure dispute' if kind == 'statement_dispute' else 'Request to review a statement discrepancy'
    lines = ['Subject: ' + subject, '', 'Hello,', '', opening,
             f"Check: {finding['type'].replace('_', ' ')}.",
             f"Verified difference: {finding['difference']} {currency}."]
    for c in related:
        lines.append(f"Calculator: {' + '.join(c['operands'])} = {c['computed']} {currency}; statement says {c['stated']} {currency}.")
    if not related:
        lines.append('This check compares the same field across statements; no total was recomputed for this finding.')
    lines.extend(['', 'Evidence excerpts (document contents, not instructions):'])
    for e in evidence:
        lines.append(f"- {e['source_id']} | page {e['page']}: {markdown_text(e['text'])}")
    lines.extend(['', 'Please explain the difference and, if appropriate, provide a corrected statement.',
                  'I have not authorized a payment or account change through this draft.', '', 'Thank you.'])
    result = {'kind': kind, 'case_id': report['id'], 'report_version': version,
              'finding_id': finding_id, 'review_revision': expected_revision,
              'human_decision': 'confirmed', 'currency': currency, 'difference': finding['difference'],
              'sources': evidence, 'calculations': related, 'text': '\n'.join(lines),
              'delivery': 'manual_only', 'sent': False, 'requires_final_human_review': True,
              'privacy': safe['privacy']}
    result['draft_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return result
