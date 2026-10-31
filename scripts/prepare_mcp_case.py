"""Export a bounded pattern-redacted case bundle for an explicitly chosen host."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core import read_pdf
from app.mcp_server import evidence_bundle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--synthetic',choices=['clean','contradiction','math_error','messy'])
    source.add_argument('--report-json',type=Path,help='Explicitly approved saved report; inspect the redacted result before sharing')
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.synthetic:
        root=Path(__file__).resolve().parents[1]/'data/synthetic'/args.synthetic
        docs=[read_pdf(p.read_bytes(),p.name,'doc'+str(i)) for i,p in enumerate(sorted(root.glob('*.pdf')),1)]
    else:
        with args.report_json.open('rb') as stream:raw=stream.read(16*1024*1024+1)
        if len(raw)>16*1024*1024:parser.error('Report exceeds the export limit')
        docs=json.loads(raw)['documents']
    raw=json.dumps(evidence_bundle(docs),indent=2).encode('utf-8')
    if len(raw)>2*1024*1024:parser.error('MCP bundle exceeds 2 MiB')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with os.fdopen(os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as stream:stream.write(raw)
    print('Created pattern-redacted case bundle. Inspect unsupported personal details before choosing an external host.')


if __name__=='__main__':main()
