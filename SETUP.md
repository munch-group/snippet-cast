# TTS setup — say, manual, Piper (local), and ElevenLabs (cloud)

All four backends are already wired into `snippet_cast.screencast`; you select
one with `--tts say` / `--tts manual` / `--tts piper` / `--tts elevenlabs`. You
never manage audio formats yourself: whatever a backend emits (macOS `.aiff`,
Piper `.wav`, ElevenLabs `.mp3`, or your own recordings) is re-encoded to AAC
and normalised to 44.1 kHz stereo, so it concatenates cleanly with the silent
typing clips.

One thing worth knowing before you start: the script **caches audio per unique
narration string**. A loop line without interpolation is spoken once and reused
every iteration; a line with `{i}` differs each time and is synthesised (and, on
ElevenLabs, billed) each time. So proof your script first with the free
`--tts silent --subtitles`, then render once with a real voice.

---

## say — macOS built-in, zero setup

`--tts say` shells out to the `say` command that ships with macOS. Nothing to
install, nothing to configure, and it's the CLI's default backend
(`main()`'s `--tts` defaults to `"say"`) — so on a Mac, `snippet-cast fib.py -o
out.mp4` with no `--tts` flag at all already gives you real speech, not just
timing.

```bash
snippet-cast fib.py -o out.mp4 --tts say
```

It uses whatever voice is set as the system default (System Settings →
Accessibility → Spoken Content → System Voice); `synth_say()` doesn't expose a
`--say-voice`/rate flag, so every line gets the same voice at the same rate.
If you want a different voice, a different rate, per-line control, or
inline `say` markup (`[[slnc 300]]`, `[[rate 170]]`, …), don't reach for
`--tts say` — drive `say` yourself with the **manual** backend below.

Linux/Windows have no `say` binary; use `--tts silent` for a free proofing
pass there instead, and Piper/ElevenLabs for a real voice.

## manual — recording narration yourself

`--tts manual` doesn't synthesize anything — it plays back audio files you
already have, one per unique narration line, in the exact order `build()`
requests them. Use it for a human voiceover, or to drive `say` (or any other
tool) by hand, line by line, with full control snippet-cast's other backends
don't give you.

### 1. Export the narration script

```bash
snippet-cast fib.py --export-script > script.txt
```

This needs no ffmpeg/ffprobe and doesn't render anything — it just prints the
numbered lines `build()` will ask a TTS backend for, e.g.:

```
001  [pass 2, beat 1]  Let's trace an iterative Fibonacci function as it runs.
002  [pass 2, beat 2]  The first line names the fib-function and defines its parameters...
003  [pass 2, beat 3]  Start from the first two Fibonacci numbers, zero and one.
...
```

Only unique narration text gets a number — an identical repeated line (e.g. an
un-interpolated loop line) shows as `(dup of #NNN)` and reuses that earlier
recording; don't record it again. A beat with no narration shows as
`(silent)` and needs no file at all.

### 2. Produce one audio file per number

Save each as `001.<ext>`, `002.<ext>`, ... in any directory — `.wav`, `.mp3`,
`.m4a`, `.aiff`, `.flac`, or `.ogg` are all accepted.

**With a real microphone:** record and export each line with any audio editor
(Audacity, GarageBand, `ffmpeg`, ...), matching the script's numbering.

**With `say`, driven by hand (macOS):** call `say` yourself once per numbered
line instead of letting `--tts say` do it automatically — this is how you get
a specific voice, rate, or inline pause/emphasis markup per line:

```bash
mkdir -p audio
say -v Samantha -r 190 -o audio/001.aiff "Let's trace an iterative Fibonacci function as it runs."
say -v Samantha -r 190 -o audio/002.aiff "The first line names the fib-function and defines its parameters..."
say -v Samantha -r 150 -o audio/003.aiff "Start from the first two Fibonacci numbers,[[slnc 200]] zero and one."
```

(`say -v ?` lists installed voices.) Re-run just the one `say` command for a
line you want to redo — no need to touch the others or re-run snippet-cast.

### 3. Render

```bash
snippet-cast fib.py -o out.mp4 --tts manual --manual-audio-dir audio/
```

`build()`/the CLI reject `--manual-audio-dir` without `--tts manual`, and
`--tts manual` without `--manual-audio-dir`. If a numbered file is missing,
the error names the exact stem and narration text it was expecting, e.g.
`manual backend: missing recording 003.* in 'audio/' (narration: '...'). Run
--export-script for the numbered list this needs to match.` — re-running
`--export-script` after any edit to the snippet's `#:` narration is the fix,
since renumbering follows straight from the source.

### Recording live via the microphone (`--record`, macOS)

Steps 1–3 above, done interactively, with your own voice, straight into the
terminal or a notebook cell — no separate script export, no external editor:

```bash
snippet-cast fib.py -o out.mp4 --record --manual-audio-dir audio/
```

or, from Python/a notebook:

```python
from snippet_cast import record_narration
record_narration("fib.py", "audio/", "out.mp4")
```

or, in the `%%snippet-cast` cell magic (`--tts` is ignored — `--record` always
targets the manual backend):

```
%%snippet-cast --record --manual-audio-dir audio/
def fib(n):             #: We define fib, taking one argument, n.
    ...
```

The prompts below appear as normal inline input boxes in the notebook,
exactly as in a terminal — nothing notebook-specific to know.

It steps through every beat in order, showing each one's rendered frame for
context (skip with `--no-frame`), and prompts only where a recording
actually matters — a duplicate or silent beat is shown and skipped
automatically. In a terminal this is via
[`imgcat`](https://iterm2.com/utilities/imgcat) (any iTerm2/WezTerm/Kitty-style
setup that provides one; without it on PATH, previews are silently skipped
with a one-time note, not a hard failure). **In a notebook, the frame and
the status text each update a single cell output in place** — one live
"current frame" area and one live "current status" area — rather than a new
output block piling up per beat, so a long session doesn't turn into a wall
of scrollback.

At each numbered beat,
**what Enter does depends on whether a recording already exists there** —
it's never the reason a beat ends up with none:

```
003  [pass 2, beat 3]  Start from the first two Fibonacci numbers, zero and one.
[Enter=keep, r=record, d=delete] >
```

- **Enter** — keep the existing recording. Only offered when one exists;
  with nothing to keep, a blank Enter is rejected (re-prompts) rather than
  silently leaving the beat unrecorded.
- **r** — record from your system's current default input device (whatever
  you have selected in System Settings → Sound → Input) until you hit Enter,
  play it back, then Enter to accept or `r` to redo.
- **d** — delete the existing recording (only offered when one exists).
- **s** — explicitly leave a beat with no existing recording unrecorded for
  now (only offered when there's nothing to keep — the deliberate
  alternative to Enter there):

```
005  [pass 2, beat 5]  Advance the pair — b becomes the running sum.
[r=record, s=skip for now] >
```

If any beat still has no recording once you've been through all of them —
skipped this session, or never recorded in an earlier one — a summary lists
them and the automatic build is skipped rather than attempted (it would
otherwise fail outright on the first missing one); re-run `--record` to fill
them in.

Nothing touches `audio/` until you've been through every beat: new takes
land in a scratch directory and deletions are staged, committed together
only on a clean finish. **Ctrl+C at any point — including mid-recording —
aborts the whole session with no changes made.** On a clean finish it
renders the MP4 automatically, same as a normal `--tts manual` run.

This is also the natural way to fix a stale recording after editing a
snippet's `#:` narration: re-run `--record`, listen to what plays back at
each beat, and `r`/`d` just the ones that no longer match — everything else
is a single Enter.

The recording itself is macOS only (mic capture, default-device detection,
and playback shell out to macOS tools: `system_profiler`, `ffmpeg
avfoundation`, `afplay`) — elsewhere, use `--tts manual` with recordings made
some other way (see above). Frame preview isn't macOS-specific (notebook
display and `imgcat` both work cross-platform).

---

## Piper — local, offline, free

Piper is a fast neural TTS that runs entirely on your machine (CPU is fine).
Active project: **OHF-Voice/piper1-gpl**. Voices are ONNX models, tens of MB.

### 1. Install

```bash
pip install piper-tts
```

Works on Linux, macOS, Windows, and Raspberry Pi. If `pip` installs into a
managed environment, prefer your project env (you use pixi) or a venv on Python
3.10–3.12.

### 2. Download a voice

As of `piper-tts` 1.5.0 (the OHF-Voice/piper1-gpl rewrite), the `piper` CLI
**does not auto-download voices** — fetch one explicitly first:

```bash
python -m piper.download_voices en_US-lessac-medium
```

This drops `en_US-lessac-medium.onnx` and `.onnx.json` into the current
directory (pass `--download-dir ~/piper-voices` to put them somewhere else).
Voices are named `<lang>_<REGION>-<name>-<quality>`, e.g. `en_US-lessac-medium`.
Quality tiers: `x_low`/`low` (16 kHz) and `medium`/`high` (22.05 kHz). `medium`
is the sweet spot for screencasts. Browse and listen at the Piper voice-samples
page (linked from the project's README). List every available voice name with:

```bash
python -m piper.download_voices
```

Once downloaded, verify it's on your PATH:

```bash
echo "hello world" | piper --model en_US-lessac-medium --output_file test.wav
```

(If you downloaded to a directory other than the current one, add
`--data-dir ~/piper-voices` so `piper` can find it.) After this one-time
download, synthesis is fully offline.

### 3. Run it

```bash
# default voice (en_US-lessac-medium)
snippet-cast fib.py -o out.mp4 --tts piper
```

Configure via environment variables:

```bash
export PIPER_MODEL=en_GB-alba-medium      # any downloaded voice name …
export PIPER_MODEL=/voices/en_US-lessac-medium.onnx   # … or a local .onnx path
export PIPER_LENGTH_SCALE=1.1             # speaking rate: >1 slower, <1 faster
export PIPER_DATA_DIR=~/piper-voices      # where you downloaded voices to (must match --download-dir above)
export PIPER_BIN=/opt/piper/piper         # if the binary isn't just "piper"
snippet-cast fib.py -o out.mp4 --tts piper
```

…or with the equivalent CLI flags, which take precedence over the environment
variables above (handy for a one-off run without touching your shell env):

```bash
snippet-cast fib.py -o out.mp4 --tts piper \
  --piper-model en_GB-alba-medium --piper-length-scale 1.1 \
  --piper-data-dir ~/piper-voices --piper-bin /opt/piper/piper
```

`PIPER_LENGTH_SCALE` / `--piper-length-scale` is the one you'll actually reach
for — Piper can rush, and `1.05–1.15` makes a walkthrough much easier to follow.

### Troubleshooting

| Symptom | Fix |
|---|---|
| `piper not found` | Not on PATH. Set `PIPER_BIN`, or reinstall into the active env. |
| `Unable to find voice: ... (use piper.download_voices)` | Voice hasn't been downloaded, or `PIPER_DATA_DIR` doesn't match the `--download-dir` you used. Run `python -m piper.download_voices <voice>`. |
| `.onnx.json` error with a local model | The config file must sit next to the `.onnx` with the same base name. |
| Odd Python errors on install | Some distros ship an incompatible Python; use a clean venv/pixi env (3.10–3.12). |

---

## ElevenLabs — cloud, highest quality, paid

Best expressiveness and voice variety, but each call goes to their API and is
billed. The backend here uses the plain REST endpoint over Python's standard
library, so there's **no SDK to install or keep up to date**.

### 1. Get an API key

Sign up at elevenlabs.io, then **Developers → API Keys → Create**. Copy the key
(looks like `sk_...`). Keep it secret — treat it like a password.

### 2. Set environment variables

```bash
export ELEVENLABS_API_KEY=sk_your_key_here      # required
# optional overrides (defaults shown):
export ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM # "Rachel"
export ELEVENLABS_MODEL=eleven_multilingual_v2
export ELEVENLABS_FORMAT=mp3_44100_128
```

…or pass the equivalent CLI flags, which take precedence over the environment
variables above:

```bash
snippet-cast fib.py -o out.mp4 --tts elevenlabs \
  --elevenlabs-api-key sk_your_key_here \
  --elevenlabs-voice-id 21m00Tcm4TlvDq8ikWAM \
  --elevenlabs-model eleven_multilingual_v2 \
  --elevenlabs-format mp3_44100_128
```

To use a different voice, open the Voice Library or your Voices in the
ElevenLabs app; each voice has an **ID** (e.g. `JBFqnCBsd6RMkjVDRZzb`). Copy the
ID, not the display name, into `ELEVENLABS_VOICE_ID` / `--elevenlabs-voice-id`.

### 3. Run it

```bash
snippet-cast fib.py -o out.mp4 --tts elevenlabs
```

### Choosing a model

| `ELEVENLABS_MODEL` | Use it for |
|---|---|
| `eleven_multilingual_v2` | Default. Highest quality, most nuanced — good for the final render. |
| `eleven_flash_v2_5` | ~75 ms latency and cheaper — good for iterating on long scripts. |
| `eleven_v3` | Most expressive, 70+ languages. |

### Cost, and how the cache helps

Text-to-speech is billed **one credit per character** of narration. Because the
script caches by narration string, repeated identical lines cost once — but
interpolated lines (`Iteration where i is {i}`) are unique per beat and billed
per beat. Two habits keep the bill down:

1. Lock the script with `--tts silent --subtitles` (free) before any paid render.
2. In `--every` mode, prefer a single summary line over interpolating on a line
   that runs hundreds of times, unless you truly want each one narrated.

### Output format

Default `mp3_44100_128` works on any plan. Higher mp3 bitrates need Creator tier
and WAV/PCM needs Pro tier — but since everything is re-encoded to AAC, the
default mp3 is more than enough; there's no quality reason to change it.

### Troubleshooting

| HTTP status | Meaning |
|---|---|
| 401 | Missing or wrong `ELEVENLABS_API_KEY`. |
| 422 | Bad `voice_id` or `model_id` (check the ID vs. the name). |
| 429 | Rate limited or out of credits. |

---

## Which backend?

| | say | manual | `--record` | Piper | ElevenLabs |
|---|---|---|---|---|---|
| Runs | macOS built-in | Your own files | macOS mic, live | Offline, on your CPU | Cloud API |
| Cost | Free | Free (your time) | Free (your time) | Free | Per character |
| Setup | None | None | None | One-time voice download | API key |
| Quality | OK, one fixed voice | Whatever you record | Whatever you record | Good | Best / most expressive |
| Best for | Quick real-speech proof on a Mac | Human voiceover, or per-line `say` control | Recording your own voiceover interactively | Iterating, privacy, bulk | The final take |

A practical workflow: **draft** with `--tts silent --subtitles`, **iterate** with
`--tts piper` (or `--tts say` on a Mac), **finish** with `--tts elevenlabs` or
your own recording via `--tts manual`.

## Adding another provider (OpenAI, Azure, etc.)

Any backend is a function `synth(text, out_stem) -> path_to_audio_file`. Write
one, then register it:

```python
def synth_openai(text, out):
    # ... call the API, save bytes to out + ".mp3" ...
    return out + ".mp3"

BACKENDS["openai"] = synth_openai   # now: --tts openai
```

`make_clip` handles the rest (any container, any sample rate). Return the path;
don't worry about format.
