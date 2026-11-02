"""Operator-only trials of literal column mappings; never runtime auto-learning.

Only a validated deployment receipt can supply runtime definitions. There is no
HTTP write route, environment switch or promotion by document content.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator


def normalize(value):
    return ' '.join(value.lower().replace('|', ' ').split())


class Proposal(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{2,47}$')
    marker: str = Field(pattern=r'^Layout: PTA-[A-Z0-9-]{3,64}$')
    header: str = Field(min_length=5, max_length=120)
    kind: str
    columns: tuple[str, ...]
    max_pages: int = Field(ge=1, le=50)

    @model_validator(mode='after')
    def literal_mapping(self):
        allowed = {'loan': {('principal', 'interest'), ('interest', 'principal')},
                   'bank_signed': {('amount',)},
                   'bank_columns': {('debit', 'credit'), ('credit', 'debit')}}
        if self.kind not in allowed or self.columns not in allowed[self.kind]:
            raise ValueError('Only existing deterministic column semantics are allowed')
        if not re.fullmatch(r'[A-Za-z][A-Za-z |]{3,119}', self.header):
            raise ValueError('A header must be literal English column labels, not a pattern or instruction')
        return self

    def fingerprint(self):
        raw = json.dumps(self.model_dump(mode='json'), sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(raw.encode()).hexdigest()


_trial = ContextVar('paper_trail_layout_trial', default=())


@contextmanager
def trial(proposals):
    """Local evaluation scope, reset on errors; never derive definitions from PDFs."""
    proposals = tuple(proposals)
    if not proposals or len(proposals) > 32 or any(not isinstance(p, Proposal) for p in proposals):
        raise ValueError('Supply 1 to 32 validated proposals')
    # Revalidate even model_construct/model_copy instances supplied by tooling.
    proposals = tuple(Proposal.model_validate_json(p.model_dump_json()) for p in proposals)
    for key in ('id', 'marker'):
        if len({getattr(p, key) for p in proposals}) != len(proposals):
            raise ValueError('Duplicate proposal identity')
    if len({normalize(p.header) for p in proposals}) != len(proposals):
        raise ValueError('Conflicting normalized proposal headers')
    token = _trial.set(proposals)
    try:
        yield
    finally:
        _trial.reset(token)


def document_mapping(doc):
    """Validate scope once per document, before consuming any proposed table row."""
    doc.pop('layout_trial', None)
    doc.pop('layout_support', None)
    entries = [(line, re.sub(r'^L\d+\s+', '', ' '.join(line['text'].split())))
               for line in doc['lines']]
    markers = [(line, text) for line, text in entries if re.match(r'^layout:\s*pta-', text, re.I)]
    if not markers:
        return {}

    def reject(kind, message):
        issue = {'type': kind, 'message': message, 'source': markers[0][0]['id']}
        if issue not in doc.setdefault('issues', []):
            doc['issues'].append(issue)
        return {}

    values = {text for _, text in markers}
    proposed = _trial.get()
    deployed = None
    if not proposed:
        from .layout_registry import load
        deployed = load()
        proposed = deployed['definitions']
    matches = [p for p in proposed if p.marker in values]
    if len(values) != 1 or len(matches) != 1:
        return reject('layout_not_promoted', 'This declared layout has no approved runtime mapping; review required.')
    proposal = matches[0]
    pages = max([line.get('page', 1) for line in doc['lines']] +
                [issue.get('page', 1) for issue in doc.get('issues', [])] + [1])
    if pages > proposal.max_pages or any(line.get('method') == 'ocr' for line in doc['lines']):
        return reject('layout_scope', 'Layout trial page/OCR scope exceeded; review required.')
    headers = [line for line, text in entries if normalize(text) == normalize(proposal.header)]
    if not headers:
        return reject('layout_header_missing', 'Declared layout lacks its exact reviewed header; review required.')
    evidence = {'id': proposal.id, 'definition_sha256': proposal.fingerprint(),
                           'marker_sources': [line['id'] for line, _ in markers],
                           'header_sources': [line['id'] for line in headers],
                           'promoted': False}
    if deployed is not None:
        doc['layout_support'] = evidence | deployed['provenance'][proposal.id]
    else:
        doc['layout_trial'] = evidence
    return {normalize(proposal.header): proposal}


def evaluate_trial(proposals, evaluate_candidate):
    """Rerun old native cases and candidate truth in the same actual parser scope.

    Not a promotion receipt: OCR, prior promoted packages, deployment freshness
    and mapping review must also pass before a production registry is enabled.
    """
    from . import benchmark, evals
    with trial(proposals):
        baseline = evals.evaluate_suite()
        regression = benchmark.evaluate_suite()
        candidate = evaluate_candidate()
    passed = (baseline['summary']['failed'] == 0 and regression['summary']['failed'] == 0
              and regression['summary']['false_clean_count'] == 0
              and candidate.get('passed') is True)
    return {'passed': passed, 'promoted': False, 'baseline': baseline,
            'regression': regression, 'candidate': candidate,
            'remaining_gates': ['actual OCR regression', 'prior promoted packages',
                                'mapping review', 'source-bound promotion receipt']}
