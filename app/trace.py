"""Case-local execution events, excluding API headers and hidden model reasoning."""
from datetime import datetime, timezone
from .privacy import redact

def record(trace, kind, name, inputs=None, output=None, validation='passed', duration_ms=None, **context):
    event={'id':f'E{len(trace)+1}','timestamp':datetime.now(timezone.utc).isoformat(),
           'kind':kind,'name':name,'input':inputs,'output':output,'validation':validation,
           'duration_ms':round(duration_ms,2) if duration_ms is not None else None,**context}
    event=redact(event)
    trace.append(event)
    return event
