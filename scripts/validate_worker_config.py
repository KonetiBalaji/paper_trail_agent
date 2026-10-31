"""Validate the disabled worker proposal against Vercel's published schema."""
import json
from pathlib import Path
from urllib.request import urlopen
from jsonschema import validators

ROOT=Path(__file__).resolve().parents[1]
SCHEMA_URL='https://openapi.vercel.sh/vercel.json'


def main():
    with urlopen(SCHEMA_URL,timeout=30) as response:raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('Configuration schema exceeds validation bound')
    schema=json.loads(raw);validator=validators.validator_for(schema)(schema)
    active=json.loads((ROOT/'vercel.json').read_text())
    proposal=json.loads((ROOT/'vercel.worker.disabled.json').read_text())
    validator.validate(active);validator.validate(proposal)
    if 'daemons' in active:raise ValueError('Active deployment unexpectedly enables worker configuration')
    if {key:value for key,value in proposal.items() if key!='daemons'}!=active:
        raise ValueError('Worker proposal differs from the verified web deployment')
    worker=proposal['daemons']['ocr-worker']
    if any(value!=0 for value in worker['instances'].values()):raise ValueError('Proposal must keep every instance disabled')
    path=(ROOT/worker['root']/worker['entrypoint']).resolve()
    if path.parent!=ROOT or not path.is_file():raise ValueError('Worker build context must be the repository root')
    print('Published Vercel schema validates; web configuration preserved; all proposed daemon instances are zero.')


if __name__=='__main__':main()
