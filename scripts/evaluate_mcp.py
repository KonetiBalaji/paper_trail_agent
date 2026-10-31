"""Independent official SDK client against actual current/legacy stdio servers."""
import argparse
import asyncio
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mcp import Client,StdioServerParameters,stdio_client
import mcp
from app.core import read_pdf
from app.mcp_server import evidence_bundle

ROOT=Path(__file__).resolve().parents[1]


async def evaluate():
    checks=[];protocols=[]
    def check(name,condition):
        checks.append({'check':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
    with tempfile.TemporaryDirectory(prefix='paper-trail-mcp-eval-') as folder:
        root=Path(folder)
        fixture=ROOT/'data/synthetic/contradiction/statement_A.pdf'
        documents=[read_pdf(fixture.read_bytes(),'fictional.pdf','doc1')]
        bundle=evidence_bundle(documents)
        check('bundle_pattern_redacted','DEMO-001' not in json.dumps(bundle))
        for mode in ('auto','legacy'):
            evidence=root/(mode+'.json');audit=root/(mode+'.jsonl')
            data=bundle if mode=='auto' else {'lines':[{'id':'doc1:p1:l1','text':'CASE_B_ONLY amount 500.00','page':1,'line':1}]}
            evidence.write_text(json.dumps(data),encoding='utf-8')
            params=StdioServerParameters(command=sys.executable,args=['-m','app.mcp_server','--evidence',str(evidence),'--audit-log',str(audit)],cwd=str(ROOT),
                env={'PYTHONPATH':str(Path(mcp.__file__).resolve().parent.parent),'OTEL_SDK_DISABLED':'true','PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'})
            with (root/(mode+'.stderr')).open('w+',encoding='utf-8') as log:
                async with Client(stdio_client(params,errlog=log),mode=mode,read_timeout_seconds=10,cache=None) as client:
                    protocols.append({'mode':mode,'protocol_version':client.protocol_version})
                    check(mode+'_protocol_negotiated',client.protocol_version==('2026-07-28' if mode=='auto' else '2025-11-25'))
                    tools=(await client.list_tools()).tools
                    check(mode+'_two_tools',{t.name for t in tools}=={'search_evidence','calculator'})
                    check(mode+'_strict_schemas',all(t.input_schema.get('additionalProperties') is False and t.output_schema for t in tools))
                    if mode=='auto':
                        search=await client.call_tool('search_evidence',{'query':'T1 principal interest'})
                        check('current_search_grounded',not search.is_error and any('1000.00' in l['text'].replace(',','') for l in search.structured_content['lines']))
                        result=await client.call_tool('calculator',{'values':['1000.00','100.00']})
                        check('current_exact_sum',not result.is_error and result.structured_content=={'sum':'1100.00'})
                        for name,args,label in [('calculator',{'values':['1.00'],'extra':True},'extra_arguments'),('search_evidence',{'query':123},'query_type'),
                                               ('calculator',{'values':['NaN']},'nonfinite'),('calculator',{'values':['0.001']},'subcent'),('read_file',{'path':'.env'},'unknown_tool')]:
                            result=await client.call_tool(name,args)
                            check(label+'_rejected',result.is_error)
                        result=await client.call_tool('search_evidence',{'query':'CASE_B_ONLY'})
                        check('case_b_not_in_case_a',not result.is_error and result.structured_content=={'lines':[]})
                        result=await client.call_tool('calculator',{'values':['1.00']})
                        check('ninth_tool_call_rejected',result.is_error and 'budget' in result.structured_content['error'].lower())
                    else:
                        result=await client.call_tool('search_evidence',{'query':'CASE_B_ONLY'})
                        check('legacy_separate_case',not result.is_error and result.structured_content['lines'][0]['text']=='CASE_B_ONLY amount 500.00')
                        result=await client.call_tool('calculator',{'values':['0.10','0.20']})
                        check('legacy_exact_sum',not result.is_error and result.structured_content=={'sum':'0.30'})
            rows=[json.loads(line) for line in audit.read_text(encoding='utf-8').splitlines()]
            check(mode+'_server_audit_complete',len(rows)==(9 if mode=='auto' else 2) and [r['sequence'] for r in rows]==list(range(1,len(rows)+1)))
            check(mode+'_audit_redacted','DEMO-001' not in json.dumps(rows))
            evidence.unlink();audit.unlink()
            check(mode+'_process_released_files',not evidence.exists() and not audit.exists())
    return {'passed':True,'checked_at':datetime.now(timezone.utc).isoformat(),'sdk':{'mcp':version('mcp'),'mcp-types':version('mcp-types')},
        'scope':'Official SDK clients launch real stdio subprocesses, discover tools and validate current/legacy protocol behavior. Fictional evidence, no model calls, no database, no OS sandbox or remote-host claim.',
        'protocols':protocols,'checks':checks,
        'source_sha256':{p:hashlib.sha256((ROOT/p).read_text(encoding='utf-8').encode()).hexdigest() for p in ('app/mcp_server.py','app/mcp_client.py','app/meta.py','scripts/evaluate_mcp.py')}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',default='work/mcp-results.json');args=parser.parse_args()
    result=asyncio.run(evaluate());output=Path(args.report);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'checks':len(result['checks']),'protocols':result['protocols']}))
