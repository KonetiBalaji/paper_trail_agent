"""Generate fictional bank PDFs from tracked UTF-8 ground truth; no API needed."""
import argparse
import json
from pathlib import Path
from reportlab.pdfgen import canvas

ROOT=Path(__file__).resolve().parents[1]/'data'/'synthetic'

def generate(output_root=ROOT):
    paths={}
    for case in ('bank_clean','bank_error'):
        truth=json.loads((ROOT/case/'ground_truth.json').read_text(encoding='utf-8'))
        folder=Path(output_root)/case;folder.mkdir(parents=True,exist_ok=True)
        path=folder/'bank.pdf'
        pdf=canvas.Canvas(str(path),pagesize=(612,792),invariant=1)
        pdf.setTitle('Paper Trail Agent fictional bank fixture')
        pdf.setFont('Helvetica-Bold',16)
        pdf.drawString(36,750,'SYNTHETIC BANK STATEMENT')
        pdf.setFont('Helvetica',11)
        lines=['Fictional Cedar Bank - Example Customer - not a real account',
            f"Account: {truth['account_id']} Currency: {truth['currency']}",
            f"Statement period end: {truth['period_end']}",
            f"Opening balance: {truth['opening_balance']}"]
        lines += [f"Transaction {t['id']} | {t['date']} | Amount: {t['amount']}" for t in truth['transactions']]
        lines += [f"Closing balance: {truth['closing_balance']}"]
        for i,line in enumerate(lines):pdf.drawString(36,710-i*30,line)
        pdf.save();paths[case]=path
    return paths

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT)
    for case,path in generate(parser.parse_args().output).items():print(case,path)
