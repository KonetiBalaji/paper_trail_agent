"""Actual bundled CPU OCR on fictional image-only PDFs; no provider requests."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core import read_pdf
from app.ocr import extract, candidate_checks


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',default='work/ocr-smoke.json')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    results=[]
    for name in ('statement_B.pdf',):
        raw=(root/'data/synthetic/messy'/name).read_bytes()
        original=read_pdf(raw,name,'doc1')
        assert not original['lines'], 'OCR smoke requires a truly image-only PDF'
        doc=extract(raw,original)
        findings,calculations=candidate_checks(doc)
        assert findings and all(f['severity']=='review' for f in findings)
        results.append({'fixture':name,'ocr':doc['ocr'],
                        'lines':[{k:v for k,v in line.items() if k in ('text','confidence','usable','id')} for line in doc['lines']],
                        'candidate_statement':doc['statement'],'findings':findings,'calculations':calculations})
    path=Path(args.report);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'scope':'Fictional baseline image-only fixtures; scores uncalibrated; all results require review.','cases':results},indent=2)+'\n')
    print(json.dumps([{'fixture':r['fixture'],'lines':r['ocr']['total_lines'],'usable':r['ocr']['usable_lines'],
                       'duration_ms':r['ocr']['duration_ms'],'review':True} for r in results]))


if __name__=='__main__':main()
