"""Redacted financial facts CSV and a neutral accounting transaction worksheet."""
import csv
import io
from .core import money
from .privacy import report_for_export


def cell(value, numeric=False):
    if value is None:return ''
    value=str(value)
    if numeric:
        return format(money(value),'.2f')
    # CSV quoting alone does not prevent spreadsheet formula execution.
    if value.lstrip(' \t\r\n').startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')):
        return "'"+value
    return value


def csv_report(report, accounting=False):
    report=report_for_export(report);out=io.StringIO(newline='')
    fields=(['date','reference','amount','currency','document_id','source_id','case_id','report_version','review_required'] if accounting else
            ['record_type','case_id','report_version','document_id','period_end','currency','item_id','date','field','amount',
             'computed','stated','difference','severity','human_decision','source_ids','description'])
    writer=csv.DictWriter(out,fieldnames=fields,lineterminator='\r\n');writer.writeheader()
    def write(**row):
        writer.writerow({k:cell(row.get(k),numeric=k in ('amount','computed','stated','difference')) for k in fields})
    for doc in report['documents']:
        s=doc['statement'];base={'case_id':report['id'],'report_version':report.get('report_version',0),
                               'document_id':doc['id'],'period_end':s.get('period_end'),'currency':s.get('currency')}
        for tx in s.get('transactions',[]):
            if accounting:
                write(**{k:v for k,v in base.items() if k in fields},date=tx['date'],reference=tx['id'],amount=tx['amount'],source_id=tx['source'],review_required='yes')
            else:write(**base,record_type='transaction',item_id=tx['id'],date=tx['date'],field='signed_amount',amount=tx['amount'],source_ids=tx['source'])
        if accounting:continue
        for row in s.get('tranches',[]):
            for field in ('principal','interest'):
                write(**base,record_type='tranche',item_id=row['id'],field=field,amount=row[field],source_ids=row.get(field+'_source') or row['source'])
        for field,source in [('stated_total','total_source'),('opening_balance','opening_source'),('closing_balance','closing_source')]:
            if s.get(field) is not None:write(**base,record_type='statement',field=field,amount=s[field],source_ids=s.get(source))
    if not accounting:
        by_id={d['id']:d['statement'] for d in report['documents']}
        for c in report['calculations']:
            statement=by_id[c['document']]
            write(record_type='calculation',case_id=report['id'],report_version=report.get('report_version',0),document_id=c['document'],
                  currency=statement.get('currency'),period_end=statement.get('period_end'),
                  computed=c['computed'],stated=c['stated'],source_ids=';'.join(c['sources']),severity='review' if c.get('provisional') else '',
                  description=' + '.join(c['operands']))
        for f in report['findings']:
            statements=[d['statement'] for d in report['documents'] if set(f['sources']) & {l['id'] for l in d['lines']}]
            currencies={s.get('currency') for s in statements};periods={s.get('period_end') for s in statements}
            write(record_type='finding',case_id=report['id'],report_version=report.get('report_version',0),item_id=f['id'],
                  currency=next(iter(currencies)) if len(currencies)==1 else None,
                  period_end=next(iter(periods)) if len(periods)==1 else None,
                  field=f.get('field'),computed=f.get('computed'),stated=f.get('stated'),difference=f.get('difference'),severity=f['severity'],
                  human_decision=f.get('human_review',{}).get('decision','pending'),source_ids=';'.join(f['sources']),description=f['message'])
    return '\ufeff'+out.getvalue()
