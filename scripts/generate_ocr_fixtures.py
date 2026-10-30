"""Rasterize fictional benchmark pages for OCR eval; no text layer remains."""
import io
import json
import hashlib
from pathlib import Path
import pypdfium2
from PIL import Image, ImageFilter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

ROOT=Path(__file__).resolve().parents[1]


def generate(destination):
    destination.mkdir(parents=True,exist_ok=True)
    source=ROOT/'data/benchmark/loan_columns_error/statement_1.pdf'
    with pypdfium2.PdfDocument(source) as pdf:
        page=pdf[0];bitmap=page.render(scale=2)
        image=bitmap.to_pil().convert('RGB').copy();bitmap.close();page.close()
    manifest={'fictional':True,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'cases':[]}
    labeled=io.BytesIO();c=canvas.Canvas(labeled,pagesize=(612,792),invariant=1)
    c.setFont('Helvetica',16)
    for index,line in enumerate(['FICTIONAL OCR TEST', 'Loan: OCR-001','Currency: USD','As of: 2026-10-31',
                                 'Tranche T1 | Principal: 1000.00 | Interest: 100.00',
                                 'Stated principal plus interest total: 1150.00']):
        c.drawString(30,740-index*65,line)
    c.save()
    with pypdfium2.PdfDocument(labeled.getvalue()) as pdf:
        page=pdf[0];bitmap=page.render(scale=2)
        labeled_image=bitmap.to_pil().convert('RGB').copy();bitmap.close();page.close()
    for name in ('table_review','labeled_error','degraded','blank'):
        scanned=image
        if name=='labeled_error':scanned=labeled_image
        if name=='degraded':scanned=image.resize((153,198)).filter(ImageFilter.GaussianBlur(2)).resize(image.size)
        if name=='blank':scanned=Image.new('RGB',image.size,'white')
        path=destination/(name+'.pdf')
        c=canvas.Canvas(str(path),pagesize=(612,792),invariant=1)
        c.drawImage(ImageReader(scanned),0,0,width=612,height=792);c.save()
        manifest['cases'].append({'name':name,'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                  'expected_status':'review','expected_confirmed':0,
                                  'candidate_math_error':'50.00' if name=='labeled_error' else None})
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__=='__main__':generate(ROOT/'data/ocr')
