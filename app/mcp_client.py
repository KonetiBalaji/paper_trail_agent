"""Owned per-case stdio MCP connection, independent of provider credentials."""
import json
import os
from pathlib import Path
import sys
import tempfile
from .mcp_server import evidence_bundle,INPUTS,OUTPUTS


class MCPTransportError(Exception):pass


class CaseTools:
    def __init__(self,documents):
        self.documents=documents;self.metadata={};self._temporary=None;self._client=None;self._log=None;self._entered=False

    async def __aenter__(self):
        from mcp import Client,StdioServerParameters,stdio_client
        import mcp
        self._temporary=tempfile.TemporaryDirectory(prefix='paper-trail-mcp-')
        root=Path(self._temporary.name).resolve();evidence=root/'evidence.json';self.audit=root/'audit.jsonl'
        try:
            raw=json.dumps(evidence_bundle(self.documents),separators=(',',':')).encode()
            if len(raw)>2*1024*1024:raise MCPTransportError('MCP evidence exceeds its case limit; review required.')
            with os.fdopen(os.open(evidence,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as stream:stream.write(raw)
            self._log=open(root/'stderr.log','w+',encoding='utf-8')
            params=StdioServerParameters(command=sys.executable,args=['-m','app.mcp_server','--evidence',str(evidence),'--audit-log',str(self.audit)],
                cwd=str(Path(__file__).resolve().parents[1]),env={'OTEL_SDK_DISABLED':'true','PYTHONDONTWRITEBYTECODE':'1','PYTHONUTF8':'1',
                    'PYTHONPATH':str(Path(mcp.__file__).resolve().parent.parent)})
            self._client=Client(stdio_client(params,errlog=self._log),read_timeout_seconds=15,cache=None)
            await self._client.__aenter__()
            self._entered=True
            listed=await self._client.list_tools()
            if {t.name for t in listed.tools}!=set(INPUTS):raise MCPTransportError('Unexpected MCP tool catalogue')
            tools=[]
            for tool in listed.tools:
                if tool.input_schema!=INPUTS[tool.name].model_json_schema() or tool.output_schema!=OUTPUTS[tool.name].model_json_schema():
                    raise MCPTransportError('MCP tool schema mismatch')
                tools.append({'type':'function','function':{'name':tool.name,'description':tool.description,'parameters':tool.input_schema}})
            self.model_tools=tools
            info=self._client.server_info
            self.metadata={'transport':'mcp_stdio','protocol_version':self._client.protocol_version,
                           'server':{'name':info.name,'version':info.version},
                           'tools':[{'name':t.name,'input_schema':t.input_schema,'output_schema':t.output_schema} for t in listed.tools],
                           'max_calls':8,'redaction':'pattern redaction before transport','server_call_log':[]}
            return self
        except BaseException:
            await self.__aexit__(*sys.exc_info());raise

    async def call(self,name,args):
        # The client validates catalogue/output schemas; the server validates
        # arguments. Source results are
        # confined to the explicitly loaded case, never a storage lookup.
        if not isinstance(args,dict):return {'error':'Invalid tool arguments'},None
        response=await self._client.call_tool(name,args,read_timeout_seconds=10)
        sequence=(response.meta or {}).get('paper_trail_sequence')
        if response.is_error:return {'error':response.structured_content.get('error','MCP tool failed') if response.structured_content else 'MCP tool failed'},sequence
        if name not in OUTPUTS:raise MCPTransportError('Unexpected MCP tool result')
        try:parsed=OUTPUTS[name].model_validate(response.structured_content).model_dump()
        except ValueError as exc:raise MCPTransportError('MCP output schema validation failed') from exc
        return (parsed['lines'] if name=='search_evidence' else parsed),sequence

    async def __aexit__(self,kind,value,traceback):
        try:
            if self._entered:
                await self._client.__aexit__(kind,value,traceback)
            if self.metadata and self.audit.exists():
                rows=[json.loads(line) for line in self.audit.read_text(encoding='utf-8').splitlines()]
                self.metadata['server_call_log']=rows
        finally:
            if self._log is not None:self._log.close()
            if self._temporary is not None:self._temporary.cleanup()


async def synthetic_check():
    """Fixed fictional data only; no database, upload or model call."""
    from .core import read_pdf
    fixture=Path(__file__).resolve().parents[1]/'data/synthetic/contradiction/statement_A.pdf'
    doc=read_pdf(fixture.read_bytes(),'fictional.pdf','doc1')
    async with CaseTools([doc]) as session:
        evidence,_=await session.call('search_evidence',{'query':'T1 principal interest'})
        total,_=await session.call('calculator',{'values':['1000.00','100.00']})
        passed=bool(evidence) and any('1000.00' in l['text'].replace(',','') and '100.00' in l['text'] for l in evidence) and total=={'sum':'1100.00'}
    return {'passed':passed,'data':'fixed fictional statement','model_calls':0,'mcp':session.metadata}
