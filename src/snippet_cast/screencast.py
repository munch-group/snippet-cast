#!/usr/bin/env python3
"""
screencast — turn an annotated Python snippet into a narrated screencast.

INPUT: a .py file that is still valid Python. Narration for a line is written as
a trailing comment beginning with the marker ``#:``. Example:

    def fib(n):          #: We define fib, taking one argument, n.
        a, b = 0, 1      #: Start from the first two Fibonacci numbers.
        for _ in range(n):  #: Loop n times.
            a, b = b, a + b #: Advance the pair; b becomes the running sum.
        return a         #: Return a — the nth Fibonacci number.

Each ``#:`` line becomes one "beat": the code is revealed up to that line, the
line is highlighted, and its narration is spoken. A ``#:`` on its own line
(no code) makes an intro/outro beat with no highlight. Ordinary ``#`` comments
are left alone and never narrated.

By default the snippet is EXECUTED once under sys.settrace, and each beat shows
a Python Tutor-style "state" panel with the variables as they are right after
that line first runs (for a loop body, after the first iteration). Lines that
never execute — e.g. a function that is defined but never called — show
"(no state)", so include a driver call if you want the body's state to appear.
Pass --no-trace to skip execution entirely (code + highlight only).

NARRATION INTERPOLATION: a narration may reference live variables with {name},
substituted with the value at that step (use {{ }} for literal braces):

    for i in range(5):    #: Iteration {i}, running total is {total}.

--every: emit one beat per EXECUTION of a marked line, in execution order, so a
loop animates iteration by iteration (combine with {name} to narrate each one).
In this mode the full snippet is shown from the start and the highlight follows
execution, rather than the code being progressively revealed.

USAGE (installed console script):
    snippet-cast input.py -o out.mp4 --tts say
    snippet-cast input.py -o out.mp4 --tts silent   # no audio backend needed
    snippet-cast loop.py  -o out.mp4 --every         # animate each iteration
    snippet-cast input.py -o out.mp4 --subtitles     # burn narration captions
    snippet-cast input.py -o out.mp4 --typing        # type each new line in

Or run the module directly without installing the console script:
    python -m snippet_cast.screencast input.py -o out.mp4 --tts say

Proofing tip: --tts silent --subtitles gives a fast, voiceless preview with the
narration on screen, so you can check wording and pacing before rendering audio.

TTS backends (choose with --tts):
    say         macOS built-in (`say`). Zero install. Good enough for drafts.
    silent      Silence sized to the text length. Runs anywhere; pair with
                --subtitles to proof narration without generating audio.
    piper       Local neural TTS (`pip install piper-tts`). Offline, free.
                Config via PIPER_MODEL / PIPER_LENGTH_SCALE (see synth_piper).
    elevenlabs  Cloud neural TTS via REST. Set ELEVENLABS_API_KEY (and
                optionally ELEVENLABS_VOICE_ID / ELEVENLABS_MODEL). See SETUP.md.
"""

import argparse
import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import urllib.error
import urllib.request
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont
from pygments import highlight
from pygments.formatters import ImageFormatter
from pygments.lexers import PythonLexer
from pygments.styles import get_style_by_name

# ---------------------------------------------------------------------------
# Config — tweak freely.
# ---------------------------------------------------------------------------
MARKER = "#:"           # trailing-comment token that marks a narration line
STYLE = "monokai"       # any pygments style name
FONT_NAME = "DejaVu Sans Mono"
FONT_SIZE = 26
FPS = 30
WORDS_PER_SEC = 2.6     # only used by the 'silent' backend to fake durations
PAD = 40                # px padding around the code on the canvas
GAP = 36                # px between the code column and the state panel
PANEL_PAD = 22          # inner padding of the state panel
PANEL_BG = "#1e1f1c"    # state-panel background (a touch off from the code bg)
COL_HEADER = "#75715e"  # muted grey for the panel header / "(no state)"
COL_NAME = "#a6e22e"    # variable names
COL_VALUE = "#f8f8f2"   # variable values
MAXVAL = 42             # truncate a value's repr to this many chars
CAP_PAD = 24            # inner padding of the caption band
CAP_GAP = 10            # px between wrapped caption lines
COL_CAPTION = "#e8e8e8" # caption text
COL_RULE = "#3a3b36"    # thin rule above the caption band
TYPE_CPF = 2            # characters typed per frame in --typing mode
TYPE_MAXFRAMES = 60     # cap on typing frames per beat (long lines type faster)
AUDIO_AR = "44100"      # normalise all clips so concat -c copy is safe
AUDIO_AC = "2"

# Monospace font files to try for the PIL-drawn state panel (first hit wins).
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",   # Linux
    "/System/Library/Fonts/Menlo.ttc",                        # macOS
    "/System/Library/Fonts/Monaco.ttf",
    "/Library/Fonts/Menlo.ttc",
    "C:\\Windows\\Fonts\\consola.ttf",                        # Windows
]


# ---------------------------------------------------------------------------
# Parsing: split code from trailing #: narration, robustly (via tokenize, so a
# '#' inside a string literal is never mistaken for a comment).
# ---------------------------------------------------------------------------
@dataclass
class Marker:
    line_no: int        # 1-based source line carrying the #: narration
    text: str           # raw narration text (may contain {var} fields)
    has_code: bool      # False for comment-only (intro/outro) lines


@dataclass
class Beat:
    """A render-ready unit: one frame + one narration clip."""
    reveal_upto: int | None   # show code_lines[:reveal_upto]; None = all lines
    highlight: int | None     # 1-based line to highlight; None = no highlight
    narration: str            # already interpolated
    state: dict               # {name: repr} for the panel (may be empty)


def parse(source: str):
    lines = source.splitlines()
    comments = {}  # 1-based line -> (comment_start_col, comment_text)
    toks = tokenize.generate_tokens(io.StringIO(source).readline)
    try:
        for tok in toks:
            if tok.type == tokenize.COMMENT:
                comments[tok.start[0]] = (tok.start[1], tok.string)
    except tokenize.TokenError:
        pass  # tolerate incomplete input

    code_lines, markers = [], []
    for i, raw in enumerate(lines, start=1):
        narration = None
        if i in comments:
            col, text = comments[i]
            body = text[1:].lstrip()            # drop leading '#'
            marker_body = MARKER[1:]            # part of marker after '#'
            if body.startswith(marker_body):
                narration = body[len(marker_body):].strip()
                raw = raw[:col].rstrip()        # strip the narration comment
        code_lines.append(raw)
        if narration:
            markers.append(Marker(i, narration, has_code=bool(raw.strip())))
    return code_lines, markers


# ---------------------------------------------------------------------------
# Execution trace: run the snippet once under sys.settrace and record, in
# completion order, EVERY execution of every line. For each execution we snapshot
# the locals *after* that line runs — captured at the next line-event in the SAME
# frame (or the frame's return), so side effects of nested calls are included.
# Each step keeps two views of the locals: repr (for the panel) and str (for
# {var} interpolation in narration). First-execution state is just a derived view.
# ---------------------------------------------------------------------------
@dataclass
class Step:
    line_no: int
    disp: dict          # {name: repr-string, truncated}  -> panel
    text: dict          # {name: str(value)}              -> interpolation
    frame_id: int       # id() of the frame, to find the next step in same scope


def _fmt_value(v):
    try:
        s = repr(v)
    except Exception:
        s = f"<{type(v).__name__}>"
    return s if len(s) <= MAXVAL else s[: MAXVAL - 1] + "…"


def _is_data(name, val):
    if name.startswith("__"):
        return False
    if callable(val) or isinstance(val, type):
        return False
    if getattr(val, "__module__", None) and not isinstance(
        val, (int, float, complex, str, bytes, bool, list, tuple, dict, set)
    ):
        return False
    return True


def _snapshot(frame):
    disp, text = {}, {}
    for name, val in frame.f_locals.items():
        if not _is_data(name, val):
            continue
        disp[name] = _fmt_value(val)
        try:
            text[name] = str(val)
        except Exception:
            text[name] = disp[name]
    return disp, text


def trace_run(source, filename):
    """Return an ordered list of Step, one per line execution (completion order)."""
    try:
        code = compile(source, filename, "exec")
    except SyntaxError as e:
        print(f"  ! cannot trace (syntax error: {e}); panels will be empty.")
        return []
    steps = []
    pending = {}   # id(frame) -> lineno awaiting its post-state snapshot

    def close(frame):
        L = pending.get(id(frame))
        if L is not None:
            disp, text = _snapshot(frame)
            steps.append(Step(L, disp, text, id(frame)))

    def tracer(frame, event, arg):
        if frame.f_code.co_filename != filename:
            return tracer                # ignore library frames
        if event == "line":
            close(frame)
            pending[id(frame)] = frame.f_lineno
        elif event == "return":
            close(frame)
            pending.pop(id(frame), None)
        return tracer

    glb = {"__name__": "__main__", "__file__": filename}
    sys.settrace(tracer)
    try:
        exec(code, glb)
    except Exception as e:
        print(f"  ! snippet raised {type(e).__name__}: {e} "
              f"(state captured up to that point)")
    finally:
        sys.settrace(None)
    return steps


_FIELD = re.compile(r"\{([A-Za-z_]\w*)\}")


def interpolate(text, values):
    """Replace {name} with values[name] (str). Unknown fields are left as-is.
    Use {{ and }} for literal braces."""
    text = text.replace("{{", "\0L\0").replace("}}", "\0R\0")
    text = _FIELD.sub(lambda m: values.get(m.group(1), m.group(0)), text)
    return text.replace("\0L\0", "{").replace("\0R\0", "}")


def _mono_font_path():
    """First existing path from _FONT_CANDIDATES, or None."""
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _mono_font(size):
    path = _mono_font_path()
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def render_panel(vars_dict, width, height):
    """A fixed-size 'state' panel listing name = value pairs."""
    img = Image.new("RGB", (width, height), PANEL_BG)
    d = ImageDraw.Draw(img)
    font = _mono_font(FONT_SIZE)
    head = _mono_font(max(12, FONT_SIZE - 8))
    asc, desc = font.getmetrics()
    lh = asc + desc + 8
    x, y = PANEL_PAD, PANEL_PAD
    d.text((x, y), "STATE", font=head, fill=COL_HEADER)
    y += lh
    if not vars_dict:
        d.text((x, y), "(no state)", font=font, fill=COL_HEADER)
        return img
    for name, val in vars_dict.items():
        d.text((x, y), name, font=font, fill=COL_NAME)
        nw = d.textlength(name + " ", font=font)
        d.text((x + nw, y), f"= {val}", font=font, fill=COL_VALUE)
        y += lh
    return img


# ---------------------------------------------------------------------------
# Beat construction: turn markers + trace steps into render-ready Beats.
#   first mode  -> one beat per marked line, first execution, progressive reveal
#   every mode  -> one beat per execution (trace order), full code, highlight moves
# Interpolation of {var} in narration uses that step's values in both modes.
# ---------------------------------------------------------------------------
def loop_body_ranges(source):
    """Map each for/while header line -> (min, max) line of its body (not else)."""
    ranges = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ranges
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            body = node.body
            lo = min(s.lineno for s in body)
            hi = max(getattr(s, "end_lineno", s.lineno) for s in body)
            ranges[node.lineno] = (lo, hi)
    return ranges


def build_beats(code_lines, markers, steps, every, loop_ranges=None):
    loop_ranges = loop_ranges or {}
    code_marks = {m.line_no: m for m in markers if m.has_code}
    comment_marks = [m for m in markers if not m.has_code]

    def env_before(line_no):
        """Values from the last step that ran on a source line above this one."""
        env = {}
        for st in steps:
            if st.line_no < line_no:
                env = st.text
        return env

    if not every:
        first = {}  # line_no -> first Step for that line
        for st in steps:
            first.setdefault(st.line_no, st)
        beats = []
        for m in markers:
            if m.has_code:
                st = first.get(m.line_no)
                beats.append(Beat(
                    reveal_upto=m.line_no, highlight=m.line_no,
                    narration=interpolate(m.text, st.text if st else {}),
                    state=st.disp if st else {}))
            else:
                beats.append(Beat(
                    reveal_upto=m.line_no, highlight=None,
                    narration=interpolate(m.text, env_before(m.line_no)),
                    state={}))
        return beats

    # every-execution mode: drive beats from the trace, full code always shown.
    exec_beats = []
    for idx, st in enumerate(steps):
        m = code_marks.get(st.line_no)
        if not m:
            continue
        if st.line_no in loop_ranges:
            # Skip the loop header's final evaluation (the one that exits): its
            # next same-frame step lands outside the loop body.
            lo, hi = loop_ranges[st.line_no]
            nxt = next((s for s in steps[idx + 1:] if s.frame_id == st.frame_id), None)
            if nxt is None or not (lo <= nxt.line_no <= hi):
                continue
        exec_beats.append(Beat(None, st.line_no, interpolate(m.text, st.text), st.disp))

    # Slot comment-only markers by source position; interpolate each with the
    # state that exists just before its line runs.
    beats, ci = [], 0
    for eb in exec_beats:
        while ci < len(comment_marks) and comment_marks[ci].line_no <= eb.highlight:
            cm = comment_marks[ci]
            beats.append(Beat(None, None, interpolate(cm.text, env_before(cm.line_no)), {}))
            ci += 1
        beats.append(eb)
    for cm in comment_marks[ci:]:                     # trailing outro comments
        beats.append(Beat(None, None, interpolate(cm.text, env_before(cm.line_no)), {}))
    return beats


# ---------------------------------------------------------------------------
# Frame rendering: render onto a fixed-size canvas so every frame shares one
# resolution (required for clean concat).
# ---------------------------------------------------------------------------
def _render_code(code: str, hl_lines):
    if not code.strip():
        code = " "  # PIL cannot encode a zero-size image
    # Prefer a concrete font *file* over FONT_NAME's by-name OS lookup: pygments'
    # ImageFormatter loads a path directly (os.path.isfile check in FontManager),
    # which is portable across OSes that don't happen to have a font installed
    # under that exact name (e.g. "DejaVu Sans Mono" isn't a stock macOS font).
    fmt = ImageFormatter(
        font_name=_mono_font_path() or FONT_NAME, font_size=FONT_SIZE, style=STYLE,
        line_numbers=False, hl_lines=hl_lines, image_pad=0, line_pad=6,
    )
    png = highlight(code, PythonLexer(), fmt)
    return Image.open(io.BytesIO(png)).convert("RGB")


def _even(n):
    return (n + 1) // 2 * 2                        # libx264 needs even dims


def _wrap(text, font, max_w):
    meas = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if cur and meas.textlength(trial, font=font) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [""]


@dataclass
class Canvas:
    W: int
    H: int
    code_w: int
    code_h: int
    panel_w: int
    cap_h: int
    bg: str
    captions: list       # per-beat list of wrapped caption lines (or None)


def plan_canvas(code_lines, beats, show_panel, subtitles):
    bg = get_style_by_name(STYLE).background_color or "#000000"
    full = _render_code("\n".join(code_lines), hl_lines=[])
    code_w, code_h = full.width, full.height

    panel_w = 0
    if show_panel:
        font = _mono_font(FONT_SIZE)
        meas = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        longest = max(
            (meas.textlength(f"{n} = {v}", font=font)
             for b in beats for n, v in b.state.items()), default=0)
        panel_w = int(max(240, longest + 2 * PANEL_PAD))

    W = _even(PAD + code_w + (GAP + panel_w if panel_w else 0) + PAD)

    captions, cap_h = None, 0
    if subtitles:
        cfont = _mono_font(max(14, FONT_SIZE - 4))
        asc, desc = cfont.getmetrics()
        clh = asc + desc + CAP_GAP
        wrap_w = W - 2 * PAD
        captions = [_wrap(b.narration, cfont, wrap_w) for b in beats]
        max_lines = max((len(c) for c in captions), default=1)
        cap_h = 2 * CAP_PAD + max_lines * clh

    H = _even(PAD + code_h + PAD + cap_h)
    return Canvas(W, H, code_w, code_h, panel_w, cap_h, bg, captions)


def _draw_caption(canvas, cv, lines):
    d = ImageDraw.Draw(canvas)
    top = cv.H - cv.cap_h
    d.line([(PAD, top), (cv.W - PAD, top)], fill=COL_RULE, width=2)
    cfont = _mono_font(max(14, FONT_SIZE - 4))
    asc, desc = cfont.getmetrics()
    clh = asc + desc + CAP_GAP
    y = top + CAP_PAD
    for ln in lines:
        w = d.textlength(ln, font=cfont)
        d.text(((cv.W - w) / 2, y), ln, font=cfont, fill=COL_CAPTION)
        y += clh


def compose(cv, code_text, hl_lines, state, caption_lines, path):
    """Render one full frame onto the fixed canvas and save it."""
    canvas = Image.new("RGB", (cv.W, cv.H), cv.bg)
    canvas.paste(_render_code(code_text, hl_lines=hl_lines), (PAD, PAD))
    if cv.panel_w:
        canvas.paste(render_panel(state, cv.panel_w, cv.code_h),
                     (PAD + cv.code_w + GAP, PAD))
    if caption_lines is not None:
        _draw_caption(canvas, cv, caption_lines)
    canvas.save(path)
    return path


def typing_frames(cv, base_lines, new_lines, state, caption_lines, outdir, tag):
    """Frames that type `new_lines` char-by-char after `base_lines`. No highlight."""
    stream = "\n".join(new_lines)
    total = len(stream)
    if not stream.strip():
        return []
    step = max(TYPE_CPF, -(-total // TYPE_MAXFRAMES))   # ceil division cap
    base = "\n".join(base_lines)
    sub = os.path.join(outdir, f"type_{tag}")
    os.makedirs(sub, exist_ok=True)
    frames, i = [], 0
    for m in range(step, total, step):                 # stop before full (hold shows full)
        typed = stream[:m]
        code = (base + "\n" + typed) if base else typed
        frames.append(compose(cv, code, [], state, caption_lines,
                              os.path.join(sub, f"{i:03d}.png")))
        i += 1
    return frames


# ---------------------------------------------------------------------------
# TTS backends. Each takes (text, out_stem) and returns a path to an audio file.
# make_clip re-encodes whatever comes back (wav / aiff / mp3) to AAC, so the
# container format a backend emits does not matter.
# ---------------------------------------------------------------------------
def synth_say(text, out):          # macOS built-in
    aiff = out + ".aiff"
    subprocess.run(["say", "-o", aiff, text], check=True)
    return aiff


def synth_silent(text, out):       # timing stand-in; runs anywhere
    dur = max(1.2, len(text.split()) / WORDS_PER_SEC)
    wav = out + ".wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "anullsrc=r=44100:cl=stereo", "-t", f"{dur:.2f}", wav],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return wav


def synth_piper(text, out):
    """Local neural TTS via the Piper CLI (`pip install piper-tts`).

    Configure with environment variables:
      PIPER_MODEL         voice name (auto-downloaded, e.g. en_US-lessac-medium)
                          or a path to a local .onnx file  [default: en_US-lessac-medium]
      PIPER_LENGTH_SCALE  speaking rate; >1 slower, <1 faster  [default: 1.0]
      PIPER_BIN           path to the piper binary            [default: "piper"]
      PIPER_DATA_DIR      where to find/download voices (optional)
    """
    if shutil.which(os.environ.get("PIPER_BIN", "piper")) is None:
        sys.exit("piper not found. Install with:  pip install piper-tts\n"
                 "then set PIPER_MODEL (e.g. en_US-lessac-medium).")
    model = os.environ.get("PIPER_MODEL", "en_US-lessac-medium")
    wav = out + ".wav"
    cmd = [os.environ.get("PIPER_BIN", "piper"),
           "--model", model, "--output_file", wav]
    if os.environ.get("PIPER_LENGTH_SCALE"):
        cmd += ["--length_scale", os.environ["PIPER_LENGTH_SCALE"]]
    if os.environ.get("PIPER_DATA_DIR"):
        cmd += ["--data-dir", os.environ["PIPER_DATA_DIR"],
                "--download-dir", os.environ["PIPER_DATA_DIR"]]
    proc = subprocess.run(cmd, input=text.encode(),
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        sys.exit(f"piper failed: {proc.stderr.decode()[:400]}")
    return wav


def synth_elevenlabs(text, out):
    """Cloud TTS via the ElevenLabs REST API (no SDK dependency).

    Environment variables:
      ELEVENLABS_API_KEY  required — from elevenlabs.io → Developers → API Keys
      ELEVENLABS_VOICE_ID voice id  [default: 21m00Tcm4TlvDq8ikWAM  (Rachel)]
      ELEVENLABS_MODEL    model id  [default: eleven_multilingual_v2;
                          use eleven_flash_v2_5 for cheaper/low-latency]
      ELEVENLABS_FORMAT   output_format  [default: mp3_44100_128]
    Text-to-speech is billed at one credit per character.
    """
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("Set ELEVENLABS_API_KEY for the elevenlabs backend "
                 "(elevenlabs.io → Developers → API Keys).")
    voice = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    model = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")
    fmt = os.environ.get("ELEVENLABS_FORMAT", "mp3_44100_128")
    url = (f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
           f"?output_format={fmt}")
    body = json.dumps({
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    })
    mp3 = out + ".mp3"
    try:
        with urllib.request.urlopen(req) as resp, open(mp3, "wb") as fh:
            shutil.copyfileobj(resp, fh)
    except urllib.error.HTTPError as e:
        sys.exit(f"ElevenLabs error {e.code}: {e.read().decode()[:400]}")
    return mp3


BACKENDS = {
    "say": synth_say,
    "silent": synth_silent,
    "piper": synth_piper,
    "elevenlabs": synth_elevenlabs,
}


# ---------------------------------------------------------------------------
# Assembly: one still+audio clip per beat, then concat. Audio length drives
# clip length (-shortest), so narration and visuals stay in sync for free.
# ---------------------------------------------------------------------------
def make_clip(frame, audio, out):
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", frame, "-i", audio,
         "-tune", "stillimage", "-c:v", "libx264", "-r", str(FPS),
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
         "-ar", AUDIO_AR, "-ac", AUDIO_AC, "-shortest", out],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_typing_clip(frames_dir, n_frames, out):
    """A silent clip from a PNG sequence (dir/000.png …) at FPS."""
    subprocess.run(
        ["ffmpeg", "-y", "-framerate", str(FPS),
         "-i", os.path.join(frames_dir, "%03d.png"),
         "-f", "lavfi", "-i", f"anullsrc=r={AUDIO_AR}:cl=stereo",
         "-c:v", "libx264", "-r", str(FPS), "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-ar", AUDIO_AR, "-ac", AUDIO_AC,
         "-shortest", out],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def concat(clips, out, workdir):
    listfile = os.path.join(workdir, "clips.txt")
    with open(listfile, "w") as fh:
        for c in clips:
            fh.write(f"file '{os.path.abspath(c)}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
         "-c", "copy", out],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build(source_path, out_path, tts, trace=True, every=False,
          subtitles=False, typing=False):
    """
    Render an annotated Python snippet into a narrated screencast video.

    Parses `source_path` for trailing ``#:`` narration comments, optionally
    executes it to capture a per-line variable state, and assembles one
    still-frame-plus-narration clip per beat into `out_path` with ffmpeg.

    Parameters
    ----------
    source_path :
        Path to the annotated, still-valid Python snippet to narrate.
    out_path :
        Path the assembled MP4 is written to.
    tts :
        Name of a registered TTS backend (a key of `BACKENDS`): one of
        `"say"`, `"silent"`, `"piper"`, `"elevenlabs"`.
    trace :
        Execute the snippet under `sys.settrace` to capture the state panel.
        Required for `every=True`.
    every :
        Emit one beat per *execution* of a marked line (animates loops
        iteration by iteration) instead of one beat per marked line.
    subtitles :
        Burn the narration text onto each frame as a caption.
    typing :
        Type newly revealed lines character-by-character (first-execution
        mode only; has no effect when `every=True`).

    Examples
    --------
    ```python
    from snippet_cast import build

    build("fib.py", "out.mp4", tts="silent", subtitles=True)
    ```

    See Also
    --------
    [](`snippet_cast.screencast.main`)
    """
    synth = BACKENDS[tts]
    source = open(source_path).read()
    code_lines, markers = parse(source)
    if not markers:
        sys.exit(f"No narration found. Add trailing '{MARKER} ...' comments.")
    steps = trace_run(source, source_path) if trace else []
    loop_ranges = loop_body_ranges(source) if every else {}
    beats = build_beats(code_lines, markers, steps, every=every, loop_ranges=loop_ranges)

    work = tempfile.mkdtemp(prefix="screencast_")
    mode = "every-exec" if every else "first-exec"
    extras = "".join(x for x in [" +subs" if subtitles else "",
                                 " +typing" if typing else ""])
    print(f"{len(beats)} beats -> {out_path}  "
          f"(backend: {tts}, trace: {'on' if trace else 'off'}, {mode}{extras})")
    cv = plan_canvas(code_lines, beats, show_panel=trace, subtitles=subtitles)

    audio_cache = {}   # identical narration (e.g. an un-interpolated loop line) -> reuse
    clips = []
    prev_upto = 0
    for k, beat in enumerate(beats):
        caption = cv.captions[k] if cv.captions is not None else None

        # Typing pre-roll for newly revealed lines (first-exec mode only).
        if typing and beat.reveal_upto is not None:
            new_lines = code_lines[prev_upto:beat.reveal_upto]
            tf = typing_frames(cv, code_lines[:prev_upto], new_lines,
                               beat.state, caption, work, tag=f"{k:03d}")
            if tf:
                tclip = os.path.join(work, f"type_{k:03d}.mp4")
                make_typing_clip(os.path.dirname(tf[0]), len(tf), tclip)
                clips.append(tclip)

        # Hold frame + narration.
        n = beat.reveal_upto if beat.reveal_upto is not None else len(code_lines)
        hold = compose(cv, "\n".join(code_lines[:n]),
                       [beat.highlight] if beat.highlight else [],
                       beat.state, caption, os.path.join(work, f"hold_{k:03d}.png"))
        if beat.narration not in audio_cache:
            audio_cache[beat.narration] = synth(
                beat.narration, os.path.join(work, f"seg_{k:03d}"))
        nclip = os.path.join(work, f"clip_{k:03d}.mp4")
        make_clip(hold, audio_cache[beat.narration], nclip)
        clips.append(nclip)

        if beat.reveal_upto is not None:
            prev_upto = max(prev_upto, beat.reveal_upto)
        print(f"  [{k+1}/{len(beats)}] {beat.narration[:60]}")

    concat(clips, out_path, work)
    shutil.rmtree(work, ignore_errors=True)
    print("done.")


def main():
    """Console-script entry point (`snippet-cast`): parses argv and calls `build`."""
    ap = argparse.ArgumentParser(description="Narrated screencast from an annotated .py snippet.")
    ap.add_argument("input", help="annotated Python file")
    ap.add_argument("-o", "--output", default="out.mp4")
    ap.add_argument("--tts", choices=list(BACKENDS), default="say")
    ap.add_argument("--no-trace", action="store_true",
                    help="don't execute the snippet; skip the state panel")
    ap.add_argument("--every", action="store_true",
                    help="one beat per execution of a line (animates loops); "
                         "full code is shown and the highlight follows execution")
    ap.add_argument("--subtitles", action="store_true",
                    help="burn the narration text as a caption (handy with --tts silent)")
    ap.add_argument("--typing", action="store_true",
                    help="type newly revealed lines character-by-character "
                         "(first-execution mode only)")
    args = ap.parse_args()
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH.")
    if args.every and args.no_trace:
        sys.exit("--every needs execution; drop --no-trace.")
    if args.typing and args.every:
        print("note: --typing has no effect with --every (full code is already shown).")
    build(args.input, args.output, args.tts,
          trace=not args.no_trace, every=args.every,
          subtitles=args.subtitles, typing=args.typing)


if __name__ == "__main__":
    main()
