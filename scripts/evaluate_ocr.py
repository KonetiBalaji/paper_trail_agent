"""Actual OCR regression gate over rasterized fictional financial statements."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import platform
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core import read_pdf
from app.ocr import extract,candidate_checks


def evaluate(root):
    manifest=json.loads((root/'manifest.json').read_text())
    if not manifest.get('fictional') or len(manifest['cases'])!=4:raise ValueError('Invalid OCR corpus')
    rows=[]
    for case in manifest['cases']:
        raw=(root/case['file']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=case['sha256']:raise ValueError('OCR fixture changed')
        original=read_pdf(raw,case['file'],'doc1')
        if original['lines']:raise ValueError('Expected image-only fixture')
        doc=extract(raw,original)
        findings,calculations=candidate_checks(doc)
        differences=[f.get('difference') for f in findings]
        checks={'requires_review':bool(findings),'zero_confirmed':all(f['severity']=='review' for f in findings),
                'no_false_clean':any(f['type']=='ocr_review' for f in findings)}
        if case['candidate_math_error']:checks['candidate_math_error']=case['candidate_math_error'] in differences
        else:checks['no_untrusted_calculation']=not calculations
        rows.append({'case':case['name'],'checks':checks,'passed':all(checks.values()),'ocr':doc['ocr'],
                     'statement':doc['statement'],'lines':doc['lines'],'findings':findings,'calculations':calculations})
    import rapidocr_onnxruntime
    project=Path(__file__).resolve().parents[1]
    models=Path(rapidocr_onnxruntime.__file__).parent/'models'
    return {'scope':'Fictional English scans only; uncalibrated scores; candidate arithmetic never confirmed.',
            'runtime':{'python':platform.python_version(),'platform':platform.system()},
            'manifest_sha256':hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),
            'source_sha256':{name:hashlib.sha256((project/name).read_text(encoding='utf-8').replace('\r\n','\n').encode()).hexdigest()
                             for name in ('app/ocr.py','app/core.py','app/layouts.py','scripts/evaluate_ocr.py')},
            'model_sha256':{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(models.glob('*.onnx'))},
            'cases':rows,'passed':all(row['passed'] for row in rows)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',default='work/ocr-results.json')
    args=parser.parse_args();report=evaluate(Path(__file__).resolve().parents[1]/'data/ocr')
    target=Path(args.report);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps([{'case':row['case'],'checks':row['checks'],'ocr':row['ocr']} for row in report['cases']]))
    raise SystemExit(0 if report['passed'] else 1)
