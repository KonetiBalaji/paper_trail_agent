"""Evaluate all six synthetic cases without credentials or network requests."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core import read_pdf,parse_statement,reconcile
from scripts.generate_bank_fixtures import generate,ROOT

def evaluate():
    results=[]
    with tempfile.TemporaryDirectory(prefix='paper-trail-eval-') as temporary:
        banks=generate(Path(temporary))
        for case in ('clean','contradiction','math_error','messy','bank_clean','bank_error'):
            truth=json.loads((ROOT/case/'ground_truth.json').read_text(encoding='utf-8'))
            paths=[banks[case]] if case in banks else sorted((ROOT/case).glob('*.pdf'))
            assert len(paths)==(1 if case in banks else 2),f'{case}: missing input PDFs'
            docs=[]
            for i,path in enumerate(paths,1):
                doc=read_pdf(path.read_bytes(),path.name,f'doc{i}')
                doc['statement']=parse_statement(doc);docs.append(doc)
            findings,calculations=reconcile(docs)
            confirmed=[f for f in findings if f['severity']=='confirmed']
            assert len(confirmed)==truth['expected_confirmed_contradictions'],f'{case}: incorrect confirmed count'
            index={line['id']:line for doc in docs for line in doc['lines']}
            for finding in confirmed:
                assert finding['sources'],f'{case}: missing confirmed source'
                assert all(source in index and index[source]['text'] for source in finding['sources']),f'{case}: unresolved source'
            if case in ('clean','bank_clean'):assert findings==[],f'{case}: unexpected findings'
            if case=='contradiction':
                assert confirmed[0]['type']=='cross_document_interest_mismatch' and confirmed[0]['difference']=='25.00'
                assert len(confirmed[0]['sources'])==2
            if case=='math_error':
                assert confirmed[0]['type']=='incorrect_statement_total' and confirmed[0]['difference']=='50.00'
                assert confirmed[0]['computed']=='3300.00'
            if case=='messy':
                assert {f['type'] for f in findings}=={'ocr_required','comparison_skipped'}
                assert all(f['severity']=='review' for f in findings)
                assert docs[1]['lines']==[] and docs[1]['statement']['tranches']==[]
            if case in banks:
                statement=docs[0]['statement']
                assert statement['loan_id']==truth['account_id'] and statement['currency']==truth['currency']
                assert statement['period_end']==truth['period_end']
                assert statement['opening_balance']==truth['opening_balance'] and statement['closing_balance']==truth['closing_balance']
                assert [{k:t[k] for k in ('id','date','amount')} for t in statement['transactions']]==truth['transactions']
                assert calculations[0]['computed']==truth['computed_closing_balance']
                if case=='bank_error':
                    expected=truth['expected_findings'][0]
                    assert all(confirmed[0][k]==v for k,v in expected.items())
            results.append(case)
            print(f'PASS {case}: {len(confirmed)} confirmed, {sum(f["severity"]=="review" for f in findings)} review')
    print(f'{len(results)} / 6 cases passed')
    return results

if __name__=='__main__':evaluate()
