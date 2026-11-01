"""Prepare accepted narration/captions without generating speech or controlling a UI.

Inputs stay in an ignored local project directory. Provider URLs/request IDs are
never copied into the portable manifest. Original audio is never overwritten.
Caption timing comes from actual provider words, not estimated word lengths.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

CHAPTERS = ('interest_hook', 'public_demo_boundary', 'grounded_sources', 'wrong_total',
            'critic_and_human_review', 'scan_abstention', 'live_meta_tools',
            'evaluations', 'closing')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tokens(value):
    return re.findall(r'[a-z0-9]+', value.lower())


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8', newline='\n')


def timestamp(seconds):
    millis = round(seconds*1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f'{hours:02}:{minutes:02}:{secs:02},{millis:03}'


def caption_groups(words):
    """Phrase groups using the supplied word clock; no rescaling of that clock."""
    groups = []; current = []
    for i, word in enumerate(words):
        current.append(word)
        text = ' '.join(w['word'] for w in current)
        elapsed = word['end']-current[0]['start']
        gap = words[i+1]['start']-word['end'] if i+1 < len(words) else 1
        if (len(current) >= 9 or len(text) >= 70 or elapsed >= 3.4 or
                (word['word'].endswith(('.', '?', '!')) and elapsed >= 1) or
                (gap > .4 and elapsed >= .9) or i == len(words)-1):
            end = word['end']+.16
            if i+1 < len(words):
                end = min(end, words[i+1]['start'])
            groups.append({'start': current[0]['start'], 'end': end, 'text': text,
                           'first_word': i-len(current)+1, 'last_word': i})
            current = []
    return groups


def caption_text(value):
    # Conventional numeric subtitle spelling; the exact spoken words remain
    # alongside every cue and in the unmodified narration.txt source.
    for original, display in (
        ('three thousand three hundred dollars', '$3,300'),
        ('three thousand three hundred fifty', '3,350'),
        ('one hundred twenty-five', '125'), ('one hundred dollars', '$100'),
        ('twenty-five-dollar', '$25'), ('fifty-dollar', '$50'),
        ('fifty percent', '50%'), ('nineteen', '19')):
        value = value.replace(original, display)
    return value


def prepare(project):
    import imageio_ffmpeg
    import av
    script = (project/'narration.txt').read_text(encoding='utf-8').strip()
    provider = json.loads((project/'voice-provider.json').read_text(encoding='utf-8'))
    original = project/'narration-original.audio'
    if provider.get('engine') != 'orca':
        raise ValueError('This project accepts the explicitly approved HeyGen Voice/Orca take only')
    words = [w for w in provider['word_timestamps'] if not w['word'].startswith('<')]
    duration = provider['duration']
    if not words or tokens(script) != tokens(' '.join(w['word'] for w in words)):
        raise ValueError('Provider timing text differs from the approved script')
    if any(not all(math.isfinite(w[k]) for k in ('start', 'end')) or
           not 0 <= w['start'] < w['end'] <= duration+.1 for w in words):
        raise ValueError('Invalid word timestamps')
    if any(words[i]['end'] > words[i+1]['start']+.02 for i in range(len(words)-1)):
        raise ValueError('Overlapping provider words require review')
    paragraphs = script.split('\n\n')
    if len(paragraphs) != len(CHAPTERS):
        raise ValueError('Unexpected chapter structure; review the edit instead of guessing timing')
    chapters = []; cursor = 0
    for name, paragraph in zip(CHAPTERS, paragraphs):
        length = len(paragraph.split()); selected = words[cursor:cursor+length]
        if tokens(paragraph) != tokens(' '.join(w['word'] for w in selected)):
            raise ValueError('Paragraph-to-word timing mismatch')
        chapters.append({'id': name, 'speech_start': selected[0]['start'],
                         'speech_end': selected[-1]['end'], 'text': paragraph,
                         'first_word': cursor, 'last_word': cursor+length-1})
        cursor += length
    if cursor != len(words):
        raise ValueError('Unaccounted spoken words')
    captions = []
    for chapter in chapters:
        # A scene/topic boundary must not leave the previous paragraph's text
        # on screen while the next argument has already begun.
        grouped = caption_groups(words[chapter['first_word']:chapter['last_word']+1])
        for cue in grouped:
            cue['first_word'] += chapter['first_word']
            cue['last_word'] += chapter['first_word']
            cue['chapter'] = chapter['id']
            cue['spoken_text'] = cue['text']
            cue['text'] = caption_text(cue['spoken_text'])
        # Keep a short trailing word with its sentence, not a flashing orphan.
        if len(grouped) > 1 and grouped[-1]['end']-grouped[-1]['start'] < .8:
            prior, last = grouped[-2:]
            prior.update(end=last['end'], last_word=last['last_word'],
                         spoken_text=prior['spoken_text']+' '+last['spoken_text'])
            prior['text'] = caption_text(prior['spoken_text']); grouped.pop()
        index = 0
        while index < len(grouped)-1:
            cue, following = grouped[index:index+2]
            if (len(cue['text'])/(cue['end']-cue['start']) > 22 and
                    following['end']-cue['start'] <= 5.5 and
                    len(cue['text'])+len(following['text']) < 100):
                cue.update(end=following['end'], last_word=following['last_word'],
                           spoken_text=cue['spoken_text']+' '+following['spoken_text'])
                cue['text'] = caption_text(cue['spoken_text']); grouped.pop(index+1)
            else:
                index += 1
        captions.extend(grouped)
    if tokens(' '.join(c['spoken_text'] for c in captions)) != tokens(script):
        raise ValueError('Caption grouping omitted or duplicated spoken content')
    warnings = [{'cue': i+1, 'seconds': round(c['end']-c['start'], 3),
                 'characters_per_second': round(len(c['text'])/(c['end']-c['start']), 1)}
                for i, c in enumerate(captions)
                if c['end']-c['start'] < .8 or len(c['text'])/(c['end']-c['start']) > 22]
    (project/'narration.srt').write_text('\n'.join(
        f"{i+1}\n{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}\n"
        for i, c in enumerate(captions)), encoding='utf-8', newline='\n')
    write_json(project/'caption-cues.json', captions)
    write_json(project/'speech-chapters.json', chapters)
    # Two-pass level preparation preserves the original speech clock. No tempo,
    # time stretch, target duration, inserted pause or speed change is used.
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [ffmpeg, '-hide_banner', '-nostdin', '-v', 'info', '-i', str(original)]
    first = subprocess.run(command+['-af', 'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json',
                                    '-f', 'null', '-'], capture_output=True, text=True, check=True, timeout=90)
    levels = json.loads(first.stderr[first.stderr.rfind('{'):first.stderr.rfind('}')+1])
    normalized = project/'narration-master.wav'
    binding = project/'narration-master-source.json'
    source_hash = sha(original)
    settings = 'loudnorm-I-16-TP-1.5-LRA-11-stereo-48k-pcm24-v1'
    if normalized.exists():
        cached = json.loads(binding.read_text(encoding='utf-8'))
        if cached != {'source_sha256': source_hash, 'settings': settings, 'output_sha256': sha(normalized)}:
            raise ValueError('Prepared audio binding changed; retain the old take and use a new project output')
    if not normalized.exists():
        effect = ('loudnorm=I=-16:TP=-1.5:LRA=11:linear=true:print_format=json:'
                  f"measured_I={levels['input_i']}:measured_TP={levels['input_tp']}:"
                  f"measured_LRA={levels['input_lra']}:measured_thresh={levels['input_thresh']}:"
                  f"offset={levels['target_offset']}")
        result = subprocess.run(command+['-af', effect, '-ar', '48000', '-ac', '2',
                                          '-c:a', 'pcm_s24le', '-n', str(normalized)],
                                capture_output=True, text=True, check=True, timeout=90)
        (project/'audio-normalization.log').write_text(result.stderr, encoding='utf-8')
        write_json(binding, {'source_sha256': source_hash, 'settings': settings, 'output_sha256': sha(normalized)})
    with av.open(str(normalized)) as audio:
        stream = audio.streams.audio[0]
        measured = float(stream.duration*stream.time_base)
        audio_info = {'channels': len(stream.layout.channels), 'sample_rate': stream.sample_rate,
                      'codec': stream.codec_context.name, 'duration_seconds': measured}
    if abs(measured-duration) > .12:
        raise ValueError('Prepared audio changed duration beyond the codec tolerance')
    review = {'schema_version': 1, 'prepared_at': datetime.now(timezone.utc).isoformat(),
              'status': 'narration_and_timing_prepared_not_final_video',
              'voice': {'catalog_name': 'Marco', 'voice_id': 'a50b2b18a4bf49109caf46a3a6c6a08a',
                        'requested_engine': 'heygen_voice', 'returned_engine': provider['engine'],
                        'language': 'en', 'speed': 1, 'generation': 'one user-approved retry after the initial engine-policy rejection'},
              'provider_duration_seconds': duration, 'audio': audio_info,
              'word_count': len(words), 'caption_cues': len(captions), 'caption_warnings': warnings,
              'subtitle_spelling': 'Conventional numeric forms for fully matched amounts/counts/percentages; exact provider words retained as spoken_text. No speech changes.',
              'timing_source': 'Provider word timestamps, exact normalized match to approved script. Independent local ASR is supplemental, not a human listening review.',
              'listening_review': 'not_performed',
              'missing_video_gates': ['live Meta trace footage', 'edit and full encode',
                                      'full visual/caption review', 'publicly accessible video URL'],
              'original_input_levels': {k: levels[k] for k in ('input_i', 'input_tp', 'input_lra')},
              'files': {name: sha(project/name) for name in ('narration.txt', 'narration-original.audio',
                        'narration-master.wav', 'narration.srt', 'caption-cues.json', 'speech-chapters.json')}}
    write_json(project/'narration-review.json', review)
    return review


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir', default='work/demo-project')
    args = parser.parse_args()
    result = prepare(Path(args.project_dir).resolve())
    print(json.dumps({'status': result['status'], 'duration': result['audio']['duration_seconds'],
                      'word_count': result['word_count'], 'caption_cues': result['caption_cues'],
                      'caption_warnings': len(result['caption_warnings'])}))
