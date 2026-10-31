"""Conservative export/trace redaction, preserving evidence IDs and arithmetic.

This is pattern-based removal, not a claim of universal PII recognition. Original
PDFs and authenticated evidence views remain private, unredacted source records.
"""
import copy
import re
import logging
import os
import traceback
import html

EMAIL=re.compile(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b')
SSN=re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
PHONE=re.compile(r'(?<![\w.])(?:\+1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\w.])')
LABELED=re.compile(r'(?im)\b(borrower(?: name)?|customer(?: name)?|full name|address|email|phone|ssn|social security(?: number)?|account(?: number| no\.?| id)?|loan(?: number| no\.?| id)?|routing(?: number)?|iban)\s*[:=]\s*([^\n|]+)')
SENSITIVE={'loan_id','account_id','account_number','routing_number','iban','borrower','borrower_name','customer_name','full_name','address','email','phone','ssn'}
URL_QUERY=re.compile(r'''(?i)(https?://[^\s?"']+|/[A-Za-z0-9_./%-]+)\?[^\s"']+''')

def text(value):
    value=re.sub(r'pta_api_[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])','[REDACTED_API_KEY]',value)
    value=LABELED.sub(lambda match:match.group(1)+': [REDACTED]',value)
    value=EMAIL.sub('[REDACTED_EMAIL]',value)
    value=SSN.sub('[REDACTED_SSN]',value)
    return PHONE.sub('[REDACTED_PHONE]',value)

def redact(value):
    if isinstance(value,dict):return {key:('[REDACTED]' if key.lower() in SENSITIVE and child not in (None,'') else redact(child)) for key,child in value.items()}
    if isinstance(value,list):return [redact(child) for child in value]
    if isinstance(value,tuple):return [redact(child) for child in value]
    if isinstance(value,str):return text(value)
    return value

def log_text(value):
    value=text(value)
    value=URL_QUERY.sub(lambda match:match.group(1)+'?[REDACTED_QUERY]',value)
    for name in ('MODEL_API_KEY','DATA_ENCRYPTION_KEY','DATABASE_URL','CRON_SECRET'):
        secret=os.getenv(name,'')
        if len(secret)>=8:value=value.replace(secret,'[REDACTED_SECRET]')
    return value

def install_log_redaction():
    """Sanitize before a handler sees a record; preserve access-log arg shape."""
    original=logging.getLogRecordFactory()
    if getattr(original,'paper_trail_redaction',False):return
    def factory(*args,**kwargs):
        event=original(*args,**kwargs)
        def scrub(value):
            if isinstance(value,str):return log_text(value)
            if isinstance(value,tuple):return tuple(scrub(child) for child in value)
            if isinstance(value,dict):return {key:('[REDACTED]' if str(key).lower() in SENSITIVE else scrub(child)) for key,child in value.items()}
            if isinstance(value,list):return [scrub(child) for child in value]
            return value
        event.msg=scrub(event.msg);event.args=scrub(event.args)
        if event.exc_info:
            event.exc_text=log_text(''.join(traceback.format_exception(*event.exc_info)))
            event.exc_info=None
        return event
    factory.paper_trail_redaction=True
    logging.setLogRecordFactory(factory)

def _filenames(value,replacements):
    if isinstance(value,dict):return {key:_filenames(child,replacements) for key,child in value.items()}
    if isinstance(value,list):return [_filenames(child,replacements) for child in value]
    if isinstance(value,str):
        for original,replacement in sorted(replacements.items(),key=lambda pair:-len(pair[0])):
            if original:value=value.replace(original,replacement)
    return value

def private_report_view(report):
    """Redact legacy traces on read, without rewriting immutable report versions."""
    result=copy.deepcopy(report)
    replacements={doc['name']:doc['id']+'.pdf' for doc in report.get('documents',[])}
    for key in ('trace','agent'):
        if key in result:result[key]=redact(_filenames(result[key],replacements))
    return result

def report_for_export(report):
    replacements={doc['name']:doc['id']+'.pdf' for doc in report.get('documents',[])}
    result=redact(_filenames(report,replacements))
    for doc in result.get('documents',[]):doc['name']=doc['id']+'.pdf'
    result['privacy']={'redacted':True,'policy':'pattern-v1','originals_included':False,
        'scope':'Labeled identity/contact fields, emails, US SSNs, formatted US phones, and original filenames. Unlabeled names, addresses and unsupported formats require human review before sharing.'}
    return result

def markdown_text(value):
    """Untrusted evidence and notes remain literal text in Markdown exports."""
    return re.sub(r'([\\`*\[\]!_#|])',r'\\\1',html.escape(str(value),quote=False)).replace('\r','').replace('\n',' ↵ ')
