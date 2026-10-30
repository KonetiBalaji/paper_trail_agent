"""Optional offline OCR. Recognized values are candidates requiring human review.

Keep heavy OCR dependencies in the separate worker environment. Confidence is
the recognizer's score, not a calibrated probability that a financial digit is right.
"""
import copy
import math
import multiprocessing
import time

ENGINE = 'rapidocr-onnxruntime/1.4.4'
MAX_PAGES = 5
MAX_PIXELS = 4_000_000
MIN_CONFIDENCE = .95


class OCRUnavailable(RuntimeError):
    pass


def source_lines(detections, doc_id, page, width, height, image_width, image_height):
    """Group adjacent cells on a baseline and map boxes to original PDF points."""
    if min(width, height, image_width, image_height) <= 0:
        raise ValueError('Invalid OCR page dimensions')
    cells = []
    for box, text, score in detections or []:
        score = float(score)
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Invalid OCR confidence')
        points = [(float(x), float(y)) for x, y in box]
        if len(points) != 4 or any(not math.isfinite(v) for p in points for v in p):
            raise ValueError('Invalid OCR geometry')
        x0, y0 = min(x for x, y in points), min(y for x, y in points)
        x1, y1 = max(x for x, y in points), max(y for x, y in points)
        if not (0 <= x0 < x1 <= image_width and 0 <= y0 < y1 <= image_height):
            raise ValueError('OCR box outside page')
        if not isinstance(text, str) or len(text) > 2000:
            raise ValueError('Invalid OCR text')
        if text.strip():
            cells.append({'text': text.strip(), 'score': score, 'box': [x0, y0, x1, y1]})
    if len(cells) > 2000:
        raise ValueError('OCR line limit exceeded')
    groups = []
    for cell in sorted(cells, key=lambda c: (c['box'][1], c['box'][0])):
        mid = (cell['box'][1] + cell['box'][3]) / 2
        match = next((g for g in reversed(groups[-3:])
                      if abs(g['mid'] - mid) <= .35 * min(g['height'], cell['box'][3] - cell['box'][1])), None)
        if match is None:
            groups.append({'mid': mid, 'height': cell['box'][3] - cell['box'][1], 'cells': [cell]})
        else:
            match['cells'].append(cell)
    lines = []
    for index, group in enumerate(groups, 1):
        row = sorted(group['cells'], key=lambda c: c['box'][0])
        confidence = min(c['score'] for c in row)
        bounds = [min(c['box'][0] for c in row), min(c['box'][1] for c in row),
                  max(c['box'][2] for c in row), max(c['box'][3] for c in row)]
        lines.append({'id': f'{doc_id}:p{page}:o{index}', 'page': page, 'line': index,
                      'text': ' '.join(c['text'] for c in row),
                      'bbox': [bounds[0]*width/image_width, bounds[1]*height/image_height,
                               bounds[2]*width/image_width, bounds[3]*height/image_height],
                      'page_width': width, 'page_height': height, 'method': 'ocr',
                      'confidence': confidence, 'usable': confidence >= MIN_CONFIDENCE})
    return lines


def _recognize(raw, doc_id, pages):
    try:
        import numpy as np
        import onnxruntime
        import pypdfium2
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        raise OCRUnavailable('Install requirements-ocr.txt in the separate OCR worker environment.') from None
    onnxruntime.disable_telemetry_events()
    engine = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1, text_score=0.0)
    lines = []
    with pypdfium2.PdfDocument(raw) as pdf:
        for number in pages:
            page = pdf[number-1]
            try:
                width, height = page.get_size()
                scale = min(2.5, math.sqrt(MAX_PIXELS / (width*height)))
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil().convert('RGB')
                    detections, _ = engine(np.array(image), text_score=0.0)
                    lines.extend(source_lines(detections, doc_id, number, width, height, image.width, image.height))
                finally:
                    bitmap.close()
            finally:
                page.close()
    return lines


def _child(connection, raw, doc_id, pages):
    try:
        connection.send(('ok', _recognize(raw, doc_id, pages)))
    except OCRUnavailable:
        connection.send(('unavailable', None))
    except Exception:
        # Never return recognizer errors containing document text or local paths.
        connection.send(('error', None))
    finally:
        connection.close()


def recognize(raw, doc_id, pages, timeout=90):
    """Bound OCR in an owned child; timeout kills only that child process."""
    if not raw.startswith(b'%PDF-') or len(raw) > 10*1024*1024:
        raise ValueError('OCR requires a PDF of at most 10 MB')
    if not pages or len(pages) > MAX_PAGES or len(set(pages)) != len(pages) or any(type(p) is not int or not 1 <= p <= 50 for p in pages):
        raise ValueError('OCR supports 1 to 5 distinct image-only pages per job')
    if not .1 <= timeout <= 90:
        raise ValueError('OCR timeout must be between 0.1 and 90 seconds')
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(sender, raw, doc_id, pages), daemon=True)
    try:
        process.start()
        sender.close()
        if not receiver.poll(timeout):
            raise TimeoutError('OCR exceeded its time limit; manual review required.')
        try:
            status, result = receiver.recv()
        except EOFError:
            raise RuntimeError('OCR worker exited; manual review required.') from None
        if status == 'unavailable':
            raise OCRUnavailable('Install requirements-ocr.txt in the separate OCR worker environment.')
        if status != 'ok':
            raise RuntimeError('OCR failed; manual review required.')
        return result
    finally:
        receiver.close()
        sender.close()
        if process.pid is not None:
            process.join(.2)
            if process.is_alive():
                process.terminate()
                process.join(2)
            if process.is_alive():
                process.kill()
                process.join()
            process.close()


def extract(raw, original, recognizer=recognize):
    """Derived OCR evidence, preserving native lines and the original document."""
    from .core import parse_statement
    pages = sorted({issue['page'] for issue in original['issues'] if issue['type'] == 'ocr_required'})
    if not pages:
        raise ValueError('Document has no image-only pages requiring OCR')
    started = time.monotonic()
    lines = recognizer(raw, original['id'], pages)
    doc = copy.deepcopy(original)
    doc.pop('statement', None)
    doc['lines'] += lines
    doc['lines'].sort(key=lambda line: (line['page'], line['bbox'][1], line['bbox'][0]))
    doc['issues'] = [issue for issue in doc['issues'] if issue['type'] != 'ocr_required']
    # Parsers see only confidence-qualified candidates. All recognized text is
    # retained in the evidence view, including excluded low-confidence lines.
    parse_doc = {**doc, 'lines': [line for line in doc['lines'] if line.get('usable', True)]}
    doc['statement'] = parse_statement(parse_doc)
    for page in pages:
        page_lines = [line for line in lines if line['page'] == page]
        if not page_lines or any(not line['usable'] for line in page_lines):
            doc['issues'].append({'type': 'ocr_low_confidence', 'page': page,
                                  'message': 'OCR is empty or contains low-confidence text; verify the original page.'})
    doc['issues'].append({'type': 'ocr_review', 'message': 'OCR values are unverified candidates. Human review of the original page is required.'})
    doc['ocr'] = {'engine': ENGINE, 'pages': pages, 'threshold': MIN_CONFIDENCE,
                  'confidence_calibrated': False, 'performed': True,
                  'duration_ms': round((time.monotonic()-started)*1000),
                  'usable_lines': sum(line['usable'] for line in lines), 'total_lines': len(lines)}
    by_source={line['id']:line for line in doc['lines']}
    candidates=[]
    def confidence(field,value,source):
        line=by_source.get(source,{})
        if line.get('method')=='ocr':
            candidates.append({'field':field,'value':value,'source':source,
                               'confidence':line['confidence'],'calibrated':False,'verified':False})
    for row in doc['statement']['tranches']:
        for field in ('principal','interest'):
            confidence('tranches.'+row['id']+'.'+field,row[field],row.get(field+'_source',row['source']))
    for field,source_field in (('stated_total','total_source'),('opening_balance','opening_source'),('closing_balance','closing_source')):
        if doc['statement'].get(field) is not None:
            confidence(field,doc['statement'][field],doc['statement'].get(source_field))
    for row in doc['statement']['transactions']:
        confidence('transactions.'+row['id']+'.amount',row['amount'],row['source'])
    doc['ocr']['field_candidates']=candidates
    return doc


def candidate_checks(doc):
    """Conditional arithmetic only; OCR cannot produce confirmed findings/clean."""
    from .core import reconcile,calculate,money
    candidate = copy.deepcopy(doc)
    candidate['issues'] = [i for i in candidate['issues'] if i['type'] != 'ocr_review']
    findings, calculations = reconcile([candidate])
    statement=candidate['statement'];rows=statement['tranches']
    # Within-page candidate arithmetic does not establish account/date identity.
    # Preserve the incomplete-identity finding; never fabricate a missing date.
    if (not calculations and not candidate['issues'] and 0<len(rows)<=500
            and len({row['id'] for row in rows})==len(rows)
            and statement['stated_total'] is not None):
        operands=[row[field] for row in rows for field in ('principal','interest')]
        computed=calculate(operands)
        sources=list(dict.fromkeys([row.get(field+'_source',row['source']) for row in rows
                                    for field in ('principal','interest')]+[statement['total_source']]))
        calculations.append({'document':doc['id'],'operands':operands,'computed':computed,
                             'stated':statement['stated_total'],'sources':sources})
        difference=abs(money(computed)-money(statement['stated_total']))
        if difference:
            findings.append({'id':f'F{len(findings)+1}','type':'incorrect_statement_total',
                             'message':f'Recognized stated total differs from recognized row sum by {difference:.2f}.',
                             'sources':sources,'difference':format(difference,'.2f'),
                             'computed':computed,'stated':statement['stated_total']})
    for finding in findings:
        finding['severity'] = 'review'
        finding['provisional'] = True
        finding['message'] = 'If OCR values are correct: ' + finding['message']
    for calculation in calculations:
        calculation['provisional'] = True
    # Include the mandatory review finding even when every candidate total matches.
    review = {'id': f'F{len(findings)+1}', 'type': 'ocr_review', 'severity': 'review',
              'message': 'Check OCR candidate values against the original PDF; recognizer confidence is not proof of correctness.',
              'sources': [line['id'] for line in doc['lines'] if line.get('method') == 'ocr'][:8]}
    return findings+[review], calculations
