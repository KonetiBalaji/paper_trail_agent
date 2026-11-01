"""Decode and verify the real demo artifact; no browser or generation calls."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frame_at(path, seconds):
    import av
    with av.open(str(path)) as container:
        container.seek(int(seconds*av.time_base))
        return next(frame for frame in container.decode(video=0) if frame.time >= seconds-.001)


def verify(project, media):
    import av
    import imageio_ffmpeg
    import numpy as np
    timeline = json.loads((project/'edit-timeline.json').read_text())
    speech = json.loads((project/'narration-review.json').read_text())
    cues = json.loads((project/'caption-cues.json').read_text())
    evidence = json.loads((project/'local-meta-report.json').read_text())
    checks = []
    def check(name, condition):
        checks.append({'check': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)
    for name, expected in ((timeline['source'], timeline['source_sha256']),
                           (timeline['narration'], timeline['narration_sha256']),
                           (timeline['live_report'], timeline['live_report_sha256'])):
        check('bound_input_'+name, sha(project/name) == expected)
    cuts = timeline['cuts']; check('starts_at_zero', cuts[0]['start_frame'] == 0)
    check('continuous_picture', all(a['end_frame'] == b['start_frame'] for a, b in zip(cuts, cuts[1:])))
    check('complete_picture', cuts[-1]['end_frame'] == timeline['frame_count'])
    originals = sorted((c['source_start'], c['source_end']) for c in cuts if c['kind'] == 'video')
    check('no_reused_source_intervals', all(a[1] <= b[0] for a, b in zip(originals, originals[1:])))
    check('natural_source_speed', all(abs(c['source_end']-c['source_start']-(c['end_frame']-c['start_frame'])/timeline['fps']) < 1e-8 for c in cuts if c['kind'] == 'video'))
    check('all_nine_story_beats', len({c['chapter'] for c in cuts}) == 9)
    check('caption_intervals', all(c['start'] < c['end'] <= speech['audio']['duration_seconds'] for c in cues))
    check('no_caption_overlap', all(a['end'] <= b['start']+.001 for a, b in zip(cues, cues[1:])))
    covered = [word for c in cues for word in range(c['first_word'], c['last_word']+1)]
    check('all_words_captioned_once', covered == list(range(speech['word_count'])))
    check('caption_readability_flags_resolved', speech['caption_warnings'] == [])
    calls = evidence['agent']['tool_trace']; logs = evidence['agent']['mcp']['server_call_log']
    check('actual_mcp_budget', len(calls) == len(logs) == 3 <= evidence['agent']['mcp']['max_calls'] == 8)
    for call, log in zip(calls, logs):
        output = {'lines': call['result']} if call['tool'] == 'search_evidence' else call['result']
        check('matching_actual_server_call_'+str(log['sequence']),
              call['input'] == log['input'] and output == log['output'] and call['tool'] == log['tool']
              and call['validation'] == log['validation'] == 'passed')
        if call['tool'] == 'calculator':
            check('independent_sum_'+str(log['sequence']),
                  sum(Decimal(value) for value in call['input']['values']) == Decimal(call['result']['sum']))
    confirmed = [f for f in evidence['findings'] if f['severity'] == 'confirmed']
    check('actual_live_finding', len(confirmed) == 1 and confirmed[0]['difference'] == '25.00' and len(confirmed[0]['sources']) == 2)
    count = 0; previous = None; luminance_min = 255
    with av.open(str(media)) as container:
        stream = container.streams.video[0]
        check('1080p_h264_15fps', stream.width == 1920 and stream.height == 1080 and stream.codec_context.name == 'h264' and float(stream.average_rate) == timeline['fps'])
        for frame in container.decode(video=0):
            if previous is not None and abs(frame.time-previous-1/timeline['fps']) > .001:
                raise AssertionError('Unexpected picture timestamp gap')
            previous = frame.time; count += 1
            # Every frame is decoded; these paper/green scenes must not contain
            # black setup frames or missing-source gaps.
            luminance_min = min(luminance_min, float(frame.to_ndarray(format='gray').mean()))
    check('full_picture_decode', count == timeline['frame_count'])
    check('no_black_frames', luminance_min > 70)
    samples = 0
    with av.open(str(media)) as container:
        stream = container.streams.audio[0]
        check('stereo_48k_aac', stream.codec_context.name == 'aac' and stream.sample_rate == 48000 and len(stream.layout.channels) == 2)
        for frame in container.decode(audio=0):
            samples += frame.samples
    audio_duration = samples/48000
    check('no_truncated_speech', abs(audio_duration-speech['audio']['duration_seconds']) < .12)
    check('under_three_minutes', timeline['duration_seconds'] <= 180)
    # Compare a non-caption region at the middle of every retained app cut.
    # This is sampled source conformance, not a proof of every pixel's content.
    comparisons = []
    for cut in cuts:
        if cut['kind'] != 'video':
            continue
        index = (cut['start_frame']+cut['end_frame'])//2
        final = frame_at(media, index/timeline['fps']).to_ndarray(format='rgb24')
        source_time = cut['source_start']+(index-cut['start_frame'])/timeline['fps']
        original = frame_at(project/timeline['source'], source_time).to_ndarray(format='rgb24')
        # Exclude top and bottom caption areas for both caption positions.
        error = float(np.abs(final[180:880].astype(np.int16)-original[180:880].astype(np.int16)).mean())
        comparisons.append({'chapter': cut['chapter'], 'final_frame': index, 'source_seconds': source_time, 'mean_absolute_rgb_error': round(error, 4)})
        check('sampled_source_conformance_'+str(index), error < 3.5)
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-nostdin', '-i', str(media),
                             '-vn', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'],
                            capture_output=True, text=True, check=True, timeout=90)
    levels = json.loads(result.stderr[result.stderr.rfind('{'):result.stderr.rfind('}')+1])
    check('encoded_audio_headroom', float(levels['input_tp']) <= 0 and -19 <= float(levels['input_i']) <= -13)
    return {'schema_version': 1, 'passed': True, 'verified_at': datetime.now(timezone.utc).isoformat(),
            'file': media.name, 'sha256': sha(media), 'duration_seconds': timeline['duration_seconds'],
            'frames_decoded': count, 'audio_samples_decoded': samples, 'audio_decoded_seconds': audio_duration,
            'loudness_lufs': float(levels['input_i']), 'true_peak_dbtp': float(levels['input_tp']),
            'source_conformance_samples': comparisons, 'checks': checks,
            'listening_review': 'not_performed',
            'visual_review_scope': 'Source and edited contact sheets plus selected full-size frames; no claim of continuous audiovisual playback review.',
            'disclosure': timeline['disclosure'],
            'input_sha256': {name: sha(project/name) for name in ('edit-timeline.json', 'caption-cues.json', 'narration-review.json')}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir', default='work/demo-project')
    parser.add_argument('--media', default='demo-review-v4.mp4')
    args = parser.parse_args(); project = Path(args.project_dir).resolve()
    if Path(args.media).name != args.media:
        parser.error('Media must be inside the project directory')
    result = verify(project, project/args.media)
    (project/'video-verification.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps({'passed': result['passed'], 'checks': len(result['checks']), 'seconds': result['duration_seconds'],
                      'loudness_lufs': result['loudness_lufs'], 'true_peak_dbtp': result['true_peak_dbtp']}))
