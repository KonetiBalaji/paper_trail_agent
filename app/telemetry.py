"""Reported provider usage and measured analysis latency; no invented billing."""
import os
from decimal import Decimal,InvalidOperation

def usage(trace,elapsed_ms):
    attempted=[event for event in trace if event['kind']=='model']
    calls=[event for event in attempted if event.get('validation')=='passed']
    measured=[event['output']['usage'] for event in calls if event.get('output',{}).get('usage') is not None]
    keys=('prompt_tokens','completion_tokens','total_tokens')
    coverage={key:sum(key in row for row in measured) for key in keys}
    tokens={key:sum(row[key] for row in measured if key in row) if coverage[key] else None for key in keys}
    complete=bool(calls) and len(measured)==len(attempted) and all('prompt_tokens' in row and 'completion_tokens' in row for row in measured)
    estimate=None
    if complete:
        try:
            incoming=Decimal(os.environ['META_INPUT_USD_PER_MILLION']);outgoing=Decimal(os.environ['META_OUTPUT_USD_PER_MILLION'])
            if not incoming.is_finite() or not outgoing.is_finite() or min(incoming,outgoing)<0:raise ValueError()
            estimate=format((incoming*tokens['prompt_tokens']+outgoing*tokens['completion_tokens'])/Decimal(1000000),'.8f')
        except (KeyError,InvalidOperation,ValueError):pass
    return {'analysis_ms':round(elapsed_ms,2),'attempted_model_calls':len(attempted),'successful_model_calls':len(calls),'calls_with_reported_usage':len(measured),
        'provider_usage_complete':complete,'reported_tokens':tokens if measured else None,'token_coverage':coverage,
        'estimated_cost_usd':estimate,'cost_basis':'configured USD-per-million token rates; estimate, not an invoice' if estimate else 'unmeasured or rates not configured'}
