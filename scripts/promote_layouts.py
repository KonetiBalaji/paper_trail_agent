"""Publish or verify a fixed, read-only deployment registry; no provider calls."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import layout_registry as registry
from scripts.evaluate_layout_package import sources, fixtures


def publish(*, check=False):
    root = registry.ROOT
    report = registry.read(root / registry.REPORT)
    registry.require(report['source_sha256'] == sources() and report['fixture_sha256'] == fixtures())
    names = sorted(row['package'] for row in report['native']['candidate']['packages'])
    candidate = {'schema_version': 1, 'packages': names, 'report_sha256': registry.digest(root / registry.REPORT)}
    verified = registry.verify(root, candidate, report)
    path = root / registry.REGISTRY
    if check:
        registry.require(registry.read(path) == candidate)
    else:
        temporary = path.with_suffix('.json.tmp')
        try:
            temporary.write_text(json.dumps(candidate, indent=2) + '\n', encoding='utf-8', newline='\n')
            os.replace(temporary, path)
        finally:
            if temporary.exists(): temporary.unlink()
    return {'status': verified['status'], 'packages': names, 'corpus_cases': verified['corpus_cases'],
            'receipt_sha256': verified['receipt_sha256'], 'check_only': check}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(publish(check=args.check)))
    except (ValueError, OSError, KeyError, TypeError):
        print('Registry not published: complete current regression and review evidence is required.', file=sys.stderr)
        raise SystemExit(1)
