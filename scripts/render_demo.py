"""Edit real synthetic-app footage with accepted speech and explicit evidence graphics.

No UI automation, provider calls, fabricated tool activity, speed changes or
frozen source frames. Every video cut retains a distinct original interval at
1x. Graphic cutaways are labelled as graphics from a saved live API report.
"""
import argparse
from bisect import bisect_right
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

FPS = 15
WIDTH, HEIGHT = 1920, 1080
INK, PAPER, GREEN = '#18342d', '#f5f7f3', '#204c37'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, data):
    path.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8', newline='\n')


def configure(project):
    chapters = json.loads((project/'speech-chapters.json').read_text())
    speech = json.loads((project/'narration-review.json').read_text())
    ends = [chapter['speech_start'] for chapter in chapters[1:]] + [speech['audio']['duration_seconds']]
    # Deliberately selected original intervals, all unique and natural speed.
    # Cut points follow measured speech, not equal-size slide durations.
    selections = [
        [('video', 19, 1)],
        [('video', 0, 1)],
        [('video', 40, .5), ('video', 63, .5)],
        [('video', 119, .28), ('video', 132, .42), ('video', 140, .30)],
        [('video', 152.5, .43), ('video', 85.5, .57)],
        [('video', 167, .5), ('video', 180, .5)],
        [('evidence_graphic', 0, 1)],
        [('video', 208, .28), ('video', 224, .30), ('video', 253, .42)],
        [('closing_graphic', 0, 1)],
    ]
    cuts = []; cursor = 0
    for chapter, end, selection in zip(chapters, ends, selections):
        last = round(end*FPS)
        if chapter is chapters[-1]:
            last = math.ceil(end*FPS)
        first = cursor
        for index, (kind, source, share) in enumerate(selection):
            boundary = last if index == len(selection)-1 else first+round((last-first)*sum(x[2] for x in selection[:index+1]))
            source_frame = round(source*FPS)
            source_seconds = source_frame/FPS
            cuts.append({'chapter': chapter['id'], 'kind': kind, 'start_frame': cursor,
                         'end_frame': boundary, 'source_start': source_seconds,
                         'source_start_frame': source_frame if kind == 'video' else None,
                         'source_end': (source_frame+boundary-cursor)/FPS if kind == 'video' else None})
            cursor = boundary
    intervals = sorted((row['source_start'], row['source_end']) for row in cuts if row['kind'] == 'video')
    if any(intervals[i][1] > intervals[i+1][0] for i in range(len(intervals)-1)):
        raise ValueError('Source intervals overlap; do not repeat footage to fill runtime')
    style = {'direction': 'Swiss precision using the application green/cream palette',
             'purpose': 'Real app evidence first; clear saved-result graphic for the Meta segment',
             'fonts': {'regular': 'C:/Windows/Fonts/segoeui.ttf', 'bold': 'C:/Windows/Fonts/segoeuib.ttf',
                       'mono': 'C:/Windows/Fonts/consola.ttf'},
             'palette': {'ink': INK, 'paper': PAPER, 'green': GREEN},
             'caption_font_size': 44, 'caption_max_width': 1640, 'caption_bottom_margin': 34,
             'caption_positions': 'Bottom by default; top for wrong_total so captions do not cover either financial total.',
             'exclusions': ['no manufactured app screens', 'no animated pending/live tool simulation',
                            'no source retiming or freeze', 'no music competing with figures']}
    result = {'schema_version': 1, 'fps': FPS, 'width': WIDTH, 'height': HEIGHT,
              'frame_count': cursor, 'duration_seconds': cursor/FPS,
              'source': 'raw-screen-03.mp4', 'source_sha256': sha(project/'raw-screen-03.mp4'),
              'narration': 'narration-master.wav', 'narration_sha256': sha(project/'narration-master.wav'),
              'live_report': 'local-meta-report.json', 'live_report_sha256': sha(project/'local-meta-report.json'),
              'cuts': cuts, 'style': style,
              'disclosure': 'App footage is the public deterministic synthetic flow. The separate live Meta section is an editorial graphic of an actual saved local API result, explicitly labelled; it is not an app recording or a new tool execution.'}
    dump(project/'edit-timeline.json', result)
    return result


class Source:
    def __init__(self, path, seconds):
        import av
        self.container = av.open(str(path)); self.container.seek(int(seconds*av.time_base))
        self.frames = self.container.decode(video=0); self.current = next(self.frames)

    def frame(self, seconds):
        while self.current.time < seconds-.001:
            self.current = next(self.frames)
        return self.current.to_image()

    def close(self):
        self.container.close()


class Graphics:
    def __init__(self, project, timeline):
        from PIL import ImageFont
        self.project = project; self.timeline = timeline
        fonts = timeline['style']['fonts']
        self.fonts = {key: {size: ImageFont.truetype(path, size) for size in (26, 28, 32, 36, 44, 52, 64, 80)}
                      for key, path in fonts.items()}
        self.report = json.loads((project/'local-meta-report.json').read_text())
        self.agent = self.report['agent']; self.calls = self.agent['tool_trace']; self.cache = {}
        if self.report['status'] != 'discrepancies' or self.report.get('agent_error'):
            raise ValueError('Graphic requires an actual successful saved live report')
        if len(self.calls) != 3 or [c['tool'] for c in self.calls] != ['search_evidence', 'calculator', 'calculator']:
            raise ValueError('Saved live evidence differs; review the graphic before rendering')
        if not all(c['validation'] == 'passed' and c['transport'] == 'mcp_stdio' for c in self.calls):
            raise ValueError('Never display failed or synthetic tool calls as passed live evidence')
        confirmed = [f for f in self.report['findings'] if f['severity'] == 'confirmed']
        if len(confirmed) != 1 or confirmed[0].get('difference') != '25.00':
            raise ValueError('Saved report no longer supports the displayed $25 claim')
        self.font_regular = ImageFont.truetype(fonts['regular'], 44)

    def canvas(self):
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (WIDTH, HEIGHT), PAPER)
        return image, ImageDraw.Draw(image)

    def text(self, draw, xy, value, size=36, weight='regular', fill=INK):
        draw.text(xy, str(value), font=self.fonts[weight][size], fill=fill)

    def evidence(self, state):
        key = 'evidence-'+str(state)
        if key in self.cache:
            return self.cache[key].copy()
        image, draw = self.canvas()
        self.text(draw, (110, 75), 'Recorded local Muse Spark run', 52, 'bold')
        self.text(draw, (110, 150), 'Evidence graphic from a saved API result — not an app screen', 28)
        if state == 0:
            self.text(draw, (110, 305), 'Same fictional statement pair', 44, 'bold')
            self.text(draw, (110, 400), '$25.00 interest discrepancy', 64, 'bold')
            self.text(draw, (110, 520), 'Grounded sources, exact tools, retained result', 36)
            self.text(draw, (110, 645), 'Public guests use local checks. This is a separate completed model run.', 28)
        elif state == 1:
            call = self.calls[0]
            self.text(draw, (110, 270), '1  search_evidence', 44, 'bold')
            self.text(draw, (110, 355), 'Query: '+call['input']['query'], 36, 'mono')
            for i, line in enumerate(call['result'][:2]):
                y = 460+i*160
                self.text(draw, (110, y), line['id'], 28, 'mono')
                self.text(draw, (110, y+52), line['text'], 32, 'mono')
            self.text(draw, (110, 825), f"{len(call['result'])} lines returned; two relevant excerpts shown. Validation: {call['validation']}.", 28)
        elif state == 2:
            self.text(draw, (110, 265), '2–3  calculator', 44, 'bold')
            for i, call in enumerate(self.calls[1:]):
                y = 365+i*210
                self.text(draw, (110, y), ' + '.join(call['input']['values']), 44, 'mono')
                self.text(draw, (110, y+75), '= '+call['result']['sum']+' USD', 52, 'bold')
            self.text(draw, (110, 825), 'Exact saved inputs and outputs. Both calls passed validation.', 28)
        else:
            limit = self.agent['mcp']['max_calls']
            # Retain the exact calculations while revealing their validation
            # and budget. This is a saved-result explanation, not a fake run.
            image = self.evidence(2)
            from PIL import ImageDraw
            draw = ImageDraw.Draw(image)
            draw.rectangle((100, 805, 1810, 875), fill=PAPER)
            self.text(draw, (110, 825), f'{len(self.calls)} / {limit} tool calls used · validation passed · MCP stdio', 32, 'bold')
        self.text(draw, (110, 895), 'Saved report SHA-256: '+self.timeline['live_report_sha256'][:24]+'…', 26, 'mono')
        self.cache[key] = image
        return image.copy()

    def closing(self):
        if 'closing' not in self.cache:
            image, draw = self.canvas()
            self.text(draw, (110, 200), 'Paper Trail Agent', 80, 'bold')
            self.text(draw, (110, 355), 'Try the four synthetic cases.', 52, 'bold')
            self.text(draw, (110, 470), 'paper-trail-agent.vercel.app', 44, 'mono')
            self.text(draw, (110, 620), 'Inspect the public code and known-answer evidence.', 36)
            self.text(draw, (110, 710), 'github.com/KonetiBalaji/paper_trail_agent', 36, 'mono')
            self.cache['closing'] = image
        return self.cache['closing'].copy()


def subtitles(graphics, cues, output):
    from PIL import Image, ImageDraw
    output.mkdir(exist_ok=True); layers = []
    for i, cue in enumerate(cues):
        image = Image.new('RGBA', (WIDTH, HEIGHT)); draw = ImageDraw.Draw(image)
        lines = []; current = ''
        for word in cue['text'].split():
            trial = (current+' '+word).strip()
            if draw.textlength(trial, font=graphics.font_regular) > 1640 and current:
                lines.append(current); current = word
            else:
                current = trial
        if current:
            lines.append(current)
        if len(lines) > 2:
            raise ValueError('Caption exceeds two readable lines')
        y = 48 if cue.get('chapter') == 'wrong_total' else HEIGHT-34-len(lines)*57
        for line in lines:
            length = draw.textlength(line, font=graphics.font_regular); x = (WIDTH-length)/2
            draw.rounded_rectangle((x-18, y-5, x+length+18, y+56), radius=9, fill=(12, 28, 22, 230))
            draw.text((x, y), line, font=graphics.font_regular, fill='white', stroke_width=1, stroke_fill='black')
            y += 57
        image.save(output/f'cue-{i+1:03}.png'); layers.append(image)
    return layers


def render(project, destination):
    import imageio_ffmpeg
    timeline = configure(project); graphics = Graphics(project, timeline)
    cues = json.loads((project/'caption-cues.json').read_text()); layers = subtitles(graphics, cues, project/'caption-images')
    cut_starts = [row['start_frame'] for row in timeline['cuts']]
    word_starts = [row['start'] for row in cues]
    # Anchor state changes to the actual returned speech timestamps, never an
    # evenly divided duration or an estimated words-per-minute clock.
    provider = json.loads((project/'voice-provider.json').read_text())
    normalized = []
    for word in provider['word_timestamps']:
        if not word['word'].startswith('<'):
            normalized.extend((token, word['start']) for token in re.findall('[a-z0-9]+', word['word'].lower()))
    def spoken(phrase):
        pattern = phrase.split()
        matches = [normalized[i][1] for i in range(len(normalized)-len(pattern)+1)
                   if normalized[i][1] > 81 and [t[0] for t in normalized[i:i+len(pattern)]] == pattern]
        if len(matches) != 1:
            raise ValueError('Graphic cue is ambiguous in the accepted speech')
        return matches[0]
    evidence_events = [(spoken('these are actual tool calls'), 1),
                       (spoken('an exact calculator'), 2), (spoken('bounded tool budget'), 3)]
    dump(project/'graphic-events.json', {'clock': 'final video seconds', 'events': evidence_events,
         'disclosure': timeline['disclosure'], 'evidence_source': timeline['live_report_sha256']})
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'warning', '-n',
               '-f', 'rawvideo', '-vcodec', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{WIDTH}x{HEIGHT}',
               '-r', str(FPS), '-i', 'pipe:0', '-i', str(project/'narration-master.wav'),
               '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-preset', 'medium',
               '-crf', '18', '-threads', '4', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
               '-ar', '48000', '-movflags', '+faststart', str(destination)]
    source = None; cut_index = -1
    with (project/'render.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
        try:
            for frame_index in range(timeline['frame_count']):
                next_index = bisect_right(cut_starts, frame_index)-1
                cut = timeline['cuts'][next_index]; seconds = frame_index/FPS
                if next_index != cut_index:
                    if source:
                        source.close(); source = None
                    if cut['kind'] == 'video':
                        source = Source(project/timeline['source'], cut['source_start'])
                    cut_index = next_index
                if cut['kind'] == 'video':
                    image = source.frame(cut['source_start']+(frame_index-cut['start_frame'])/FPS)
                elif cut['kind'] == 'evidence_graphic':
                    state = sum(seconds >= event[0] for event in evidence_events)
                    image = graphics.evidence(state)
                else:
                    image = graphics.closing()
                cue_index = bisect_right(word_starts, seconds)-1
                if cue_index >= 0 and seconds < cues[cue_index]['end']:
                    image.paste(layers[cue_index], (0, 0), layers[cue_index])
                process.stdin.write(image.tobytes())
                if frame_index % (FPS*15) == 0:
                    print(f'Rendered {seconds:.0f} / {timeline["duration_seconds"]:.1f} seconds', flush=True)
            process.stdin.close(); code = process.wait(timeout=180)
            if code:
                raise RuntimeError('FFmpeg failed; inspect the local render log')
        finally:
            if source:
                source.close()
            if process.poll() is None:
                process.terminate(); process.wait(timeout=15)
    report = {'status': 'rendered_pending_full_review', 'rendered_at': datetime.now(timezone.utc).isoformat(),
              'duration_seconds': timeline['duration_seconds'], 'fps': FPS,
              'file': destination.name, 'sha256': sha(destination), 'timeline_sha256': sha(project/'edit-timeline.json'),
              'scope': timeline['disclosure'], 'playback_speed': 1,
              'listening_review': 'not_performed', 'public_video_url': None}
    dump(project/'video-render-results.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir', default='work/demo-project')
    parser.add_argument('--output', default='demo-review-v1.mp4')
    args = parser.parse_args(); project = Path(args.project_dir).resolve()
    if Path(args.output).name != args.output:
        parser.error('Output must be a new filename inside the project directory')
    print(json.dumps(render(project, project/args.output)))
