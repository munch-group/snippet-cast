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

TWO-PASS NARRATION: split a ``#:`` narration into "writing / walkthrough" text
with a ``/``:

    def fib(n):    #: We're about to write fib. / fib takes one argument, n.

If ANY marker in the file uses ``/``, the whole video becomes two full,
sequential passes: pass 1 opens on a blank canvas and types the entire
snippet in from scratch, narrating each line with the text BEFORE ``/`` as
it's typed (no state panel, no highlight — nothing has executed yet); pass 2
then walks back through the same snippet from the top, narrating with the
text AFTER ``/`` — but the code pass 1 already typed stays fully on screen
throughout pass 2 (it is not hidden and re-revealed line by line); only the
highlight and state panel move, beat by beat. Either side may be empty: an
empty writing-pass text still types the line in, silently; an empty
walkthrough-pass text still highlights the line, holding briefly with no
narration. A file with no ``/`` anywhere is unaffected —
--typing/--typing-speed keep controlling that single pass as before. Not
supported together with --every.

CUSTOM NARRATION ORDER: give a ``#:`` line's narration a leading ``N)`` to
narrate/highlight it out of source-line order:

    def fib(n):          #: 3) We define fib, taking one argument, n.
        a, b = 0, 1      #: 1) Start from the first two Fibonacci numbers.
        for _ in range(n):  #: 2) Loop n times.

plays "Start...", "Loop...", "We define fib..." in that order, while the code
itself only ever reveals forward (jumping ahead to a later line reveals
everything up to it; a later beat for an earlier line just re-highlights code
already on screen). Numbering is per pass in two-pass narration — each side of
the ``/`` has its own independent order:

    def fib(n):    #: 1) writing-pass order / 2) walkthrough-pass order

Leave a side without any ``N)`` prefixes to keep it in default top-to-bottom
order; a pass may not mix numbered and unnumbered lines. Not supported
together with --every (there, beat order already follows execution, not
marker order).

MANUAL RECORDING WORKFLOW: instead of a TTS backend, you can narrate a
snippet in your own voice. `--export-script` prints the exact ordered,
numbered list of narration lines to read (in two-pass mode: every writing-pass
line, in order, then every walkthrough-pass line, in order — the same order
`--tts manual` will request them in). Record each numbered line as
`NNN.wav` (or .mp3/.m4a/.aiff/.flac/.ogg) in a directory, then render with
`--tts manual --manual-audio-dir DIR`.

JUPYTER: `pip install snippet-cast[jupyter]`, then in a notebook:

    %load_ext snippet_cast.magic

    %%snippet-cast -o out.mp4 --tts silent --subtitles
    def fib(n):             #: We define fib, taking one argument, n.
        a, b = 0, 1         #: Start from the first two Fibonacci numbers.
        for _ in range(n):  #: Loop n times.
            a, b = b, a + b #: Advance the pair; b becomes the running sum.
        return a            #: Return a — the nth Fibonacci number.
    result = fib(7)         #: Call fib with seven; result becomes {result}.

Same flags as the CLI (`--tts`, `--every`, `--subtitles`, `--typing`,
`--typing-speed`, `--pause`, `--no-trace`, `--export-script`, `--tts manual
--manual-audio-dir DIR`); `--tts` defaults to `silent` here instead of `say`,
and the rendered MP4 is displayed inline (`--embed` to base64-embed it in the
notebook instead of linking the file). See `snippet_cast.magic`.

USAGE (installed console script):
    snippet-cast input.py -o out.mp4 --tts say
    snippet-cast input.py -o out.mp4 --tts silent   # no audio backend needed
    snippet-cast loop.py  -o out.mp4 --every         # animate each iteration
    snippet-cast input.py -o out.mp4 --subtitles     # burn narration captions
    snippet-cast input.py -o out.mp4 --typing        # type each new line in
    snippet-cast input.py -o out.mp4 --typing --typing-speed 0.06  # slower typing
    snippet-cast input.py -o out.mp4 --pause 0.6     # breathing gap between beats
    snippet-cast input.py --export-script > script.txt        # narration to record
    snippet-cast input.py -o out.mp4 --tts manual \
        --manual-audio-dir recordings/                        # use recordings

Or run the module directly without installing the console script:
    python -m snippet_cast.screencast input.py -o out.mp4 --tts say

Proofing tip: --tts silent --subtitles gives a fast, voiceless preview with the
narration on screen, so you can check wording and pacing before rendering audio.

TTS backends (choose with --tts):
    say         macOS built-in (`say`). Zero install. Good enough for drafts.
    silent      Silence sized to the text length. Runs anywhere; pair with
                --subtitles to proof narration without generating audio.
    piper       Local neural TTS (`pip install piper-tts`). Offline, free.
                Config via PIPER_MODEL / PIPER_LENGTH_SCALE (see synth_piper),
                or the --piper-* flags, which take precedence.
    elevenlabs  Cloud neural TTS via REST. Set ELEVENLABS_API_KEY (and
                optionally ELEVENLABS_VOICE_ID / ELEVENLABS_MODEL). See SETUP.md.
                The --elevenlabs-* flags override these env vars.
    manual      Your own recordings, keyed by position — see MANUAL RECORDING
                WORKFLOW above. Requires --manual-audio-dir.
"""

import argparse
import ast
import io
import json
import math
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
TYPE_SPEED = 0.035      # default seconds to reveal each new character in --typing mode
TYPE_MAXFRAMES = 150    # absolute cap on typing frames per beat, so a slow speed
                        # or a very long line can't blow a beat up unboundedly
TWO_PASS_SEP = "/"      # splits a #: narration into "writing pass / walkthrough pass"
PART2_EMPTY_HOLD = 0.8  # seconds to hold a walkthrough-pass beat with no narration
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


def split_narration(text):
    """Split a #: narration on the first TWO_PASS_SEP into (part1, part2),
    each stripped — part1 narrates the writing pass, part2 the walkthrough
    pass. No separator present -> ("", text), so a file that never uses it
    is unaffected (whole text stays in part2, exactly today's behavior)."""
    if TWO_PASS_SEP in text:
        part1, _, part2 = text.partition(TWO_PASS_SEP)
        return part1.strip(), part2.strip()
    return "", text.strip()


_ORDER_RE = re.compile(r"^(\d+)\)\s*")


def _parse_order(text):
    """Strip a leading 'N) ' playback-order prefix from one pass's narration
    text. Returns (order:int|None, text) — None when `text` has no prefix
    (an empty string, e.g. an unused pass1 slot, also has no prefix)."""
    m = _ORDER_RE.match(text)
    if not m:
        return None, text
    return int(m.group(1)), text[m.end():].strip()


def order_markers(markers, texts):
    """Pair `markers` with parallel per-pass `texts` (post split_narration()
    for two-pass, or each marker's whole text for single-pass), strip any
    leading 'N) ' order prefix, and return new Markers (same line_no/has_code,
    text replaced by the stripped text) in PLAYBACK order.

    If every text in this pass carries a prefix, markers are sorted by that
    number (stable, so ties keep source order); if none do, markers are left
    in their given (source-line) order — today's default. A pass may not mix
    numbered and unnumbered lines — that's ambiguous, so it's a hard error."""
    parsed = [_parse_order(t) for t in texts]
    orders = [o for o, _ in parsed]
    numbered = [o is not None for o in orders]
    if any(numbered) and not all(numbered):
        sys.exit("Mix of numbered ('N) ...') and unnumbered '#:' narration in "
                 "one pass — number either all lines in that pass or none.")
    out = [Marker(m.line_no, t, m.has_code) for m, (_, t) in zip(markers, parsed)]
    if all(numbered):
        out = [m for _, m in sorted(zip(orders, out), key=lambda p: p[0])]
    return out


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
        revealed = 0   # high-water mark: markers may be given out of source
                        # order (see order_markers), so code only ever grows —
                        # never truncates what an earlier beat already showed.
        for m in markers:
            revealed = max(revealed, m.line_no)
            if m.has_code:
                st = first.get(m.line_no)
                beats.append(Beat(
                    reveal_upto=revealed, highlight=m.line_no,
                    narration=interpolate(m.text, st.text if st else {}),
                    state=st.disp if st else {}))
            else:
                beats.append(Beat(
                    reveal_upto=revealed, highlight=None,
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


def _two_pass_beats(code_lines, markers, steps):
    """Split every marker's text on TWO_PASS_SEP and build both beat
    sequences via the unmodified build_beats(): pass 1 ('writing') gets
    steps=[] so every beat's state is {} and {var} fields are left literal
    (nothing has executed yet); pass 2 ('walkthrough') gets the real steps,
    same per-beat highlight/state/narration as single-pass first-exec mode.
    (_render_two_pass() ignores each beat's reveal_upto when rendering pass 2,
    since pass 1 already typed the code onto the canvas — only highlight and
    state move.)

    Each pass may independently carry a leading 'N) ' order prefix on every
    one of its texts (order_markers()) — e.g. '#: 1) text / 4) text' — to
    narrate that pass out of source-line order; a bare '#: text / 4) text'
    leaves pass 1 in default (top-to-bottom) order while pass 2 is reordered."""
    parts = [split_narration(m.text) for m in markers]
    m1 = order_markers(markers, [p[0] for p in parts])
    m2 = order_markers(markers, [p[1] for p in parts])
    beats1 = build_beats(code_lines, m1, steps=[], every=False)
    beats2 = build_beats(code_lines, m2, steps=steps, every=False)
    return beats1, beats2


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


def typing_frames(cv, base_lines, new_lines, state, caption_lines, outdir, tag,
                  typing_speed=TYPE_SPEED, n_frames=None, reach_full=False):
    """Frames that type `new_lines` char-by-char after `base_lines`. No highlight.

    `typing_speed` is the target seconds-per-character; the number of frames
    is derived from that and FPS (capped by TYPE_MAXFRAMES), then the chars
    are spread evenly across the frames — so a slow speed on a short line
    holds frames instead of needing one unique frame per character.

    `n_frames`, if given, overrides the typing_speed-derived frame count
    entirely (two-pass mode sizes frames to a real narration's duration
    instead). `reach_full`, if True, makes the LAST frame show the complete
    `new_lines` text instead of stopping just short of it — used when no
    separate hold-at-100% frame follows (unlike legacy --typing).

    When `base_lines` is empty — nothing is on screen yet, i.e. this is the
    very start of the recording — frame 0 shows a blank canvas (0 characters)
    and the count ramps up to the same end point the non-blank case reaches,
    instead of jumping straight to 1+ characters already typed.
    """
    stream = "\n".join(new_lines)
    total = len(stream)
    if total < 2 or not stream.strip():
        return []
    if n_frames is None:
        n_frames = min(TYPE_MAXFRAMES, max(1, round(total * typing_speed * FPS)))
    base = "\n".join(base_lines)
    start_blank = not base
    if start_blank:
        n_frames = max(n_frames, 2)   # need >=2 frames to ramp from 0 to end_frac
    end_frac = 1.0 if reach_full else n_frames / (n_frames + 1)
    sub = os.path.join(outdir, f"type_{tag}")
    os.makedirs(sub, exist_ok=True)
    frames = []
    for i in range(n_frames):                # stop before full (hold shows full)
        if start_blank:
            m = round((i / (n_frames - 1)) * end_frac * total)
        else:
            denom = n_frames if reach_full else n_frames + 1
            m = max(1, round((i + 1) * total / denom))
        typed = stream[:m]
        code = (base + "\n" + typed) if base else typed
        frames.append(compose(cv, code, [], state, caption_lines,
                              os.path.join(sub, f"{i:03d}.png")))
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

    Piper does not auto-download voices; fetch one first:
        python -m piper.download_voices en_US-lessac-medium

    Configure with environment variables, or the equivalent --piper-* CLI flag
    (a flag, when given, overrides the environment variable):
      PIPER_MODEL         / --piper-model         voice name (e.g. en_US-lessac-medium)
                          or a path to a local .onnx file       [default: en_US-lessac-medium]
      PIPER_LENGTH_SCALE  / --piper-length-scale   speaking rate; >1 slower, <1 faster  [default: 1.0]
      PIPER_BIN           / --piper-bin            path to the piper binary  [default: "piper"]
      PIPER_DATA_DIR      / --piper-data-dir       directory to search for the voice's
                          .onnx/.onnx.json; must match where you downloaded it  [default: cwd]
    """
    if shutil.which(os.environ.get("PIPER_BIN", "piper")) is None:
        sys.exit("piper not found. Install with:  pip install piper-tts\n"
                 "then fetch a voice: python -m piper.download_voices en_US-lessac-medium")
    model = os.environ.get("PIPER_MODEL", "en_US-lessac-medium")
    wav = out + ".wav"
    cmd = [os.environ.get("PIPER_BIN", "piper"),
           "--model", model, "--output_file", wav]
    if os.environ.get("PIPER_LENGTH_SCALE"):
        cmd += ["--length_scale", os.environ["PIPER_LENGTH_SCALE"]]
    if os.environ.get("PIPER_DATA_DIR"):
        cmd += ["--data-dir", os.environ["PIPER_DATA_DIR"]]
    proc = subprocess.run(cmd, input=text.encode(),
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        err = proc.stderr.decode()
        if "Unable to find voice" in err:
            download_dir = os.environ.get("PIPER_DATA_DIR")
            hint = f" --download-dir {download_dir}" if download_dir else ""
            sys.exit(f"piper: voice '{model}' not found. Fetch it first:\n"
                     f"  python -m piper.download_voices {model}{hint}")
        sys.exit(f"piper failed: {err[:400]}")
    return wav


def synth_elevenlabs(text, out):
    """Cloud TTS via the ElevenLabs REST API (no SDK dependency).

    Environment variables, or the equivalent --elevenlabs-* CLI flag (a flag,
    when given, overrides the environment variable):
      ELEVENLABS_API_KEY  / --elevenlabs-api-key   required — from elevenlabs.io ->
                          Developers -> API Keys
      ELEVENLABS_VOICE_ID / --elevenlabs-voice-id  voice id
                          [default: 21m00Tcm4TlvDq8ikWAM  (Rachel)]
      ELEVENLABS_MODEL    / --elevenlabs-model     model id  [default: eleven_multilingual_v2;
                          use eleven_flash_v2_5 for cheaper/low-latency]
      ELEVENLABS_FORMAT   / --elevenlabs-format    output_format  [default: mp3_44100_128]
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


def make_manual_backend(audio_dir):
    """Return a synth(text, out) -> path callable that serves the Nth
    pre-recorded audio file (1-based, in call order) from `audio_dir`, named
    001.<ext>, 002.<ext>, ... in the exact order export_script() printed
    them. A fresh closure per build() call, so no counter state leaks across
    repeated programmatic build() calls in one process."""
    counter = {"n": 0}

    def synth_manual(text, out):
        counter["n"] += 1
        stem = f"{counter['n']:03d}"
        for ext in (".wav", ".mp3", ".m4a", ".aiff", ".flac", ".ogg"):
            candidate = os.path.join(audio_dir, stem + ext)
            if os.path.exists(candidate):
                return candidate
        sys.exit(f"manual backend: missing recording {stem}.* in {audio_dir!r} "
                 f"(narration: {text!r}). Run --export-script for the numbered "
                 f"list this needs to match.")
    return synth_manual


BACKENDS = {
    "say": synth_say,
    "silent": synth_silent,
    "piper": synth_piper,
    "elevenlabs": synth_elevenlabs,
    "manual": None,   # special-cased in build(); requires --manual-audio-dir
}


# ---------------------------------------------------------------------------
# Assembly: one still+audio clip per beat, then concat. Audio length drives
# clip length (-shortest), so narration and visuals stay in sync for free.
# ---------------------------------------------------------------------------
def probe_duration(path):
    """Duration of `path` in seconds via ffprobe — sizes a pass-1 'writing'
    clip's typing-frame count to its real narration length."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            check=True, capture_output=True, text=True).stdout.strip()
        return float(out)
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
        sys.exit(f"could not read duration of {path!r} via ffprobe: {e}")


def make_clip(frame, audio, out):
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", frame, "-i", audio,
         "-tune", "stillimage", "-c:v", "libx264", "-r", str(FPS),
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
         "-ar", AUDIO_AR, "-ac", AUDIO_AC, "-shortest", out],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_pause_clip(frame, duration, out):
    """A silent clip holding `frame` for `duration` seconds — the gap between
    one beat's narration ending and the next beat's frame/narration starting."""
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", frame,
         "-f", "lavfi", "-i", f"anullsrc=r={AUDIO_AR}:cl=stereo",
         "-t", f"{duration:.2f}",
         "-tune", "stillimage", "-c:v", "libx264", "-r", str(FPS),
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
         "-ar", AUDIO_AR, "-ac", AUDIO_AC, "-shortest", out],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_typing_clip(frames_dir, n_frames, out, audio=None):
    """A clip from a PNG sequence (dir/000.png …) at FPS, muxed with `audio`
    (a real narration file) or silence if `audio` is None."""
    audio_in = ["-i", audio] if audio else ["-f", "lavfi", "-i", f"anullsrc=r={AUDIO_AR}:cl=stereo"]
    subprocess.run(
        ["ffmpeg", "-y", "-framerate", str(FPS),
         "-i", os.path.join(frames_dir, "%03d.png"), *audio_in,
         "-c:v", "libx264", "-r", str(FPS), "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-ar", AUDIO_AR, "-ac", AUDIO_AC,
         "-shortest", out],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_pass1_code_clip(cv, base_lines, new_lines, caption_lines, duration,
                         outdir, tag, audio=None):
    """One pass-1 'writing' clip: types `new_lines` in after `base_lines`,
    reaching 100% typed on the last frame (two-pass mode has no separate
    hold-at-100% frame after typing), muxed with `audio` (real narration) or
    silent if `audio` is None. `duration` paces the typing: real audio
    length when `audio` is given (frame count is NOT capped by
    TYPE_MAXFRAMES — narration audio must never be truncated), else
    `len(new_lines joined) * typing_speed` when writing silently (capped by
    TYPE_MAXFRAMES, same safety valve as legacy --typing). Frame count is
    ceil(duration * FPS) so the clip is never shorter than `audio`;
    make_typing_clip's -shortest then trims at most one frame of excess
    video, never truncating narration. Returns None if `new_lines` has < 2
    characters (nothing worth animating — caller falls back to a static
    hold)."""
    stream = "\n".join(new_lines)
    if len(stream) < 2 or not stream.strip():
        return None
    frames_target = duration * FPS
    if audio is None:
        frames_target = min(TYPE_MAXFRAMES, frames_target)
    n_frames = max(1, math.ceil(frames_target))
    frames = typing_frames(cv, base_lines, new_lines, {}, caption_lines,
                           outdir, tag, n_frames=n_frames, reach_full=True)
    if not frames:
        return None
    clip = os.path.join(outdir, f"type_{tag}.mp4")
    make_typing_clip(os.path.dirname(frames[0]), len(frames), clip, audio=audio)
    return clip


def concat(clips, out, workdir):
    listfile = os.path.join(workdir, "clips.txt")
    with open(listfile, "w") as fh:
        for c in clips:
            fh.write(f"file '{os.path.abspath(c)}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
         "-c", "copy", out],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _cached_synth(synth, audio_cache, text, work, tag):
    """audio_cache-deduped synth call: identical narration text (e.g. an
    un-interpolated loop line, or the same line reused across passes) is
    synthesized once and reused. Same semantics as the legacy loop's inline
    cache check, factored out because two-pass rendering needs it at
    multiple call sites."""
    if text not in audio_cache:
        audio_cache[text] = synth(text, os.path.join(work, f"seg_{tag}"))
    return audio_cache[text]


def _render_two_pass(code_lines, beats1, beats2, cv, work, synth, audio_cache,
                     typing_speed, pause):
    """Render two-pass mode's clips and return the ordered clip-path list
    (all of pass 1, then all of pass 2) ready for concat()."""
    clips = []
    prev_upto = 0
    for k, beat in enumerate(beats1):
        caption = cv.captions[k] if cv.captions is not None else None
        new_lines = code_lines[prev_upto:beat.reveal_upto]
        stream = "\n".join(new_lines)

        if len(stream) >= 2 and stream.strip():
            if beat.narration:
                audio = _cached_synth(synth, audio_cache, beat.narration, work, f"p1a_{k:03d}")
                duration = probe_duration(audio)
            else:
                audio, duration = None, len(stream) * typing_speed
            clip = make_pass1_code_clip(cv, code_lines[:prev_upto], new_lines,
                                        caption, duration, work, f"p1_{k:03d}", audio=audio)
            if clip:
                clips.append(clip)
        elif beat.narration:
            hold = compose(cv, "\n".join(code_lines[:beat.reveal_upto]), [], {},
                           caption, os.path.join(work, f"p1_hold_{k:03d}.png"))
            audio = _cached_synth(synth, audio_cache, beat.narration, work, f"p1b_{k:03d}")
            clip = os.path.join(work, f"p1_clip_{k:03d}.mp4")
            make_clip(hold, audio, clip)
            clips.append(clip)
        # else: no new code and nothing to say — no clip for this beat.

        prev_upto = max(prev_upto, beat.reveal_upto)
        print(f"  [pass1 {k+1}/{len(beats1)}] {beat.narration[:60] or '(silent)'}")

    off = len(beats1)
    # Pass 1 already typed everything up to the last marked line — pass 2
    # keeps that code on screen throughout instead of re-hiding and
    # progressively re-revealing it; only the highlight/state panel move.
    final_upto = beats1[-1].reveal_upto
    for k, beat in enumerate(beats2):
        caption = cv.captions[off + k] if cv.captions is not None else None
        hold = compose(cv, "\n".join(code_lines[:final_upto]),
                       [beat.highlight] if beat.highlight else [],
                       beat.state, caption, os.path.join(work, f"p2_hold_{k:03d}.png"))
        clip = os.path.join(work, f"p2_clip_{k:03d}.mp4")
        if beat.narration:
            audio = _cached_synth(synth, audio_cache, beat.narration, work, f"p2_{k:03d}")
            make_clip(hold, audio, clip)
        else:
            make_pause_clip(hold, PART2_EMPTY_HOLD, clip)
        clips.append(clip)

        if pause > 0 and k < len(beats2) - 1:
            pclip = os.path.join(work, f"p2_pause_{k:03d}.mp4")
            make_pause_clip(hold, pause, pclip)
            clips.append(pclip)
        print(f"  [pass2 {k+1}/{len(beats2)}] {beat.narration[:60] or '(silent)'}")

    return clips


def build(source_path, out_path, tts, trace=True, every=False,
          subtitles=False, typing=False, typing_speed=TYPE_SPEED, pause=0.0,
          manual_audio_dir=None):
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
        `"say"`, `"silent"`, `"piper"`, `"elevenlabs"`, `"manual"`.
    trace :
        Execute the snippet under `sys.settrace` to capture the state panel.
        Required for `every=True`.
    every :
        Emit one beat per *execution* of a marked line (animates loops
        iteration by iteration) instead of one beat per marked line. Not
        supported together with two-pass narration (a `/` in some marker).
    subtitles :
        Burn the narration text onto each frame as a caption.
    typing :
        Type newly revealed lines character-by-character (first-execution
        mode only; has no effect when `every=True`, and no effect in
        two-pass mode — the writing pass always types).
    typing_speed :
        Seconds to reveal each newly typed character when `typing=True`, or
        when the writing pass has no narration to time itself to
        [default: `TYPE_SPEED`]. Larger is slower.
    pause :
        Seconds of silence to hold on each beat's frame after its narration
        finishes, before the next beat begins. `0` (default) cuts directly
        from one beat's narration to the next. In two-pass mode this only
        applies to the walkthrough pass.
    manual_audio_dir :
        Directory of pre-recorded audio files for `tts="manual"`, named
        001.wav, 002.wav, ... (or .mp3/.m4a/.aiff/.flac/.ogg) matching
        `export_script()`'s numbering.

    Narration split into two passes
    --------------------------------
    A `#:` narration containing a `/` is split into "writing pass / walkthrough
    pass" text (see `split_narration`). If ANY marker in the file uses `/`,
    the whole video becomes two full, sequential passes: first the entire
    snippet is typed in (narrated by each line's part before `/`, no state
    panel, no highlight), then the existing walkthrough plays again from the
    top (narrated by the text after `/`, exactly today's single-pass
    mechanics). A file with no `/` anywhere renders exactly as before.

    Examples
    --------
    ```python
    from snippet_cast import build

    build("fib.py", "out.mp4", tts="silent", subtitles=True)
    ```

    See Also
    --------
    [](`snippet_cast.screencast.main`)
    [](`snippet_cast.screencast.export_script`)
    """
    if tts == "manual":
        if not manual_audio_dir:
            sys.exit("--tts manual requires --manual-audio-dir DIR.")
        synth = make_manual_backend(manual_audio_dir)
    else:
        synth = BACKENDS[tts]

    source = open(source_path).read()
    code_lines, markers = parse(source)
    if not markers:
        sys.exit(f"No narration found. Add trailing '{MARKER} ...' comments.")

    two_pass = any(TWO_PASS_SEP in m.text for m in markers)
    if two_pass and every:
        sys.exit("Two-pass narration ('/' in a marker) isn't supported with "
                 "--every; remove the '/' or drop --every.")
    if two_pass and typing:
        print("note: --typing has no effect in two-pass mode ('/' in a "
              "marker) — the writing pass always types the new code in.")
    if not two_pass:
        if every and any(_parse_order(m.text)[0] is not None for m in markers):
            sys.exit("Numbered 'N) ' order prefixes require first-exec mode; "
                     "drop --every or remove the prefixes.")
        markers = order_markers(markers, [m.text for m in markers])

    steps = trace_run(source, source_path) if trace else []
    work = tempfile.mkdtemp(prefix="screencast_")

    if two_pass:
        beats1, beats2 = _two_pass_beats(code_lines, markers, steps)
        print(f"{len(beats1)+len(beats2)} beats ({len(beats1)} pass-1 + "
              f"{len(beats2)} pass-2) -> {out_path}  (backend: {tts}, "
              f"trace: {'on' if trace else 'off'}, two-pass)")
        cv = plan_canvas(code_lines, beats1 + beats2, show_panel=trace,
                         subtitles=subtitles)
        audio_cache = {}
        clips = _render_two_pass(code_lines, beats1, beats2, cv, work, synth,
                                 audio_cache, typing_speed, pause)
        concat(clips, out_path, work)
        shutil.rmtree(work, ignore_errors=True)
        print("done.")
        return

    loop_ranges = loop_body_ranges(source) if every else {}
    beats = build_beats(code_lines, markers, steps, every=every, loop_ranges=loop_ranges)
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
                               beat.state, caption, work, tag=f"{k:03d}",
                               typing_speed=typing_speed)
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

        if pause > 0 and k < len(beats) - 1:
            pclip = os.path.join(work, f"pause_{k:03d}.mp4")
            make_pause_clip(hold, pause, pclip)
            clips.append(pclip)

        if beat.reveal_upto is not None:
            prev_upto = max(prev_upto, beat.reveal_upto)
        print(f"  [{k+1}/{len(beats)}] {beat.narration[:60]}")

    concat(clips, out_path, work)
    shutil.rmtree(work, ignore_errors=True)
    print("done.")


def _format_script(beats1, beats2):
    """Ordered, numbered narration script matching exactly what build() will
    request from a TTS backend: one number per unique non-empty narration
    string, first-seen order, pass 1 entirely before pass 2 — the same
    dedup semantics as audio_cache/_cached_synth. Empty-narration beats are
    listed as unnumbered '(silent)' placeholders (not hidden) so the script
    stays a complete positional map of the whole video; repeated identical
    text references the earlier number instead of getting a new one."""
    lines = [
        "# Narration script — one recording per numbered line.",
        "# Save as 001.wav, 002.wav, ... (or .mp3/.m4a/.aiff/.flac/.ogg) in a",
        "# directory, then render with:",
        "#   snippet-cast <input> -o out.mp4 --tts manual --manual-audio-dir DIR",
        "# '(silent)' lines need no recording; '(dup of #NNN)' lines reuse an",
        "# earlier recording verbatim.",
        "",
    ]
    seen, n = {}, 0
    sequence = ([(1, i, b.narration) for i, b in enumerate(beats1)] +
                [(2, i, b.narration) for i, b in enumerate(beats2)])
    for pass_no, idx, text in sequence:
        tag = f"[pass {pass_no}, beat {idx + 1}]"
        if not text:
            lines.append(f"      {tag}  (silent)")
        elif text in seen:
            lines.append(f"      {tag}  (dup of #{seen[text]:03d})  {text}")
        else:
            n += 1
            seen[text] = n
            lines.append(f"{n:03d}  {tag}  {text}")
    return lines


def export_script(source_path, trace=True, every=False):
    """Parse `source_path`, build beats for both passes (or just the
    walkthrough pass, for a file with no '/'), and return the ordered,
    numbered narration script — the exact order/dedup `build()` uses to
    request audio — as a list of printable lines. Touches no ffmpeg/ffprobe,
    so it works even where those aren't installed. Use this to know exactly
    what to record for `tts="manual"`."""
    source = open(source_path).read()
    code_lines, markers = parse(source)
    if not markers:
        sys.exit(f"No narration found. Add trailing '{MARKER} ...' comments.")
    two_pass = any(TWO_PASS_SEP in m.text for m in markers)
    if two_pass and every:
        sys.exit("Two-pass narration ('/' in a marker) isn't supported with "
                 "--every; remove the '/' or drop --every.")
    if not two_pass:
        if every and any(_parse_order(m.text)[0] is not None for m in markers):
            sys.exit("Numbered 'N) ' order prefixes require first-exec mode; "
                     "drop --every or remove the prefixes.")
        markers = order_markers(markers, [m.text for m in markers])
    steps = trace_run(source, source_path) if trace else []
    if two_pass:
        beats1, beats2 = _two_pass_beats(code_lines, markers, steps)
    else:
        loop_ranges = loop_body_ranges(source) if every else {}
        beats1 = []
        beats2 = build_beats(code_lines, markers, steps, every=every, loop_ranges=loop_ranges)
    return _format_script(beats1, beats2)


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
    ap.add_argument("--typing-speed", type=float, default=TYPE_SPEED, metavar="SECONDS",
                    help="seconds to reveal each newly typed character; larger is "
                         f"slower [default: {TYPE_SPEED}]")
    ap.add_argument("--pause", type=float, default=0.0, metavar="SECONDS",
                    help="seconds of silence to hold on each beat's frame after "
                         "its narration finishes, before the next beat begins "
                         "[default: 0]")
    ap.add_argument("--export-script", action="store_true",
                    help="print the ordered, numbered narration script and exit "
                         "(no rendering, no ffmpeg/ffprobe needed) — redirect it "
                         "yourself, e.g. --export-script > script.txt")
    ap.add_argument("--manual-audio-dir", metavar="DIR",
                    help="directory of pre-recorded audio for --tts manual, named "
                         "001.wav, 002.wav, ... (or .mp3/.m4a/.aiff/.flac/.ogg) "
                         "matching --export-script's numbering")

    piper = ap.add_argument_group(
        "piper options", "override the PIPER_* environment variables (see synth_piper)")
    piper.add_argument("--piper-bin", metavar="PATH",
                       help="path to the piper binary [env: PIPER_BIN]")
    piper.add_argument("--piper-model", metavar="NAME_OR_PATH",
                       help="voice name or path to a local .onnx file [env: PIPER_MODEL]")
    piper.add_argument("--piper-length-scale", metavar="FLOAT",
                       help="speaking rate; >1 slower, <1 faster [env: PIPER_LENGTH_SCALE]")
    piper.add_argument("--piper-data-dir", metavar="DIR",
                       help="directory to search for the voice's .onnx/.onnx.json "
                            "[env: PIPER_DATA_DIR]")

    eleven = ap.add_argument_group(
        "elevenlabs options", "override the ELEVENLABS_* environment variables (see synth_elevenlabs)")
    eleven.add_argument("--elevenlabs-api-key", metavar="KEY",
                        help="API key [env: ELEVENLABS_API_KEY]")
    eleven.add_argument("--elevenlabs-voice-id", metavar="ID",
                        help="voice id [env: ELEVENLABS_VOICE_ID]")
    eleven.add_argument("--elevenlabs-model", metavar="NAME",
                        help="model id [env: ELEVENLABS_MODEL]")
    eleven.add_argument("--elevenlabs-format", metavar="FORMAT",
                        help="output_format [env: ELEVENLABS_FORMAT]")

    args = ap.parse_args()
    if args.every and args.no_trace:
        sys.exit("--every needs execution; drop --no-trace.")
    if args.typing and args.every:
        print("note: --typing has no effect with --every (full code is already shown).")
    if args.pause < 0:
        sys.exit("--pause must be >= 0.")
    if args.typing_speed <= 0:
        sys.exit("--typing-speed must be > 0.")
    if args.manual_audio_dir and args.tts != "manual":
        sys.exit("--manual-audio-dir only applies with --tts manual.")

    if args.export_script:
        for line in export_script(args.input, trace=not args.no_trace, every=args.every):
            print(line)
        return

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("ffmpeg (with ffprobe) not found on PATH.")

    # CLI flags take precedence over any already-set environment variables;
    # synth_piper/synth_elevenlabs read these via os.environ.get(...).
    env_overrides = {
        "PIPER_BIN": args.piper_bin,
        "PIPER_MODEL": args.piper_model,
        "PIPER_LENGTH_SCALE": args.piper_length_scale,
        "PIPER_DATA_DIR": args.piper_data_dir,
        "ELEVENLABS_API_KEY": args.elevenlabs_api_key,
        "ELEVENLABS_VOICE_ID": args.elevenlabs_voice_id,
        "ELEVENLABS_MODEL": args.elevenlabs_model,
        "ELEVENLABS_FORMAT": args.elevenlabs_format,
    }
    for env_var, value in env_overrides.items():
        if value is not None:
            os.environ[env_var] = value

    build(args.input, args.output, args.tts,
          trace=not args.no_trace, every=args.every,
          subtitles=args.subtitles, typing=args.typing,
          typing_speed=args.typing_speed, pause=args.pause,
          manual_audio_dir=args.manual_audio_dir)


if __name__ == "__main__":
    main()
