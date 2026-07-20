# TTS setup — Piper (local) and ElevenLabs (cloud)

Both backends are already wired into `snippet_cast.screencast`; you select one with
`--tts piper` or `--tts elevenlabs`. You never manage audio formats yourself:
whatever a backend emits (Piper `.wav`, ElevenLabs `.mp3`) is re-encoded to AAC
and normalised to 44.1 kHz stereo, so it concatenates cleanly with the silent
typing clips.

One thing worth knowing before you start: the script **caches audio per unique
narration string**. A loop line without interpolation is spoken once and reused
every iteration; a line with `{i}` differs each time and is synthesised (and, on
ElevenLabs, billed) each time. So proof your script first with the free
`--tts silent --subtitles`, then render once with a real voice.

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

| | Piper | ElevenLabs |
|---|---|---|
| Runs | Offline, on your CPU | Cloud API |
| Cost | Free | Per character |
| Quality | Good | Best / most expressive |
| Network | Only first download | Every render |
| Best for | Iterating, privacy, bulk | The final take |

A practical workflow: **draft** with `--tts silent --subtitles`, **iterate** with
`--tts piper`, **finish** with `--tts elevenlabs`.

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
