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

plays "Start...", "Loop...", "We define fib..." in that order. Each line
reveals independently, in whatever order it's visited: only THAT line (and
any unmarked lines directly above it back to the previous marker) appears;
every other line stays blank at its own fixed row until its own turn comes,
so jumping ahead never drags earlier untouched lines along with it and never
shifts already-revealed code to a different row. Numbering is per pass in
two-pass narration — each side of the ``/`` has its own independent order:

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
import signal
import subprocess
import sys
import tempfile
import time
import tokenize
import urllib.error
import urllib.request
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont
from pygments import highlight
from pygments.formatters import ImageFormatter
from pygments.lexers import PythonLexer
from pygments.style import Style
from pygments.styles import get_style_by_name
from pygments.token import Comment, Error, Keyword, Name, Number, Operator, String, Token

# ---------------------------------------------------------------------------
# Config — tweak freely.
# ---------------------------------------------------------------------------
MARKER = "#:"           # trailing-comment token that marks a narration line
STYLE = "monokai"       # any registered pygments style name, OR a
                        # pygments.style.Style subclass (no registration needed)
FONT_NAME = "DejaVu Sans Mono"
FONT_SIZE = 26
PANEL_FONT_SIZE = 32    # state-panel name/value text; header is PANEL_FONT_SIZE - 8
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
COL_CAPTION = "#e8e8e8"       # caption text on a dark STYLE background
COL_RULE = "#3a3b36"          # rule above the caption band on a dark STYLE background
COL_CAPTION_LIGHT = "#2b2b2b" # caption text on a light STYLE background
COL_RULE_LIGHT = "#d0d0d0"    # rule above the caption band on a light STYLE background
TYPE_SPEED = 0.15       # default seconds to reveal each new character in --typing mode
TYPE_MAXFRAMES = 150    # absolute cap on typing frames per beat, so a slow speed
                        # or a very long line can't blow a beat up unboundedly
TWO_PASS_SEP = "/"      # splits a #: narration into "writing pass / walkthrough pass"
PART2_EMPTY_HOLD = 0.8  # seconds to hold a walkthrough-pass beat with no narration
PAUSE_DEFAULT = 0.8     # default seconds of silence held on each beat after its narration
MANUAL_AUDIO_DIR_DEFAULT = "./manual_audio"  # default --manual-audio-dir for CLI/notebook
PAUSE_MARKER_RE = re.compile(r"(\.{2,})")  # 2+ consecutive periods in narration = an inline pause
PAUSE_PER_PERIOD = 0.1  # seconds of silence per "." in a PAUSE_MARKER_RE run (".."->0.2s, "...."->0.4s)
AUDIO_AR = "44100"      # normalise all clips so concat -c copy is safe
AUDIO_AC = "2"
MANUAL_AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".aiff", ".flac", ".ogg")  # --tts manual / --record

# Monospace font files to try for the PIL-drawn state panel (first hit wins).
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",   # Linux
    "/System/Library/Fonts/Menlo.ttc",                        # macOS
    "/System/Library/Fonts/Monaco.ttf",
    "/Library/Fonts/Menlo.ttc",
    "C:\\Windows\\Fonts\\consola.ttf",                        # Windows
]

# ---------------------------------------------------------------------------
# Bundled pygments Style subclasses mirroring VS Code's current built-in
# default themes ("Dark Modern" / "Light Modern" — the defaults since
# VS Code 1.71, distinct from the older "Dark+"/"Light+" classic themes).
# Not registered with pygments (no setup.cfg entry point needed): assign the
# class itself to STYLE, e.g. `STYLE = DarkModernStyle` — see _resolve_style().
#
# Colors are taken directly from VS Code's own theme-defaults source
# (github.com/microsoft/vscode, extensions/theme-defaults/themes/), each
# "Modern" theme's editor.background/foreground plus its included
# dark_plus.json/light_plus.json + dark_vs.json/light_vs.json tokenColors
# (Modern themes only override a few UI/editor colors; token colors are
# inherited unchanged from Dark+/Light+). Two simplifications were forced by
# Pygments' coarser token model, since VS Code's TextMate grammar draws
# distinctions Pygments' PythonLexer doesn't emit:
#   - Keyword: VS Code colors control-flow keywords (if/for/while/return/
#     import/...) separately from declaration keywords (def/class, scoped
#     storage.type) — pygments emits plain Token.Keyword for both, so this
#     uses the control-flow color (the one seen far more often in a typical
#     snippet).
#   - Name.Builtin: VS Code colors builtin functions (print/range/len/...)
#     separately from builtin types (int/str/bool/...) — pygments emits
#     plain Token.Name.Builtin for both, so this uses the builtin-function
#     color (this project's own test snippets only ever exercise the
#     function case: print(), range()).
# ---------------------------------------------------------------------------
class DarkModernStyle(Style):
    """VS Code's default dark theme ("Dark Modern")."""

    background_color = "#1F1F1F"
    styles = {
        Token:                  "#CCCCCC",
        Comment:                "#6A9955",
        Keyword:                "#C586C0",
        Keyword.Namespace:      "#C586C0",
        Keyword.Constant:       "#569CD6",
        Operator:               "#D4D4D4",
        Operator.Word:          "#569CD6",
        Number:                 "#B5CEA8",
        String:                 "#CE9178",
        Name:                   "#9CDCFE",
        Name.Function:          "#DCDCAA",
        Name.Class:             "#4EC9B0",
        Name.Namespace:         "#4EC9B0",
        Name.Builtin:           "#DCDCAA",
        Name.Builtin.Pseudo:    "#569CD6",   # self / cls
        Name.Exception:         "#4EC9B0",
        Name.Decorator:         "#DCDCAA",
        Error:                  "#F44747",
    }


class LightModernStyle(Style):
    """VS Code's default light theme ("Light Modern")."""

    background_color = "#FFFFFF"
    styles = {
        Token:                  "#3B3B3B",
        Comment:                "#008000",
        Keyword:                "#AF00DB",
        Keyword.Namespace:      "#AF00DB",
        Keyword.Constant:       "#0000FF",
        Operator:               "#3B3B3B",
        Operator.Word:          "#0000FF",
        Number:                 "#098658",
        String:                 "#A31515",
        Name:                   "#001080",
        Name.Function:          "#795E26",
        Name.Class:             "#267F99",
        Name.Namespace:         "#267F99",
        Name.Builtin:           "#795E26",
        Name.Builtin.Pseudo:    "#0000FF",   # self / cls
        Name.Exception:         "#267F99",
        Name.Decorator:         "#795E26",
        Error:                  "#CD3131",
    }


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
    revealed: frozenset[int] | None   # 1-based source lines visible at this
                                       # beat (see _visible_code()); None = all lines
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
    font = _mono_font(PANEL_FONT_SIZE)
    head = _mono_font(max(12, PANEL_FONT_SIZE - 8))
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


def _reveal_groups(code_lines, markers):
    """Map each marker's line_no -> the frozenset of 1-based source lines it
    is responsible for revealing: itself plus any unmarked lines between it
    and the previous marker (or the top of the file, for the first marker).
    Groups partition [1, last marker's line] with no gaps and no overlap, so
    each marker's beat always has something new to reveal, in ANY playback
    order (see order_markers()) — unlike a running high-water mark, visiting
    a later line never drags earlier, not-yet-visited lines along with it.
    Lines after the last marker are never assigned to a group (never
    revealed) — unchanged, long-standing behavior."""
    marked = sorted(m.line_no for m in markers)
    groups, start = {}, 1
    for line_no in marked:
        groups[line_no] = frozenset(range(start, line_no + 1))
        start = line_no + 1
    return groups


def _visible_code(code_lines, revealed):
    """Render `code_lines` with every NOT-yet-revealed line blanked out, so
    a line always renders at its fixed row — revealing lines out of source
    order never shifts already-visible code up or down. `revealed=None`
    means "show everything" (every-exec mode)."""
    if revealed is None:
        return "\n".join(code_lines)
    return "\n".join(line if (i + 1) in revealed else ""
                     for i, line in enumerate(code_lines))


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
        groups = _reveal_groups(code_lines, markers)
        beats = []
        revealed = frozenset()   # markers may be given out of source order
                                  # (see order_markers) — accumulate whichever
                                  # groups have been visited so far; a group,
                                  # once revealed, is never taken away again.
        for m in markers:
            revealed = revealed | groups[m.line_no]
            if m.has_code:
                st = first.get(m.line_no)
                beats.append(Beat(
                    revealed=revealed, highlight=m.line_no,
                    narration=interpolate(m.text, st.text if st else {}),
                    state=st.disp if st else {}))
            else:
                beats.append(Beat(
                    revealed=revealed, highlight=None,
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
    (_render_two_pass() ignores each beat's `revealed` when rendering pass 2,
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
    # stripnl=False: pygments' lexers strip leading/trailing blank lines by
    # default, which would silently collapse a partially-revealed frame's
    # leading blank rows (unrevealed lines rendered as "") and shove its
    # actual content up to row 1 — see _visible_code()/typing_frames().
    png = highlight(code, PythonLexer(stripnl=False), fmt)
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
    cap_fg: str = COL_CAPTION
    cap_rule: str = COL_RULE


def _resolve_style(style):
    """STYLE may be a registered pygments style name, or a Style subclass
    passed directly (pygments.formatter.Formatter accepts either already —
    see ImageFormatter's `style=` in _render_code() — this mirrors that same
    isinstance check for the one call site, get_style_by_name(), that only
    accepts a name)."""
    return get_style_by_name(style) if isinstance(style, str) else style


def _is_light(hex_color):
    """Perceived-brightness check on a '#rrggbb' background, so caption text
    (drawn straight onto the canvas, not inside its own contrasting panel —
    see PANEL_BG) can pick a readable color for either a dark or light
    STYLE — COL_CAPTION/COL_RULE assume dark, e.g. DarkModernStyle;
    COL_CAPTION_LIGHT/COL_RULE_LIGHT assume light, e.g. LightModernStyle."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) > 128


def plan_canvas(code_lines, beats, show_panel, subtitles):
    bg = _resolve_style(STYLE).background_color or "#000000"
    cap_fg, cap_rule = (COL_CAPTION_LIGHT, COL_RULE_LIGHT) if _is_light(bg) \
        else (COL_CAPTION, COL_RULE)
    full = _render_code("\n".join(code_lines), hl_lines=[])
    code_w, code_h = full.width, full.height

    panel_w = 0
    if show_panel:
        font = _mono_font(PANEL_FONT_SIZE)
        meas = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        longest = max(
            (meas.textlength(f"{n} = {v}", font=font)
             for b in beats for n, v in b.state.items()), default=0)
        panel_w = int(max(240, longest + 2 * PANEL_PAD))

        # The panel is drawn into an image exactly `code_h` tall (see
        # compose()); with a larger PANEL_FONT_SIZE a beat with many state
        # variables and few code lines could need more room than the code
        # column provides, so grow code_h (and the overall canvas) to fit —
        # never shrink the code column, only ever tall enough for both.
        asc, desc = font.getmetrics()
        lh = asc + desc + 8
        max_rows = max((len(b.state) for b in beats), default=0)
        panel_h = 2 * PANEL_PAD + lh * (1 + max(1, max_rows))  # header + rows
        code_h = max(code_h, panel_h)

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
    return Canvas(W, H, code_w, code_h, panel_w, cap_h, bg, captions, cap_fg, cap_rule)


def _draw_caption(canvas, cv, lines):
    d = ImageDraw.Draw(canvas)
    top = cv.H - cv.cap_h
    d.line([(PAD, top), (cv.W - PAD, top)], fill=cv.cap_rule, width=2)
    cfont = _mono_font(max(14, FONT_SIZE - 4))
    asc, desc = cfont.getmetrics()
    clh = asc + desc + CAP_GAP
    y = top + CAP_PAD
    for ln in lines:
        w = d.textlength(ln, font=cfont)
        d.text(((cv.W - w) / 2, y), ln, font=cfont, fill=cv.cap_fg)
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


def typing_frames(cv, code_lines, revealed_before, new_group, state, caption_lines,
                  outdir, tag, typing_speed=TYPE_SPEED, n_frames=None, reach_full=False):
    """Frames that type the lines in `new_group` (a sorted, contiguous run of
    1-based source line numbers — one _reveal_groups() group) into their
    fixed row positions. Lines in `revealed_before` stay fully shown; every
    other line stays blank — so typing a group anywhere in the file, in any
    order, never shifts already-revealed code to a different row. No highlight.

    `typing_speed` is the target seconds-per-character; the number of frames
    is derived from that and FPS (capped by TYPE_MAXFRAMES), then the chars
    are spread evenly across the frames — so a slow speed on a short line
    holds frames instead of needing one unique frame per character.

    `n_frames`, if given, overrides the typing_speed-derived frame count
    entirely (two-pass mode sizes frames to a real narration's duration
    instead). `reach_full`, if True, makes the LAST frame show the group's
    complete text instead of stopping just short of it — used when no
    separate hold-at-100% frame follows (unlike legacy --typing).

    When `revealed_before` is empty — nothing is on screen yet, i.e. this is
    the very start of the recording — frame 0 shows a blank canvas (0
    characters) and the count ramps up to the same end point the non-blank
    case reaches, instead of jumping straight to 1+ characters already typed.
    """
    new_lines = [code_lines[i - 1] for i in new_group]
    stream = "\n".join(new_lines)
    total = len(stream)
    if total < 2 or not stream.strip():
        return []
    if n_frames is None:
        n_frames = min(TYPE_MAXFRAMES, max(1, round(total * typing_speed * FPS)))
    start_blank = not revealed_before
    if start_blank:
        n_frames = max(n_frames, 2)   # need >=2 frames to ramp from 0 to end_frac
    end_frac = 1.0 if reach_full else n_frames / (n_frames + 1)
    sub = os.path.join(outdir, f"type_{tag}")
    os.makedirs(sub, exist_ok=True)
    lo, hi = new_group[0], new_group[-1]
    frames = []
    for i in range(n_frames):                # stop before full (hold shows full)
        if start_blank:
            m = round((i / (n_frames - 1)) * end_frac * total)
        else:
            denom = n_frames if reach_full else n_frames + 1
            m = max(1, round((i + 1) * total / denom))
        typed_rows = stream[:m].split("\n")
        rows = []
        for row_no, line in enumerate(code_lines, start=1):
            if row_no in revealed_before:
                rows.append(line)
            elif lo <= row_no <= hi:
                idx = row_no - lo
                rows.append(typed_rows[idx] if idx < len(typed_rows) else "")
            else:
                rows.append("")
        frames.append(compose(cv, "\n".join(rows), [], state, caption_lines,
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
        for ext in MANUAL_AUDIO_EXTS:
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


def make_pass1_code_clip(cv, code_lines, revealed_before, new_group, caption_lines,
                         duration, outdir, tag, audio=None, typing_speed=TYPE_SPEED):
    """One pass-1 'writing' clip: types the lines in `new_group` into their
    row positions (lines in `revealed_before` stay shown, everything else
    stays blank — see typing_frames()), reaching 100% typed on the last
    frame (two-pass mode has no separate hold-at-100% frame after typing),
    muxed with `audio` (real narration) or silent if `audio` is None.

    The reveal itself is always paced by `typing_speed` (capped at
    TYPE_MAXFRAMES frames, same safety valve as legacy --typing) — it no
    longer gets silently overridden by narration length. `duration` (real
    audio length when `audio` is given, else `len(group's lines joined) *
    typing_speed` from the caller) is instead a FLOOR: if the typed reveal
    finishes before `duration`, the fully-typed frame is held for the
    remainder, so a clip is never shorter than its narration audio (see
    CLAUDE.md invariant 10) without slowing the reveal below the requested
    typing_speed just to stretch it across the whole narration. If
    typing_speed would need MORE time than `duration` provides (a slow
    --typing-speed paired with brief narration), the reveal is — same as
    before this fix — cut short by make_typing_clip's -shortest at the real
    audio length; narration itself is still never truncated. Returns None
    if the group's joined text has < 2 characters (nothing worth animating
    — caller falls back to a static hold)."""
    stream = "\n".join(code_lines[i - 1] for i in new_group)
    if len(stream) < 2 or not stream.strip():
        return None
    total = len(stream)
    typing_n_frames = min(TYPE_MAXFRAMES, max(1, round(total * typing_speed * FPS)))
    frames = typing_frames(cv, code_lines, revealed_before, new_group, {}, caption_lines,
                           outdir, tag, n_frames=typing_n_frames, reach_full=True)
    if not frames:
        return None
    if audio is not None:
        floor_frames = max(1, math.ceil(duration * FPS))
        if floor_frames > len(frames):
            # Narration outlasts the typed reveal: hold the final,
            # fully-typed frame for the remainder rather than spreading the
            # reveal itself thinner to fill the whole narration.
            frames_dir = os.path.dirname(frames[-1])
            last = frames[-1]
            for i in range(len(frames), floor_frames):
                pad_path = os.path.join(frames_dir, f"{i:03d}.png")
                shutil.copyfile(last, pad_path)
                frames.append(pad_path)
    clip = os.path.join(outdir, f"type_{tag}.mp4")
    make_typing_clip(os.path.dirname(frames[0]), len(frames), clip, audio=audio)
    return clip


def concat(clips, out, workdir):
    listfile = os.path.join(workdir, "clips.txt")
    with open(listfile, "w") as fh:
        for c in clips:
            fh.write(f"file '{os.path.abspath(c)}'\n")
    # -movflags +faststart: without it, -c copy leaves the moov atom (the
    # sample index) at the END of the file — confirmed via a raw atom scan.
    # macOS Finder/Quick Look/QuickTime Player need it near the START to
    # generate a thumbnail/poster frame quickly; without it they show a
    # black window on open instead (this is exactly that, not a black FRAME
    # actually rendered into the video — the rendered first frame itself is
    # correct, see CLAUDE.md). A second, fast remux pass (no re-encode).
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
         "-c", "copy", "-movflags", "+faststart", out],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _make_silence(duration, work, tag):
    """A silent audio file `duration` seconds long, normalised to
    AUDIO_AR/AUDIO_AC like everything else in this pipeline."""
    path = os.path.join(work, f"seg_{tag}.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={AUDIO_AR}:cl=stereo",
         "-t", f"{duration:.3f}", path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path


def _concat_audio_pieces(pieces, work, tag):
    """Stitch audio files into one, via ffmpeg's `concat` audio filter —
    unlike the `concat` demuxer's `-c copy` (used by concat() for whole
    clips), the filter decodes each input first, so pieces coming from
    different backends/containers (or a generated .wav silence) don't need
    matching codecs or sample rates going in."""
    if len(pieces) == 1:
        return pieces[0]
    path = os.path.join(work, f"seg_{tag}.wav")
    inputs = [x for p in pieces for x in ("-i", p)]
    graph = "".join(f"[{i}:a]" for i in range(len(pieces))) + \
        f"concat=n={len(pieces)}:v=0:a=1[outa]"
    subprocess.run(
        ["ffmpeg", "-y", *inputs, "-filter_complex", graph, "-map", "[outa]",
         "-ar", AUDIO_AR, "-ac", AUDIO_AC, path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path


def _synth_with_pauses(synth, text, work, tag):
    """Call `synth` on `text`, honoring inline pauses: a run of 2+
    consecutive periods (PAUSE_MARKER_RE — "..", "....", ...) is not spoken.
    It's replaced by PAUSE_PER_PERIOD seconds of silence per period (".."
    -> 0.2s, "...." -> 0.4s), with the text on either side synthesized as
    separate clips and stitched back into one audio file. A single period is
    ordinary end-of-sentence punctuation and is left untouched — this only
    ever fires on a run of 2 or more. Falls back to one plain, unmodified
    `synth()` call — exactly as if this feature didn't exist — when `text`
    has no such run, so a narration that never uses it renders exactly as
    before."""
    parts = PAUSE_MARKER_RE.split(text)
    if len(parts) == 1:
        return synth(text, os.path.join(work, f"seg_{tag}"))

    pieces = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            part = part.strip()
            if part:
                pieces.append(synth(part, os.path.join(work, f"seg_{tag}_{i}")))
        else:
            pieces.append(_make_silence(len(part) * PAUSE_PER_PERIOD, work, f"{tag}_{i}"))
    return _concat_audio_pieces(pieces, work, f"{tag}_joined")


def _cached_synth(synth, audio_cache, text, work, tag, split_pauses=True):
    """audio_cache-deduped synth call: identical narration text (e.g. an
    un-interpolated loop line, or the same line reused across passes) is
    synthesized once and reused. Same semantics as the legacy loop's inline
    cache check, factored out because two-pass rendering needs it at
    multiple call sites.

    `split_pauses=False` skips _synth_with_pauses() and calls `synth` exactly
    once regardless of any '..' pause markers in `text` — used for the
    manual backend only, where splitting would consume more than one
    numbered recording per beat and desync --tts manual's file order with
    --export-script's (a human reads the dots as a natural pause cue when
    recording; nothing needs to be spliced)."""
    if text not in audio_cache:
        if split_pauses:
            audio_cache[text] = _synth_with_pauses(synth, text, work, tag)
        else:
            audio_cache[text] = synth(text, os.path.join(work, f"seg_{tag}"))
    return audio_cache[text]


def _render_two_pass(code_lines, beats1, beats2, cv, work, synth, audio_cache,
                     typing_speed, pause, split_pauses):
    """Render two-pass mode's clips and return the ordered clip-path list
    (all of pass 1, then all of pass 2) ready for concat()."""
    clips = []
    prev_revealed = frozenset()
    for k, beat in enumerate(beats1):
        caption = cv.captions[k] if cv.captions is not None else None
        new_group = sorted(beat.revealed - prev_revealed)
        stream = "\n".join(code_lines[i - 1] for i in new_group)
        pause_frame = None

        if len(stream) >= 2 and stream.strip():
            if beat.narration:
                audio = _cached_synth(synth, audio_cache, beat.narration, work,
                                      f"p1a_{k:03d}", split_pauses)
                duration = probe_duration(audio)
            else:
                audio, duration = None, len(stream) * typing_speed
            clip = make_pass1_code_clip(cv, code_lines, prev_revealed, new_group,
                                        caption, duration, work, f"p1_{k:03d}", audio=audio,
                                        typing_speed=typing_speed)
            if clip:
                clips.append(clip)
                pause_frame = compose(cv, _visible_code(code_lines, beat.revealed), [], {},
                                      caption, os.path.join(work, f"p1_pausehold_{k:03d}.png"))
        elif beat.narration:
            hold = compose(cv, _visible_code(code_lines, beat.revealed), [], {},
                           caption, os.path.join(work, f"p1_hold_{k:03d}.png"))
            audio = _cached_synth(synth, audio_cache, beat.narration, work,
                                  f"p1b_{k:03d}", split_pauses)
            clip = os.path.join(work, f"p1_clip_{k:03d}.mp4")
            make_clip(hold, audio, clip)
            clips.append(clip)
            pause_frame = hold
        # else: a comment-only marker with no pass-1 narration — nothing to
        # type and nothing to say, no clip for this beat (expected). A
        # code-bearing marker always has its own line in `new_group`
        # (_reveal_groups() groups are disjoint), so this case never fires
        # for one — every numbered line gets its own beat, regardless of
        # playback order.

        if pause_frame and pause > 0 and k < len(beats1) - 1:
            pclip = os.path.join(work, f"p1_pause_{k:03d}.mp4")
            make_pause_clip(pause_frame, pause, pclip)
            clips.append(pclip)

        prev_revealed = beat.revealed
        print(f"  [pass1 {k+1}/{len(beats1)}] {beat.narration[:60] or '(silent)'}")

    off = len(beats1)
    # Pass 1 already typed everything up to the last marked line — pass 2
    # keeps that code on screen throughout instead of re-hiding and
    # progressively re-revealing it; only the highlight/state panel move.
    final_revealed = beats1[-1].revealed
    for k, beat in enumerate(beats2):
        caption = cv.captions[off + k] if cv.captions is not None else None
        hold = compose(cv, _visible_code(code_lines, final_revealed),
                       [beat.highlight] if beat.highlight else [],
                       beat.state, caption, os.path.join(work, f"p2_hold_{k:03d}.png"))
        clip = os.path.join(work, f"p2_clip_{k:03d}.mp4")
        if beat.narration:
            audio = _cached_synth(synth, audio_cache, beat.narration, work,
                                  f"p2_{k:03d}", split_pauses)
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


def _build_all_beats(source_path, trace, every):
    """Shared parse -> two-pass-detect -> validate -> trace -> beats
    preamble used by build(), export_script(), and record_narration().
    Returns (code_lines, beats1, beats2): beats1 is the two-pass 'writing'
    pass (empty list for a file with no '/' narration split), beats2 is
    either the two-pass 'walkthrough' pass or, for a non-two-pass file,
    the complete single-pass beat sequence. `bool(beats1)` tells a caller
    whether two-pass mode was used."""
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
    return code_lines, beats1, beats2


def build(source_path, out_path, tts, trace=True, every=False,
          subtitles=False, typing=False, typing_speed=TYPE_SPEED, pause=PAUSE_DEFAULT,
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
        finishes, before the next beat begins [default: `PAUSE_DEFAULT`]. `0`
        cuts directly from one beat's narration to the next. In two-pass mode
        this only applies to the walkthrough pass.
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

    Inline pauses within a narration line
    --------------------------------------
    A run of 2+ consecutive periods inside a `#:` narration (".." , "....",
    ...) inserts a pause mid-line instead of being spoken: `PAUSE_PER_PERIOD`
    seconds of silence per period (".." -> 0.2s, "...." -> 0.4s), with the
    text on either side synthesized separately and stitched together (see
    `_synth_with_pauses`). A single period is ordinary end-of-sentence
    punctuation and is untouched. Applies to every real speech backend; the
    manual backend ignores it (a human recording narration reads the dots as
    a natural pause cue, and splitting would desync `--tts manual`'s file
    numbering with `export_script()`'s).

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

    code_lines, beats1, beats2 = _build_all_beats(source_path, trace, every)
    _render_from_beats(code_lines, beats1, beats2, out_path, tts, synth, trace,
                       every, subtitles, typing, typing_speed, pause)


def _render_from_beats(code_lines, beats1, beats2, out_path, tts, synth, trace,
                       every, subtitles, typing, typing_speed, pause):
    """Render already-computed beats (from _build_all_beats()) to `out_path`.
    Factored out of build() so record_narration() can render straight from
    the beats its interactive session already built — reusing the SAME
    interpolated narration/state the user recorded against, and skipping a
    second trace_run() (a second full execution of the user's snippet)."""
    two_pass = bool(beats1)
    if two_pass and typing:
        print("note: --typing has no effect in two-pass mode ('/' in a "
              "marker) — the writing pass always types the new code in.")
    # '..' narration pause markers (see _synth_with_pauses) only apply to real
    # speech backends — the manual backend must get exactly one synth() call
    # per beat, or its file numbering desyncs from --export-script's.
    split_pauses = tts != "manual"

    work = tempfile.mkdtemp(prefix="screencast_")

    if two_pass:
        print(f"{len(beats1)+len(beats2)} beats ({len(beats1)} pass-1 + "
              f"{len(beats2)} pass-2) -> {out_path}  (backend: {tts}, "
              f"trace: {'on' if trace else 'off'}, two-pass)")
        cv = plan_canvas(code_lines, beats1 + beats2, show_panel=trace,
                         subtitles=subtitles)
        audio_cache = {}
        clips = _render_two_pass(code_lines, beats1, beats2, cv, work, synth,
                                 audio_cache, typing_speed, pause, split_pauses)
        concat(clips, out_path, work)
        shutil.rmtree(work, ignore_errors=True)
        print("done.")
        return

    beats = beats2
    mode = "every-exec" if every else "first-exec"
    extras = "".join(x for x in [" +subs" if subtitles else "",
                                 " +typing" if typing else ""])
    print(f"{len(beats)} beats -> {out_path}  "
          f"(backend: {tts}, trace: {'on' if trace else 'off'}, {mode}{extras})")
    cv = plan_canvas(code_lines, beats, show_panel=trace, subtitles=subtitles)

    audio_cache = {}   # identical narration (e.g. an un-interpolated loop line) -> reuse
    clips = []
    prev_revealed = frozenset()
    for k, beat in enumerate(beats):
        caption = cv.captions[k] if cv.captions is not None else None

        # Typing pre-roll for newly revealed lines (first-exec mode only).
        if typing and beat.revealed is not None:
            new_group = sorted(beat.revealed - prev_revealed)
            if new_group:
                tf = typing_frames(cv, code_lines, prev_revealed, new_group,
                                   beat.state, caption, work, tag=f"{k:03d}",
                                   typing_speed=typing_speed)
                if tf:
                    tclip = os.path.join(work, f"type_{k:03d}.mp4")
                    make_typing_clip(os.path.dirname(tf[0]), len(tf), tclip)
                    clips.append(tclip)

        # Hold frame + narration.
        hold = compose(cv, _visible_code(code_lines, beat.revealed),
                       [beat.highlight] if beat.highlight else [],
                       beat.state, caption, os.path.join(work, f"hold_{k:03d}.png"))
        audio = _cached_synth(synth, audio_cache, beat.narration, work,
                              f"{k:03d}", split_pauses)
        nclip = os.path.join(work, f"clip_{k:03d}.mp4")
        make_clip(hold, audio, nclip)
        clips.append(nclip)

        if pause > 0 and k < len(beats) - 1:
            pclip = os.path.join(work, f"pause_{k:03d}.mp4")
            make_pause_clip(hold, pause, pclip)
            clips.append(pclip)

        if beat.revealed is not None:
            prev_revealed = beat.revealed
        print(f"  [{k+1}/{len(beats)}] {beat.narration[:60]}")

    concat(clips, out_path, work)
    shutil.rmtree(work, ignore_errors=True)
    print("done.")


def _narration_sequence(beats1, beats2):
    """Yield (pass_no, beat_idx, beat, number, dup_of) for every beat across
    both passes, in the exact order/dedup build() requests audio in: pass 1
    entirely before pass 2 (the same sequence _two_pass_beats() /
    build_beats() produce), one number per unique non-empty narration
    string (first-seen order) — the same dedup semantics as
    audio_cache/_cached_synth. `number` is None for a beat that needs no
    recording of its own: either silent (empty narration, `dup_of` also
    None) or a duplicate of an earlier number (`dup_of` set to it)."""
    seen, n = {}, 0
    sequence = ([(1, i, b) for i, b in enumerate(beats1)] +
                [(2, i, b) for i, b in enumerate(beats2)])
    for pass_no, idx, beat in sequence:
        text = beat.narration
        if not text:
            yield pass_no, idx, beat, None, None
        elif text in seen:
            yield pass_no, idx, beat, None, seen[text]
        else:
            n += 1
            seen[text] = n
            yield pass_no, idx, beat, n, None


def _format_script(beats1, beats2):
    """Ordered, numbered narration script matching exactly what build() will
    request from a TTS backend — see _narration_sequence(). Empty-narration
    beats are listed as unnumbered '(silent)' placeholders (not hidden) so
    the script stays a complete positional map of the whole video; repeated
    identical text references the earlier number instead of getting a new
    one."""
    lines = [
        "# Narration script — one recording per numbered line.",
        "# Save as 001.wav, 002.wav, ... (or .mp3/.m4a/.aiff/.flac/.ogg) in a",
        "# directory, then render with:",
        "#   snippet-cast <input> -o out.mp4 --tts manual --manual-audio-dir DIR",
        "# '(silent)' lines need no recording; '(dup of #NNN)' lines reuse an",
        "# earlier recording verbatim.",
        "",
    ]
    for pass_no, idx, beat, number, dup_of in _narration_sequence(beats1, beats2):
        tag = f"[pass {pass_no}, beat {idx + 1}]"
        text = beat.narration
        if number is not None:
            lines.append(f"{number:03d}  {tag}  {text}")
        elif dup_of is not None:
            lines.append(f"      {tag}  (dup of #{dup_of:03d})  {text}")
        else:
            lines.append(f"      {tag}  (silent)")
    return lines


def export_script(source_path, trace=True, every=False):
    """Parse `source_path`, build beats for both passes (or just the
    walkthrough pass, for a file with no '/'), and return the ordered,
    numbered narration script — the exact order/dedup `build()` uses to
    request audio — as a list of printable lines. Touches no ffmpeg/ffprobe,
    so it works even where those aren't installed. Use this to know exactly
    what to record for `tts="manual"`."""
    _, beats1, beats2 = _build_all_beats(source_path, trace, every)
    return _format_script(beats1, beats2)


# ---------------------------------------------------------------------------
# --record: interactively record narration for --tts manual via the system
# microphone (macOS only — system_profiler/avfoundation/afplay, no new
# dependency). One take per unique narration line (the same set
# _narration_sequence() numbers); nothing touches manual_audio_dir until the
# whole walk finishes cleanly — see record_narration()'s docstring.
# ---------------------------------------------------------------------------
def _default_input_device():
    """Name of the system's currently selected default microphone (tracks
    System Settings -> Sound -> Input live, including switching to/from
    Bluetooth devices), via system_profiler's JSON output."""
    try:
        out = subprocess.run(
            ["system_profiler", "SPAudioDataType", "-json"],
            capture_output=True, text=True, check=True).stdout
        items = json.loads(out)["SPAudioDataType"][0]["_items"]
    except Exception as e:
        sys.exit(f"record: couldn't query the default microphone via "
                 f"system_profiler ({e}).")
    for item in items:
        if item.get("coreaudio_default_audio_input_device") == "spaudio_yes":
            return item["_name"]
    sys.exit("record: no default input device found "
             "(check System Settings -> Sound -> Input).")


def _record_until_enter(dest_wav, device_name, input_fn=input):
    """Record from `device_name` into `dest_wav` until the user hits Enter.
    ffmpeg runs in the background; Enter (or an exception, e.g. Ctrl+C)
    stops it gracefully via SIGINT so the file is finalized either way.

    Returns True if audio was actually captured, False if `dest_wav` ended
    up missing or empty — e.g. Enter arrived faster than ffmpeg's own
    startup (races opening the device/output file — confirmed possible
    with a near-instant stop), or ffmpeg failed outright (most commonly:
    the calling app — a notebook's IDE/kernel, not necessarily the same app
    as a terminal — was never granted microphone permission; macOS grants
    that per-application, so a terminal being allowed doesn't imply a
    notebook's host app is too). Surfaces ffmpeg's own stderr on failure
    instead of silently discarding it, and bails out immediately (without
    waiting on `input_fn`) if ffmpeg has already exited, e.g. permission
    denied — a dead recording has nothing left to stop."""
    proc = subprocess.Popen(
        # -loglevel error: ffmpeg's default verbosity writes continuous
        # progress lines to stderr for the whole capture; since stderr is
        # only read once at the end (below), NOT suppressing that risks
        # filling the pipe buffer and stalling a long recording. At "error"
        # only a genuine failure (e.g. permission denied) writes anything.
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "avfoundation",
         "-i", f":{device_name}", dest_wav],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    print("starting microphone...")
    # Wait for ffmpeg to actually open the device and create dest_wav before
    # claiming "recording" — printing that immediately, before capture has
    # truly started, is misleading (an Enter that arrives before this would
    # also race ffmpeg's own startup). Also stop waiting immediately if
    # ffmpeg has already exited on its own (e.g. permission denied).
    for _ in range(100):  # up to ~2s
        if os.path.exists(dest_wav) or proc.poll() is not None:
            break
        time.sleep(0.02)
    if proc.poll() is None:
        print("recording — press Enter to stop.")
        try:
            input_fn()
        finally:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    ok = os.path.exists(dest_wav) and os.path.getsize(dest_wav) > 0
    if not ok:
        err = proc.stderr.read().decode(errors="replace").strip() if proc.stderr else ""
        print("ffmpeg reported:", err.splitlines()[-1] if err else "no audio captured — microphone never started.")
    return ok


def _play(path):
    """Best-effort playback via afplay (macOS built-in), after resampling
    to 44.1 kHz stereo (matching AUDIO_AR/AUDIO_AC — the same
    normalization every other audio path in this file already applies)
    rather than playing the raw file directly. Confirmed empirically: a
    24 kHz mono capture (this project's mic-recorded narration, before
    build()'s own resampling) played via afplay consistently ran ~0.5-1s
    shorter than a 44.1kHz-stereo-resampled copy of the exact same audio,
    across repeated trials, despite ffprobe reporting identical durations
    for both — i.e. afplay itself, not the file, was the unreliable part
    for that unusual source rate. If resampling fails for any reason, falls
    back to the original file — a format afplay can't handle at all just
    means no preview, not a hard failure."""
    with tempfile.TemporaryDirectory() as tmp:
        resampled = os.path.join(tmp, "preview.wav")
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-ar", AUDIO_AR, "-ac", AUDIO_AC, resampled],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        play_path = resampled if proc.returncode == 0 else path
        subprocess.run(["afplay", play_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _find_recording(audio_dir, number):
    stem = f"{number:03d}"
    for ext in MANUAL_AUDIO_EXTS:
        candidate = os.path.join(audio_dir, stem + ext)
        if os.path.exists(candidate):
            return candidate
    return None


def _show_frame_imgcat(path):
    """Best-effort terminal preview via imgcat — the inline-image protocol
    common across iTerm2/WezTerm/Kitty-style setups, all of which ship or
    alias a command literally named `imgcat` (or provide one, e.g. iTerm2's
    own install script). Availability is checked by the caller, which
    decides whether to use this at all; this just invokes it."""
    subprocess.run(["imgcat", path])


def _preview_code_text(code_lines, pass_no, beat, two_pass, final_pass1_revealed):
    """What to show on the preview frame for one beat — mirrors what the
    final render actually shows (see critical invariant on _render_two_pass
    in CLAUDE.md): in two-pass mode pass 2 always shows pass 1's fully-typed
    code (only highlight/state move), not its own `revealed`."""
    if two_pass and pass_no == 2:
        return _visible_code(code_lines, final_pass1_revealed)
    if beat.revealed is None:
        return "\n".join(code_lines)
    return _visible_code(code_lines, beat.revealed)


def _decide_recording(number, tag, text, audio_dir, session_dir, device_name,
                      input_fn=input, record_fn=_record_until_enter, play_fn=_play):
    """Prompt for one numbered narration line; return ('keep', None),
    ('record', tmp_path), ('delete', None), or ('skip', None). Plays back
    an existing recording first, if there is one.

    The default (blank Enter) is deliberately context-dependent: with an
    existing recording it means 'keep', which is safe. With NO existing
    recording there is nothing to keep — a blank Enter is rejected there
    (re-prompts) rather than silently leaving the beat unrecorded, so the
    default action can never be the reason a beat ends up with no
    recording. Leaving it unrecorded for now still requires the explicit
    's' — a real bug, not hypothetical: build(tts='manual') fails outright
    on the first beat with no numbered file, and an accidental blank Enter
    here was a silent way to end up in exactly that state."""
    existing = _find_recording(audio_dir, number)
    print(f"{number:03d}  {tag}  {text}")
    if existing:
        play_fn(existing)
        prompt = "[Enter=keep, r=record, d=delete] > "
    else:
        prompt = "[r=record, s=skip for now] > "
    while True:
        choice = input_fn(prompt).strip().lower()
        if existing and choice == "":
            return "keep", None
        if existing and choice == "d":
            return "delete", None
        if not existing and choice == "s":
            return "skip", None
        if choice == "r":
            tmp_wav = os.path.join(session_dir, f"{number:03d}.wav")
            while True:  # re-record loop: 'r' at the accept prompt stays in
                         # here so a redo can't fall through to the outer
                         # [Enter=keep,...] prompt and get silently discarded
                         # by a plain Enter meant as "yes, accept that redo"
                if not record_fn(tmp_wav, device_name, input_fn=input_fn):
                    print("no audio captured — try again (mic permission? or "
                          "waited too briefly before pressing Enter).")
                    break  # back to the outer [Enter=keep, r=record, d=delete] prompt
                play_fn(tmp_wav)
                again = input_fn("[Enter=accept, r=redo] > ").strip().lower()
                if again != "r":
                    return "record", tmp_wav
                # else: redo — record again immediately, same tmp_wav
        elif existing:
            print("unrecognized input; try 'r', 'd', or Enter.")
        else:
            print("unrecognized input; try 'r' or 's' — nothing recorded here "
                 "yet, so Enter alone won't skip it.")


def record_narration(source_path, manual_audio_dir, out_path, trace=True,
                     every=False, subtitles=False, typing=False,
                     typing_speed=TYPE_SPEED, pause=PAUSE_DEFAULT, show_frame=True,
                     build_after=True, input_fn=input,
                     record_fn=_record_until_enter, play_fn=_play,
                     frame_fn=None):
    """
    Interactively record narration for `source_path`, one take per unique
    narration line, then render with `tts="manual"`.

    Steps through every beat in playback order (pass 1 then pass 2, in
    two-pass mode). A beat that would get its own recording under
    `--tts manual` — the same unique, non-empty narration lines
    `export_script()` numbers — plays back its existing recording, if any,
    then prompts. The default (blank Enter) is deliberately
    context-dependent — it can never be the reason a beat ends up with no
    recording at all:

    - Enter — keep what's there. Only offered when a recording already
      exists; there being nothing to "keep" otherwise is the point.
    - 'r'   — record a new take (Enter to stop), then Enter to accept or
      'r' to redo.
    - 'd'   — delete the existing recording (only offered when one exists).
    - 's'   — leave a beat with no existing recording unrecorded for now
      (only offered when there's nothing to keep — the explicit
      alternative to Enter there).

    A duplicate-text or silent beat is shown for context and skipped
    automatically — it reuses an earlier number or needs no recording. If
    any beat still has no recording once the walk finishes (skipped this
    session, or never recorded in an earlier one), a summary is printed
    and, on a clean finish, `build_after` is skipped rather than attempted
    (`build(tts="manual")` would otherwise fail outright on the first one).

    Nothing is written to `manual_audio_dir` until the whole walk finishes:
    new takes are recorded to a scratch directory and deletions are staged,
    committed together only once every beat has been visited. Ctrl+C at any
    point (including mid-recording) aborts the session with no changes made.

    On a clean finish, renders `out_path` from the SAME beats this session
    walked (reusing their already-interpolated narration/state rather than
    re-parsing and re-executing `source_path` — the interactive session
    already ran it once; a snippet with real side effects, e.g. writes or
    network calls, must not run twice for one `--record` session) unless
    `build_after=False`.

    Parameters
    ----------
    source_path, trace, every, subtitles, typing, typing_speed, pause :
        Same as `build()`.
    manual_audio_dir :
        Directory holding (and to receive) `NNN.wav` recordings.
    out_path :
        Passed through to the final `build()` call.
    show_frame :
        Show each beat's rendered frame for visual context while recording
        [default: True] — via `frame_fn`, or printed as a one-time note and
        disabled for the rest of the session if `frame_fn` is left at its
        default and `imgcat` isn't on PATH.
    build_after :
        Render the MP4 after a clean (non-aborted) session [default: True].
    frame_fn :
        `frame_fn(png_path)` displays one beat's rendered frame; defaults to
        `_show_frame_imgcat` (terminal inline images via `imgcat`) if left
        `None`. `magic.py`'s cell magic passes its own, showing the frame in
        the notebook's cell output via `IPython.display.Image` instead.

    Returns
    -------
    True if the session completed and committed (even with 0 changes);
    False if aborted with Ctrl+C.

    Uses `input()` throughout (no raw keypress handling), so it works the
    same from a terminal or a notebook cell. macOS only for the recording
    itself — capture, default-device detection, and playback all shell out
    to macOS-only tools (system_profiler / ffmpeg avfoundation / afplay);
    frame preview (imgcat, or a caller-supplied `frame_fn`) is not
    macOS-specific.
    """
    if sys.platform != "darwin":
        sys.exit("record: recording narration is currently macOS-only "
                 "(uses system_profiler/avfoundation/afplay).")
    os.makedirs(manual_audio_dir, exist_ok=True)

    code_lines, beats1, beats2 = _build_all_beats(source_path, trace, every)
    two_pass = bool(beats1)
    final_pass1_revealed = beats1[-1].revealed if beats1 else None

    if show_frame and frame_fn is None:
        if shutil.which("imgcat") is None:
            print("note: 'imgcat' not found on PATH — skipping frame previews "
                 "(install imgcat for your terminal, e.g. iTerm2/WezTerm/Kitty, "
                 "or pass show_frame=False to silence this).")
            show_frame = False
        else:
            frame_fn = _show_frame_imgcat

    cv = None
    if show_frame:
        cv = plan_canvas(code_lines, beats1 + beats2, show_panel=trace, subtitles=False)

    device_name = _default_input_device()
    session_dir = tempfile.mkdtemp(prefix="snippet_cast_record_")
    preview_path = os.path.join(session_dir, "preview.png")
    pending = {}   # number -> ("record", tmp_path) | ("delete", None)

    try:
        for pass_no, idx, beat, number, dup_of in _narration_sequence(beats1, beats2):
            tag = f"[pass {pass_no}, beat {idx + 1}]"
            if show_frame:
                code_text = _preview_code_text(code_lines, pass_no, beat,
                                              two_pass, final_pass1_revealed)
                compose(cv, code_text, [beat.highlight] if beat.highlight else [],
                       beat.state, None, preview_path)
                frame_fn(preview_path)

            if number is None:
                status = f"(dup of #{dup_of:03d})" if dup_of is not None else "(silent)"
                print(f"      {tag}  {status}  {beat.narration}")
                continue

            action, tmp_path = _decide_recording(
                number, tag, beat.narration, manual_audio_dir, session_dir,
                device_name, input_fn=input_fn, record_fn=record_fn, play_fn=play_fn)
            if action not in ("keep", "skip"):
                pending[number] = (action, tmp_path)
    except KeyboardInterrupt:
        print("\naborted — no changes written.")
        shutil.rmtree(session_dir, ignore_errors=True)
        return False

    for number, (action, tmp_path) in pending.items():
        if action == "delete":
            existing = _find_recording(manual_audio_dir, number)
            if existing:
                os.remove(existing)
        else:  # "record"
            for ext in MANUAL_AUDIO_EXTS:
                stale = os.path.join(manual_audio_dir, f"{number:03d}{ext}")
                if os.path.exists(stale):
                    os.remove(stale)
            shutil.move(tmp_path, os.path.join(manual_audio_dir, f"{number:03d}.wav"))
    shutil.rmtree(session_dir, ignore_errors=True)
    print(f"{len(pending)} change(s) committed to {manual_audio_dir!r}.")

    missing = sorted(
        number for _, _, _, number, _ in _narration_sequence(beats1, beats2)
        if number is not None and _find_recording(manual_audio_dir, number) is None)
    if missing:
        print(f"note: {len(missing)} beat(s) still have no recording: "
             f"{', '.join(f'{n:03d}' for n in missing)}. Re-run --record to "
             f"fill them in — a build with --tts manual will fail on the "
             f"first one until then.")
        if build_after:
            print("skipping the auto-build until every beat has a recording.")
            return True

    if build_after:
        synth = make_manual_backend(manual_audio_dir)
        _render_from_beats(code_lines, beats1, beats2, out_path, "manual", synth,
                           trace, every, subtitles, typing, typing_speed, pause)
    return True


ENV_PREFIX = "SNIPPET_CAST_"


def _env_default(name, fallback):
    """A `SNIPPET_CAST_<NAME>` environment variable as a default value, typed
    to match `fallback` (bool/float/str), or `fallback` itself if unset."""
    val = os.environ.get(ENV_PREFIX + name.upper())
    if val is None:
        return fallback
    if isinstance(fallback, bool):
        return val.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(fallback, float):
        try:
            return float(val)
        except ValueError:
            sys.exit(f"{ENV_PREFIX}{name.upper()}={val!r} is not a valid number.")
    return val


def resolve_env_defaults(args, **fallbacks):
    """Fill in `args` fields left at their `None` sentinel (not passed on
    the CLI / not given in a `%%snippet-cast` line) from `SNIPPET_CAST_<NAME>`
    environment variables, falling back to `fallbacks[name]` if neither set
    a value. An explicit flag always wins over the environment variable; the
    environment variable always wins over the hardcoded fallback. Used by
    both `main()` and `magic.py`'s cell magic — the latter needs this
    resolved fresh on every cell run rather than baked into an
    `@argument(default=...)`, since those decorators are only evaluated
    once, at import time, not per invocation. Mutates and returns `args`."""
    for name, fallback in fallbacks.items():
        if getattr(args, name) is None:
            setattr(args, name, _env_default(name, fallback))
    return args


def resolve_output_path(output, output_dir, name):
    """The `-o/--output` path if given, else `output_dir/name.mp4` — and
    makes sure the destination directory exists."""
    out_path = output if output is not None else os.path.join(output_dir, f"{name}.mp4")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    return out_path


def main():
    """Console-script entry point (`snippet-cast`): parses argv and calls `build`."""
    ap = argparse.ArgumentParser(description="Narrated screencast from an annotated .py snippet.")
    ap.add_argument("input", help="annotated Python file")
    ap.add_argument("-o", "--output", default=None, metavar="PATH",
                    help="explicit output MP4 path — overrides -n/--name and "
                         "-d/--output-dir if given")
    ap.add_argument("-n", "--name", default=None, metavar="NAME",
                    help="basename (without extension) for the output file in "
                         "--output-dir, when -o/--output isn't given "
                         "[default: out; env: SNIPPET_CAST_NAME]")
    ap.add_argument("-d", "--output-dir", default=None, metavar="DIR",
                    help="directory for the output file when -o/--output isn't "
                         "given (created if missing) [default: current "
                         "directory; env: SNIPPET_CAST_OUTPUT_DIR]")
    ap.add_argument("--tts", choices=list(BACKENDS), default=None,
                    help="TTS backend [default: say; env: SNIPPET_CAST_TTS] "
                         "(--record implies manual; passing --tts explicitly "
                         "as anything else together with --record is an error)")
    ap.add_argument("--no-trace", action="store_true", default=None,
                    help="don't execute the snippet; skip the state panel "
                         "[env: SNIPPET_CAST_NO_TRACE]")
    ap.add_argument("--every", action=argparse.BooleanOptionalAction, default=None,
                    help="one beat per execution of a line (animates loops); "
                         "full code is shown and the highlight follows execution "
                         "[env: SNIPPET_CAST_EVERY]")
    ap.add_argument("--subtitles", action=argparse.BooleanOptionalAction, default=None,
                    help="burn the narration text as a caption (handy with "
                         "--tts silent) [env: SNIPPET_CAST_SUBTITLES]")
    ap.add_argument("--typing", action=argparse.BooleanOptionalAction, default=None,
                    help="type newly revealed lines character-by-character "
                         "(first-execution mode only) [env: SNIPPET_CAST_TYPING]")
    ap.add_argument("--typing-speed", type=float, default=None, metavar="SECONDS",
                    help="seconds to reveal each newly typed character; larger is "
                         f"slower [default: {TYPE_SPEED}; env: SNIPPET_CAST_TYPING_SPEED]")
    ap.add_argument("--pause", type=float, default=None, metavar="SECONDS",
                    help="seconds of silence to hold on each beat's frame after "
                         "its narration finishes, before the next beat begins "
                         f"[default: {PAUSE_DEFAULT}; env: SNIPPET_CAST_PAUSE]")
    ap.add_argument("--export-script", action=argparse.BooleanOptionalAction, default=None,
                    help="print the ordered, numbered narration script and exit "
                         "(no rendering, no ffmpeg/ffprobe needed) — redirect it "
                         "yourself, e.g. --export-script > script.txt "
                         "[env: SNIPPET_CAST_EXPORT_SCRIPT]")
    ap.add_argument("--manual-audio-dir", default=None, metavar="DIR",
                    help="directory of pre-recorded audio for --tts manual, named "
                         "001.wav, 002.wav, ... (or .mp3/.m4a/.aiff/.flac/.ogg) "
                         "matching --export-script's numbering "
                         f"[default: {MANUAL_AUDIO_DIR_DEFAULT}; "
                         "env: SNIPPET_CAST_MANUAL_AUDIO_DIR]")
    ap.add_argument("--record", action=argparse.BooleanOptionalAction, default=None,
                    help="interactively record narration via the system microphone "
                         "(macOS only), then build with --tts manual (implied "
                         "automatically); see SETUP.md [env: SNIPPET_CAST_RECORD]")
    ap.add_argument("--no-frame", action="store_true", default=None,
                    help="with --record, don't pop each beat's rendered frame in "
                         "the system image viewer [env: SNIPPET_CAST_NO_FRAME]")

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
    # Captured before resolve_env_defaults fills in the "say"/manual_audio_dir
    # fallbacks below, so --record can tell an explicit --tts/env var apart
    # from the hardcoded default it's about to silently override.
    tts_explicit = args.tts is not None or os.environ.get("SNIPPET_CAST_TTS") is not None
    manual_dir_explicit = (args.manual_audio_dir is not None
                           or os.environ.get("SNIPPET_CAST_MANUAL_AUDIO_DIR") is not None)
    resolve_env_defaults(
        args, tts="say", no_trace=False, every=False, subtitles=False, typing=False,
        typing_speed=TYPE_SPEED, pause=PAUSE_DEFAULT, export_script=False,
        manual_audio_dir=MANUAL_AUDIO_DIR_DEFAULT, record=False, no_frame=False,
        name="out", output_dir=".")
    if args.tts not in BACKENDS:
        sys.exit(f"--tts: invalid choice {args.tts!r} (choose from {', '.join(BACKENDS)})")

    if args.every and args.no_trace:
        sys.exit("--every needs execution; drop --no-trace.")
    if args.typing and args.every:
        print("note: --typing has no effect with --every (full code is already shown).")
    if args.pause < 0:
        sys.exit("--pause must be >= 0.")
    if args.typing_speed <= 0:
        sys.exit("--typing-speed must be > 0.")

    if args.record:
        if tts_explicit and args.tts != "manual":
            sys.exit(f"--record always uses the manual backend; got --tts {args.tts!r}. "
                     "Drop --tts (or set it to manual) when using --record.")
        args.tts = "manual"
    elif manual_dir_explicit and args.tts != "manual":
        sys.exit("--manual-audio-dir only applies with --tts manual (or --record).")

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

    out_path = resolve_output_path(args.output, args.output_dir, args.name)

    if args.record:
        record_narration(args.input, args.manual_audio_dir, out_path,
                         trace=not args.no_trace, every=args.every,
                         subtitles=args.subtitles, typing=args.typing,
                         typing_speed=args.typing_speed, pause=args.pause,
                         show_frame=not args.no_frame)
        return

    build(args.input, out_path, args.tts,
          trace=not args.no_trace, every=args.every,
          subtitles=args.subtitles, typing=args.typing,
          typing_speed=args.typing_speed, pause=args.pause,
          manual_audio_dir=args.manual_audio_dir)


if __name__ == "__main__":
    main()
