"""Render every candidate PDF page with Poppler for human visual review."""
import argparse
import json
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw

PROJECT = Path(__file__).resolve().parents[1]


def render(output, poppler='pdftoppm'):
    output.mkdir(parents=True, exist_ok=True)
    root = PROJECT / 'data/layout_packages/cedar_v1/cases'
    manifest = json.loads((root / 'manifest.json').read_text())
    pages = []
    for case in manifest['cases']:
        for doc in case['documents']:
            prefix = output / (case['case'] + '_' + Path(doc['file']).stem)
            subprocess.run([poppler, '-r', '110', '-png', str(root / case['case'] / doc['file']), str(prefix)],
                           check=True, timeout=30, capture_output=True)
            for path in sorted(output.glob(prefix.name + '-*.png')):
                pages.append((case['case'] + '/' + path.stem.split('_statement_')[-1], path))
    width, height, columns = 306, 430, 4
    contact = Image.new('RGB', (width * columns, height * ((len(pages) + columns - 1) // columns)), 'white')
    draw = ImageDraw.Draw(contact)
    for index, (label, path) in enumerate(pages):
        image = Image.open(path).convert('RGB'); image.thumbnail((width - 12, height - 38))
        x, y = (index % columns) * width, (index // columns) * height
        contact.paste(image, (x + 6, y + 30)); draw.text((x + 6, y + 8), label, fill='black')
    target = output / 'contact-sheet.png'; contact.save(target)
    print(json.dumps({'pages': len(pages), 'contact_sheet': str(target)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=PROJECT / 'tmp/pdfs/layout-review')
    parser.add_argument('--pdftoppm', default='pdftoppm')
    args = parser.parse_args(); render(args.output, args.pdftoppm)
