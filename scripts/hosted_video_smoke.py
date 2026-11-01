"""Read-only public checks for the authorized deployed video and player."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import httpx

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://paper-trail-agent.vercel.app'


def run():
    checks = []
    def check(name, condition):
        checks.append({'check': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)
    video = (ROOT/'app/static/demo.mp4').read_bytes()
    digest = hashlib.sha256(video).hexdigest()
    with httpx.Client(base_url=ORIGIN, timeout=60, follow_redirects=False) as client:
        page = client.get('/static/demo.html'); page.raise_for_status()
        check('public_player_matches', page.text.replace('\r\n', '\n') == (ROOT/'app/static/demo.html').read_text(encoding='utf-8'))
        check('native_video_controls', '<video' in page.text and ' controls ' in page.text and '/static/demo.mp4' in page.text)
        check('full_transcript', 'Read the full transcript' in page.text and 'Python Decimal recomputes' in page.text)
        check('saved_result_graphic_disclosed', 'graphic of a separate saved live API result' in page.text)
        check('no_inline_or_remote_script', '<script' not in page.text)
        check('media_csp', "media-src 'self'" in page.text)
        check('root_links_player', '/static/demo.html' in client.get('/').text)
        response = client.head('/static/demo.mp4'); response.raise_for_status()
        check('video_mime', response.headers.get('content-type', '').startswith('video/mp4'))
        check('video_length', response.headers.get('content-length') == str(len(video)))
        for name, start, end in [('beginning', 0, 1023), ('tail', len(video)-1024, len(video)-1)]:
            response = client.get('/static/demo.mp4', headers={'Range': f'bytes={start}-{end}'})
            check(name+'_206_range', response.status_code == 206 and response.headers.get('content-range') == f'bytes {start}-{end}/{len(video)}')
            check(name+'_exact_bytes', response.content == video[start:end+1])
        response = client.get('/static/demo.mp4'); response.raise_for_status()
        check('complete_anonymous_video_hash', hashlib.sha256(response.content).hexdigest() == digest)
        check('subtitles_match', client.get('/static/demo.srt').text.replace('\r\n', '\n') == (ROOT/'app/static/demo.srt').read_text(encoding='utf-8'))
        poster = client.get('/static/demo-poster.jpg'); poster.raise_for_status()
        check('poster_matches', poster.content == (ROOT/'app/static/demo-poster.jpg').read_bytes())
        check('demo_css_available', client.get('/static/demo.css').status_code == 200)
        check('no_session_created', not client.cookies)
        health = client.get('/api/health'); health.raise_for_status()
        check('application_still_healthy', health.json()['status'] == 'ok')
        score = client.get('/api/agent-evals'); score.raise_for_status(); value = score.json()
        check('existing_live_evidence_still_current', value['passed'] and value['current_live_proof'] and value['current_fixture_match'])
    return {'schema_version': 1, 'passed': True, 'checked_at': datetime.now(timezone.utc).isoformat(),
            'base_url': ORIGIN, 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'video_sha256': digest, 'video_bytes': len(video), 'checks': checks,
            'scope': 'Read-only anonymous HTTP, exact full/range media bytes, player assets and existing app health. No model calls, sessions, browser playback, visual keyboard/mobile or listening review.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', default='work/hosted-video-results.json')
    args = parser.parse_args(); result = run()
    output = Path(args.report); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps({'passed': result['passed'], 'checks': len(result['checks'])}))
