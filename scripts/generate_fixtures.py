"""Generate fictional PDF fixtures and explicit evaluation ground truth. No API needed."""
from pathlib import Path
import json
from decimal import Decimal
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import fitz

ROOT = Path(__file__).resolve().parents[1] / 'data' / 'synthetic'
CASES = {
    'clean': [],
    'contradiction': ['cross_document_interest_mismatch'],
    'math_error': ['incorrect_statement_total'],
    'messy': ['missing_tranche', 'period_mismatch', 'ocr_required'],
}

def generate():
    for case, labels in CASES.items():
        folder = ROOT / case
        folder.mkdir(parents=True, exist_ok=True)
        docs = []
        for side in ['A', 'B']:
            interest = '125.00' if case == 'contradiction' and side == 'B' else '100.00'
            missing = case == 'messy' and side == 'B'
            date = '2026-09-30' if missing else '2026-10-31'
            rows = [
                'SYNTHETIC TEST DATA - NOT A REAL FINANCIAL DOCUMENT',
                'Fictional Cedar Lending | Example Customer',
                f'Document: {side} | Loan: DEMO-001 | Currency: USD',
                f'Statement period end: {date}',
                f'Tranche T1 | Principal: 1000.00 | Interest: {interest}',
            ]
            if not missing:
                rows.append('Tranche T2 | Principal: 2000.00 | Interest: 200.00')
            total = Decimal('1000.00') + Decimal(interest)
            if not missing:
                total += Decimal('2200.00')
            stated = total + (Decimal('50.00') if case == 'math_error' and side == 'B' else 0)
            rows.append(f'Stated principal plus interest total: {stated:.2f}')
            pdf = folder / f'statement_{side}.pdf'
            c = canvas.Canvas(str(pdf), pagesize=(612, 792))
            c.setTitle(f'Paper Trail Agent synthetic {case} statement {side}')
            c.setFillColorRGB(.08, .18, .25)
            c.setFont('Helvetica-Bold', 19)
            c.drawString(48, 742, 'Paper Trail Agent | Test Statement')
            c.setFont('Helvetica', 10)
            for i, line in enumerate(rows, 1):
                c.drawString(48, 700 - (i-1)*32, f'L{i:02d}  {line}')
            c.setFont('Helvetica', 9)
            c.drawString(48, 50, 'Page 1 | All names, identifiers and amounts are fictional.')
            c.save()
            if missing:
                source = fitz.open(pdf)
                pix = source[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                source.close()
                c = canvas.Canvas(str(pdf), pagesize=(612, 792))
                import io
                c.drawImage(ImageReader(io.BytesIO(pix.tobytes('png'))), 0, 0, 612, 792)
                c.save()
            docs.append({'file': pdf.name, 'page': 1, 'text_layer': not missing,
                'period_end': date, 'loan_id': 'DEMO-001', 'currency': 'USD',
                'tranches': [{'id':'T1','principal':'1000.00','interest':interest,'source_line':'L05'}] +
                    ([] if missing else [{'id':'T2','principal':'2000.00','interest':'200.00','source_line':'L06'}]),
                'stated_total': f'{stated:.2f}', 'computed_total': f'{total:.2f}',
                'total_source_line': f'L{len(rows):02d}',
                'source_lines': {f'L{i:02d}': s for i,s in enumerate(rows,1)}})
        findings = []
        if case == 'contradiction':
            findings = [{'type': labels[0], 'tranche':'T1', 'field':'interest',
                'values':['100.00','125.00'], 'difference':'25.00',
                'sources':['statement_A.pdf#page=1:L05','statement_B.pdf#page=1:L05']}]
        elif case == 'math_error':
            findings = [{'type': labels[0], 'document':'statement_B.pdf',
                'stated':'3350.00','computed':'3300.00','difference':'50.00',
                'sources':['statement_B.pdf#page=1:L05','statement_B.pdf#page=1:L06','statement_B.pdf#page=1:L07']}]
        elif case == 'messy':
            findings = [{'type':'period_mismatch','severity':'review',
                'sources':['statement_A.pdf#page=1:L04','statement_B.pdf#page=1:L04']},
                {'type':'missing_tranche','tranche':'T2','severity':'review',
                 'note':'Different periods: absence is incomplete evidence, not a confirmed financial contradiction.'},
                {'type':'ocr_required','document':'statement_B.pdf','severity':'review',
                 'note':'Without OCR, return extraction limitation. Never invent missing values.'}]
        (folder/'ground_truth.json').write_text(json.dumps({'case':case,'documents':docs,
            'expected_findings':findings,'expected_confirmed_contradictions':int(case in ['contradiction','math_error'])},indent=2))
    print('Generated 8 PDFs and 4 ground-truth files.')

if __name__ == '__main__':
    generate()
