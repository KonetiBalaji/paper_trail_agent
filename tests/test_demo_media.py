"""Verify the published demo is anonymous, bound to evidence and byte-seekable."""
import hashlib
import json
from pathlib import Path
from fastapi.testclient import TestClient
from app import main, platform

ROOT = Path(__file__).resolve().parents[1]


def test_public_video_page_and_byte_ranges_need_no_identity_or_provider(monkeypatch):
    monkeypatch.setenv('PAPER_TRAIL_MODE', 'service')
    def forbidden(*args, **kwargs):
        raise AssertionError('Watching the demo must not require a database or model call')
    monkeypatch.setattr(main.meta, 'request', forbidden)
    monkeypatch.setattr(platform, 'runtime', forbidden)
    expected = (ROOT/'app/static/demo.mp4').read_bytes()
    evidence = json.loads((ROOT/'docs/demo-video-verification.json').read_text())
    assert evidence['passed'] and hashlib.sha256(expected).hexdigest() == evidence['sha256']
    with TestClient(main.app) as client:
        page = client.get('/static/demo.html')
        assert page.status_code == 200
        assert '<video' in page.text and '/static/demo.mp4' in page.text
        assert 'saved live API result' in page.text and 'Read the full transcript' in page.text
        assert 'Watch the 2:08 demo' in client.get('/').text
        response = client.get('/static/demo.mp4', headers={'Range': 'bytes=0-1023'})
        assert response.status_code == 206
        assert response.headers['content-type'].startswith('video/mp4')
        assert response.headers['content-range'] == f'bytes 0-1023/{len(expected)}'
        assert response.content == expected[:1024]
        assert client.head('/static/demo.mp4').headers['content-length'] == str(len(expected))
        assert client.get('/static/demo.mp4', headers={'Range': f'bytes={len(expected)+1}-'}).status_code == 416
        assert client.get('/static/demo.srt').status_code == 200
        assert client.get('/static/demo-poster.jpg').status_code == 200
