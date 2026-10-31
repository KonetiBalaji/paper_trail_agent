import asyncio
import json
from types import SimpleNamespace
from pathlib import Path
import sys
import pytest
from app import meta
from app.mcp_client import CaseTools,MCPTransportError
from app.mcp_server import evidence_bundle,load_evidence
from test_core import documents
from test_service import service


def test_case_bundle_is_redacted_and_rejects_duplicate_or_oversized_evidence(tmp_path):
    docs=documents('clean');bundle=evidence_bundle(docs)
    assert 'DEMO-001' not in json.dumps(bundle) and '1000.00' in json.dumps(bundle)
    assert all(set(line)=={'id','text','page','line'} for line in bundle['lines'])
    with pytest.raises(ValueError):evidence_bundle([docs[0],docs[0]])
    path=tmp_path/'case.json';path.write_text(json.dumps(bundle))
    assert load_evidence(path)[0]['lines']==bundle['lines']
    path.write_bytes(b'x'*(2*1024*1024+1))
    with pytest.raises(ValueError):load_evidence(path)


def test_meta_invokes_real_mcp_and_keeps_server_log(monkeypatch):
    docs=documents('clean');source=docs[0]['statement']['tranches'][0]['source']
    messages=iter([
        {'role':'assistant','tool_calls':[{'id':'s','function':{'name':'search_evidence','arguments':'{"query":"T1 principal"}'}},
                                         {'id':'c','function':{'name':'calculator','arguments':'{"values":["1000.00","100.00"]}'}}]},
        {'content':json.dumps({'summary':'Reviewed calculator and evidence.','checklist':[],'sources':[source]})}])
    def request(messages,tools):
        assert {t['function']['name'] for t in tools}=={'search_evidence','calculator'}
        assert all(t['function']['parameters']['additionalProperties'] is False for t in tools)
        return next(replies)
    replies=messages;monkeypatch.setattr(meta,'request',request)
    result=meta.reason(docs,[],[])
    assert result['mcp']['transport']=='mcp_stdio' and result['mcp']['protocol_version']=='2026-07-28'
    assert len(result['mcp']['server_call_log'])==2
    assert result['mcp']['server_call_log'][1]['output']=={'sum':'1100.00'}
    assert all(t['transport']=='mcp_stdio' and t['mcp_sequence']==i for i,t in enumerate(result['tool_trace'],1))
    assert 'DEMO-001' not in json.dumps(result['mcp'])


def test_mcp_connection_failure_never_falls_back_to_local_tools(monkeypatch):
    async def fail(*args):raise MCPTransportError('Unavailable')
    def forbidden(*args):raise AssertionError('Provider must not run without MCP')
    monkeypatch.setattr(CaseTools,'__aenter__',fail);monkeypatch.setattr(meta,'request',forbidden)
    with pytest.raises(meta.MetaError,match='MCP'):meta.reason(documents('clean'),[],[])


def test_invalid_server_output_fails_closed():
    class Peer:
        async def call_tool(self,*args,**kwargs):return SimpleNamespace(meta={'paper_trail_sequence':1},is_error=False,structured_content={'sum':999})
    session=CaseTools([]);session._client=Peer()
    with pytest.raises(MCPTransportError):asyncio.run(session.call('calculator',{'values':['1.00']}))


def test_standard_host_can_restart_server_with_default_stderr_audit(tmp_path):
    from mcp import Client,StdioServerParameters,stdio_client
    import mcp
    evidence=tmp_path/'case.json';evidence.write_text(json.dumps(evidence_bundle(documents('clean'))))
    params=StdioServerParameters(command=sys.executable,args=['-m','app.mcp_server','--evidence',str(evidence)],
        cwd=str(Path(__file__).resolve().parents[1]),env={'PYTHONPATH':str(Path(mcp.__file__).resolve().parent.parent),'OTEL_SDK_DISABLED':'true'})
    async def restart():
        for n in range(2):
            with (tmp_path/f'audit{n}.jsonl').open('w',encoding='utf-8') as log:
                async with Client(stdio_client(params,errlog=log),cache=None) as client:
                    result=await client.call_tool('calculator',{'values':['0.10','0.20']})
                    assert not result.is_error and result.structured_content=={'sum':'0.30'}
            rows=[json.loads(l) for l in (tmp_path/f'audit{n}.jsonl').read_text().splitlines() if l.startswith('{')]
            assert len(rows)==1 and rows[0]['sequence']==1 and rows[0]['output']=={'sum':'0.30'}
    asyncio.run(restart())


def test_public_mcp_check_is_fixed_csrf_protected_and_rate_limited(service,monkeypatch):
    client,_,_=service
    def forbidden(*args):raise AssertionError('Synthetic MCP demo must never call a model')
    monkeypatch.setattr(meta,'request',forbidden)
    assert client.post('/api/platform/demo/mcp-check').status_code==401
    assert client.post('/api/platform/demo/start').status_code==200
    assert client.post('/api/platform/demo/mcp-check').status_code==403
    headers={'X-CSRF-Token':client.cookies['pta_csrf']}
    for _ in range(4):
        response=client.post('/api/platform/demo/mcp-check',headers=headers)
        assert response.status_code==200,response.text
        result=response.json();assert result['passed'] and result['model_calls']==0 and len(result['mcp']['server_call_log'])==2
    assert client.post('/api/platform/demo/mcp-check',headers=headers).status_code==429
