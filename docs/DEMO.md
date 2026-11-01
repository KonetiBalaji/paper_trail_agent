# Narrated synthetic demonstration

[Watch the 2:08 demo](https://paper-trail-agent.vercel.app/static/demo.html) ·
[MP4](https://paper-trail-agent.vercel.app/static/demo.mp4) ·
[Subtitles](https://paper-trail-agent.vercel.app/static/demo.srt)

The 1920×1080 H.264/AAC video is **128.267 seconds**, below three minutes.
It uses actual recorded application interactions with fictional PDFs. Source
footage and speech retain their natural 1× speed; no source interval is repeated
or frozen to fill a target duration.

| Time | Evidence |
| --- | --- |
| 0:00 | Confirmed $25 interest contradiction |
| 0:14 | Public synthetic flow and its deterministic scope |
| 0:22 | Both original interest lines, with source highlights |
| 0:34 | $3,300 calculation versus the highlighted $3,350 statement total |
| 0:49 | Extractor/Verifier/Critic trace and saved human approval |
| 1:06 | Image-only statement: review, zero confirmed discrepancies |
| 1:22 | Explicitly labelled graphic from an actual saved local Meta result |
| 1:41 | Baseline Evals, 19-case benchmark and the visible 50% retrieval probe |
| 1:59 | Interactive demo and public code links |

The Meta segment is an **editorial evidence graphic, not an app recording or
newly executing tools**. Its query, two relevant source excerpts, calculator
inputs/outputs, validation and three-of-eight call count come from the actual
saved report. All six retrieved lines and matching MCP server log are retained
in [demo-live-meta-evidence.json](demo-live-meta-evidence.json). The two original
source PDFs are the public contradiction fixtures. Public guests still cannot
invoke paid Meta processing.

## Production and verification

English narration uses HeyGen's public catalog voice Marco, explicitly requested
as HeyGen Voice and returned under its `orca` engine token. It is not a clone of
the builder's voice. The first Starfish request was rejected by workspace policy;
the user approved one retry, which produced the retained take. No further speech
generation or speed adjustment was used.

Provider word timestamps match all 355 script words after normalization. The
45 open-caption cues preserve every spoken word, use conventional numeric
spelling for matched amounts, and stay within paragraph boundaries. The exact
spoken wording remains in the transcript and cue source. Short trailing words
were grouped with their sentence. Caption timing/read-speed checks have zero
remaining flags. Captions move to the top during the math example so they do
not cover either total; they otherwise use the same bottom position.

[demo-video-verification.json](demo-video-verification.json) records 41 passing
checks, full decoding of 1,924 frames and the AAC audio, source-conformance
samples for every retained app cut, no missing/black frames, complete caption
coverage and independently recomputed MCP sums. Encoded audio measures -16.22
LUFS integrated and -4.34 dBTP. Independent local `small.en` ASR on the encoded
audio matches its transcription of the original speech and recognizes the key
amounts and review negations. ASR is supplemental evidence, not a human ear.

Visual QA inspected the source contact sheet, an edited contact sheet and
full-size critical frames, including both original highlights, the saved review
revision, $50 calculation/source pairing and every Meta graphic state.
**Continuous audiovisual playback and a human listening review have not been
performed.** Final owner review remains appropriate before submission; no
auditory-quality or universal accessibility claim is made.

The player is public, uses native controls, serves byte ranges, and offers the
complete text transcript and subtitles. It has no model call or identity
requirement. Browser playback/keyboard/mobile visual verification is still
unverified; HTTP/codec/range checks are recorded separately.

## Reusable project

The local project bundle preserves original speech and take 03, the normalized
audio master, word timings, source report, cuts, graphic events, captions,
verification results and Python source. Aborted recordings, local environment
files, signed provider URLs and model cache are excluded. Windows Segoe UI and
Consolas are used from the existing OS installation; font files are not
redistributed.

After unpacking the bundle on Windows, install `requirements.txt` into a separate
environment. The following commands use the existing accepted audio and footage;
they do not generate speech, call Meta or control a browser:

```powershell
python scripts/prepare_demo.py --project-dir .
python scripts/render_demo.py --project-dir . --output demo-rebuild.mp4
python scripts/verify_demo.py --project-dir . --media demo-rebuild.mp4
```

In the repository, the optional tools are pinned in
`tests/requirements-video.txt`; they are not web or OCR-worker dependencies.
The scripts default to the ignored `work/demo-project` directory. Keep provider
response URLs and private recordings outside Git.
