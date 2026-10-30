"""Strict table layouts with explicit headers, linked continuations and provenance.

Unknown column meanings are never inferred. Dates support ISO or English named
months; ambiguous slash dates remain unsupported.
"""
import re
from datetime import date
from .core import AMOUNT,money

MONTHS={month:index for index,month in enumerate(('jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'),1)}

def statement_date(value):
    try:return date.fromisoformat(value).isoformat()
    except ValueError:
        match=re.fullmatch(r'(\d{1,2}) ([A-Za-z]{3}) (\d{4})',value)
        if not match:raise ValueError('Unsupported statement date')
        return date(int(match[3]),MONTHS[match[2].lower()],int(match[1])).isoformat()

def augment(doc,result):
    mode=None;order=None;pending=None;recognized=set();carries=[]
    issues=doc.setdefault('issues',[]);seen={};conflicted=set()
    def issue(kind,message,source,related=None):
        item={'type':kind,'message':message,'source':source}
        if related:item['sources']=[related,source]
        if item not in issues:issues.append(item)
    def assign(field,value,line,source_field=None):
        if field in conflicted:return
        if field in seen and seen[field][0]!=value:
            issue('conflicting_field','Conflicting explicitly stated metadata or totals require review.',line['id'],seen[field][1])
            result[field]=None;conflicted.add(field)
            if source_field:result[source_field]=None
        else:
            result[field]=value;seen.setdefault(field,(value,line['id']))
            if source_field:result[source_field]=line['id']
    def unfinished():
        nonlocal pending
        if pending:issue('partial_extraction','A split table row has no unambiguous linked continuation.',pending['line']['id']);pending=None
    for line in doc['lines']:
        text=re.sub(r'^L\d+\s+','',' '.join(line['text'].split()));source=line['id']
        if re.match(r'^(?:NOTE|SYSTEM|ASSISTANT|USER|DEVELOPER|INSTRUCTION):',text,re.I):continue
        if re.fullmatch(r'Page\s+\d+(?:\s+(?:of|/)\s*\d+)?',text,re.I):continue
        metadata=False
        match=re.fullmatch(r'(?:Document:\s*[\w-]+\s*\|\s*)?(?:Loan|Account)(?: number| no\.?| id)?:\s*([\w-]+)(?:\s*(?:\|\s*)?Currency:\s*([A-Z]{3}))?',text,re.I)
        if match:
            assign('loan_id',match[1],line);metadata=True
            if match[2]:assign('currency',match[2].upper(),line)
        match=re.fullmatch(r'(?:Currency|Statement currency):?\s*([A-Z]{3})',text,re.I)
        if match:assign('currency',match[1].upper(),line);metadata=True
        match=re.fullmatch(r'(?:Statement date|Statement period end|Period end|As of):\s*(.+)',text,re.I)
        if match:
            try:assign('period_end',statement_date(match[1]),line)
            except (ValueError,KeyError):issue('unsupported_date','Statement date is invalid or ambiguous; review required.',source)
            metadata=True
        match=re.fullmatch(r'(?:Total principal and interest|Principal and interest total|Stated principal plus interest total):?\s*'+AMOUNT,text,re.I)
        if match:assign('stated_total',format(money(match[1]),'.2f'),line,'total_source');metadata=True;unfinished();mode=None
        for field in ('opening','closing'):
            match=re.fullmatch(field+r'(?: ledger)? balance:\s*'+AMOUNT,text,re.I)
            if match:
                assign(field+'_balance',format(money(match[1]),'.2f'),line,field+'_source');metadata=True
                if field=='closing':mode=None
        match=re.fullmatch(r'(?:Balance brought forward|Balance carried forward):\s*'+AMOUNT,text,re.I)
        if match:carries.append({'amount':format(money(match[1]),'.2f'),'source':source});metadata=True
        if metadata:continue
        normalized=text.lower().replace('|',' ')
        normalized=' '.join(normalized.split())
        if re.fullmatch(r'(?:tranche|facility) (?:outstanding )?principal (?:accrued )?interest',normalized):
            mode='loan';order=('principal','interest');recognized.add('loan_columns_v1');continue
        if re.fullmatch(r'(?:tranche|facility) (?:accrued )?interest (?:outstanding )?principal',normalized):
            mode='loan';order=('interest','principal');recognized.add('loan_columns_v1');continue
        if normalized in ('date reference amount','date transaction amount'):
            mode='bank_signed';recognized.add('bank_signed_columns_v1');continue
        if normalized in ('date reference debit credit','date reference credit debit'):
            mode='bank_columns';order=tuple(normalized.split()[-2:]);recognized.add('bank_debit_credit_v1');continue
        if mode=='loan':
            match=re.fullmatch(r'([\w-]+)\s+'+AMOUNT+r'\s+'+AMOUNT,text)
            if match:
                unfinished()
                doc_row={'id':match[1],order[0]:format(money(match[2]),'.2f'),order[1]:format(money(match[3]),'.2f'),'source':source}
                result['tranches'].append(doc_row);continue
            match=re.fullmatch(r'([\w-]+)\s+\(continued\)\s+'+AMOUNT,text,re.I)
            if match:
                if not pending or match[1]!=pending['id'] or order!=pending['order']:
                    issue('partial_extraction','A continuation does not match an unambiguous preceding table row.',source)
                else:
                    first=pending['line']['id'];fields={order[0]:pending['value'],order[1]:format(money(match[2]),'.2f')}
                    result['tranches'].append({'id':match[1],**fields,'source':first,order[0]+'_source':first,order[1]+'_source':source})
                    recognized.add('loan_linked_continuation_v1');pending=None
                continue
            match=re.fullmatch(r'([\w-]+)\s+'+AMOUNT,text)
            if match:
                unfinished();pending={'id':match[1],'value':format(money(match[2]),'.2f'),'line':line,'order':order};continue
        if mode in ('bank_signed','bank_columns'):
            pattern=r'(\d{4}-\d{2}-\d{2})\s+([\w-]+)\s+'+AMOUNT+(r'\s+'+AMOUNT if mode=='bank_columns' else '')
            match=re.fullmatch(pattern,text)
            if match:
                try:day=date.fromisoformat(match[1]).isoformat()
                except ValueError:issue('partial_extraction','Transaction date is invalid; review required.',source);continue
                amount=money(match[3])
                if mode=='bank_columns':
                    sides={order[0]:amount,order[1]:money(match[4])}
                    if any(value<0 for value in sides.values()) or all(value!=0 for value in sides.values()):
                        issue('ambiguous_transaction','Debit/credit row has ambiguous signs; review required.',source);continue
                    amount=sides['credit']-sides['debit']
                result['transactions'].append({'id':match[2],'date':day,'amount':format(amount,'.2f'),'source':source});continue
        # Numeric-looking malformed rows inside a recognized table cannot disappear.
        numeric_row=bool(re.search(AMOUNT,text) or re.match(r'^\d{4}-\d{2}-\d{2}\b',text) or re.match(r'^[\w-]+\s+[-+($]?\d',text))
        if mode and numeric_row and not re.match(r'^(?:Tranche\s+[\w-]+\s*\||Transaction\s+[\w-]+\s*\|)',text,re.I):
            issue('partial_extraction','A numeric table row could not be fully grounded; review required.',source)
    unfinished()
    positions={line['id']:index for index,line in enumerate(doc['lines'])}
    result['transactions'].sort(key=lambda row:positions.get(row['source'],-1))
    result['tranches'].sort(key=lambda row:positions.get(row['source'],-1))
    if carries:
        for carry in carries:carry['after_transaction_count']=sum(positions[t['source']]<positions[carry['source']] for t in result['transactions'])
        result['carried_balances']=carries
    if recognized:doc['layouts']=sorted(recognized)
    return result
