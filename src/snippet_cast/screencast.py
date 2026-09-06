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
never execute — e.g. a function that is defined but never called — show an
empty panel, so include a driver call if you want the body's state to appear.
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

FOOTNOTE NARRATION: when a narration is too long to sit in the code's right
margin, use the SAME ``N)`` label twice — once on the line it narrates, once
on a comment-only block elsewhere (by convention at the bottom) holding the
text, which may wrap over plain ``#`` lines:

    total = 0           #: 1)
    for i in range(4):  #: 2)
        total += i

    #: 1) We start with a running total of zero, because an accumulation
    # has to begin somewhere. / Here the total is still {total}.
    #: 2) Then we walk the numbers zero through three. / i is now {i}.

Before anything else runs, the block's text is unwrapped into a single line,
APPENDED to whatever text the other occurrence already has (often none), and
the block is deleted — so it never shows up as code. The result is textually
identical to having typed the body inline, so ``{var}``, ``/`` and ``..``
work in a body exactly as they do anywhere, and the ``N)`` keeps its usual
per-pass playback-order meaning (number the ``/`` side inside the body if
you want the walkthrough pass ordered too).

A label is a footnote purely by COUNT — two occurrences pair up, one is left
alone — so the plain one-occurrence ``N)`` order prefix and two-occurrence
footnotes mix freely in the same file, and nothing written before footnotes
existed can change meaning. Of the two, whichever sits on a line of its own
supplies the body (if both do, the second one does); two code-bearing
occurrences can't be merged and are left alone with a note. Three or more is
an error. Like any ``N)`` prefix, not supported with --every.

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

The displayed video's control bar is always restyled to drop the black
gradient the browser draws behind it, which would otherwise cover most of the
frame; the glyphs are flipped dark for a light frame and left white for a dark
one, chosen automatically from the theme. `--light-controls` /
`--no-light-controls` force it either way.

`%%snippet-cast --help` prints every option with its default and environment
variable, and renders nothing — from an empty cell too. `%snippet-cast --help`
(single `%`) does the same.

`--responsive` is magic-only and ON by default: it caps the displayed video at
the width of whatever it is rendered into (a Quarto column, a narrow notebook
pane) rather than the exact pixel size the snippet produced. `--no-responsive`
keeps the intrinsic size.

Same flags as the CLI (`--tts`, `--every`, `--subtitles`, `--typing`,
`--typing-speed`, `--pause`, `--no-trace`, `--export-script`, `--tts manual
--manual-audio-dir DIR`); `--tts` defaults to `silent` here instead of `say`,
and the rendered MP4 is displayed inline (`--embed` to base64-embed it in the
notebook instead of linking the file). See `snippet_cast.magic`.

USAGE (installed console script):
    snippet-cast input.py -o out.mp4 --tts say
    snippet-cast input.py -o out.mp4 --tts silent   # no audio backend needed
    snippet-cast loop.py  -o out.mp4 --every         # animate each iteration
    snippet-cast input.py -o out.mp4 --order exec    # follow Python's own order
    snippet-cast input.py -o out.mp4 --subtitles     # burn narration captions
    snippet-cast input.py -o out.mp4 --typing        # type each new line in
    snippet-cast input.py -o out.mp4 --typing --typing-speed 0.06  # slower typing
    snippet-cast input.py -o out.mp4 -q             # silent: no progress output
    snippet-cast input.py -o out.mp4 --pause 0.6     # breathing gap between beats
    snippet-cast plain.py -o out.mp4 --pause 2.0     # NO '#:' at all: one silent
                                                     # 2s frame per code line, to
                                                     # narrate later in an editor
    snippet-cast input.py -o out.mp4 --font-size 40              # bigger text
    snippet-cast input.py -o out.mp4 --screenflow               # 1920x1080, centred
    snippet-cast input.py -o out.mp4 --screenflow 1280x720      # any frame size
    snippet-cast input.py -o out.mp4 --style github-dark        # syntax theme
    snippet-cast --style list                                   # list all themes
    snippet-cast input.py -o out.mp4 --style light-modern --bg-color none
    snippet-cast input.py -o out.mp4 --state-bg-color '#0d1117' \
        --state-fg-color '#9cdcfe'                              # state panel
    snippet-cast input.py -o out.mp4 --highlight-color '#2a2d2e' # highlight band
    snippet-cast input.py -o out.mp4 --style mytheme.theme       # pandoc/KDE theme
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
import contextlib
import functools
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

from PIL import Image, ImageChops, ImageDraw, ImageFont
from pygments import highlight
from pygments.formatters import ImageFormatter
from pygments.lexers import PythonLexer
from pygments.style import Style
from pygments.styles import get_all_styles, get_style_by_name
from pygments.token import Comment, Error, Keyword, Name, Number, Operator, String, Token

# ---------------------------------------------------------------------------
# Config — tweak freely.
# ---------------------------------------------------------------------------
# "argument not given" sentinel, needed wherever None is itself a meaningful
# value the caller may pass — `bg_color=None` means "no override, use the
# style's own background", which is NOT the same as "caller said nothing".
_USE_DEFAULT = object()

MARKER = "#:"           # trailing-comment token that marks a narration line
STYLE = "numpy"         # default syntax theme: a BUILTIN_STYLES key, a
                        # BUILTIN_THEMES key (a packaged .theme file), any
                        # registered pygments style name, a path to a .theme
                        # file, OR a pygments.style.Style subclass (no
                        # registration needed). Overridable per run with
                        # --style / SNIPPET_CAST_STYLE / build(style=).
                        # For the previous dark look: --style monokai
                        # --bg-color '#1F1F1F'.
BG_COLOR = None         # background behind BOTH the code and the whole canvas,
                        # overriding STYLE's own background_color (syntax colors
                        # are untouched). None = use whatever STYLE provides,
                        # which is what lets the default light theme through.
                        # Overridable per run with --bg-color / SNIPPET_CAST_
                        # BG_COLOR / build(bg_color=).
HIGHLIGHT_PANEL = "panel"   # --highlight-color spelling for "match PANEL_BG /
                            # --state-bg-color", so the band behind the current
                            # line and the STATE box read as one surface
HIGHLIGHT_COLOR = HIGHLIGHT_PANEL  # band behind the highlighted code line, overriding
                        # STYLE's own highlight_color. HIGHLIGHT_PANEL (the
                        # shipped default) tracks the STATE panel background,
                        # so the two surfaces match and a --state-bg-color
                        # change carries the band with it; None = use the
                        # style's own (pygments' unset default is a pale
                        # "#ffffcc", which is why DarkModernStyle needs one
                        # passed). Overridable
                        # with --highlight-color / SNIPPET_CAST_HIGHLIGHT_COLOR
                        # / build(highlight_color=).
FONT_NAME = "DejaVu Sans Mono"
FONT_SIZE = 26
PANEL_FONT_SIZE = FONT_SIZE  # state-panel name/value text — mirrors the code
                             # font size by default
FONT_SIZE_MIN = 6            # floor for --font-size; pygments/PIL need a real size
SCREENFLOW_SIZE = "1920x1080"  # --screenflow's target canvas when given no WxH of its own
FPS = 30
WORDS_PER_SEC = 2.6     # only used by the 'silent' backend to fake durations
LINE_PAD = 6            # px of vertical breathing room added to each code row
HL_PAD = LINE_PAD       # px the highlight band extends past its line's text,
                        # left and right — kept equal to LINE_PAD so the band
                        # has the same padding on all four sides
PAD = 40                # px padding around the code on the canvas
GAP = 72                # px between the code column and the state panel
PANEL_PAD = 22          # inner padding of the state panel
PANEL_BG = "#DDDEDF"    # state-panel background — must stay a visible step off
                        # BG_COLOR/STYLE's background or the box disappears
COL_NAME = "#000080"    # variable names
COL_VALUE = "#000000"   # variable values
MAXVAL = 42             # truncate a value's repr to this many chars
CAP_PAD = 24            # inner padding of the caption band
CAP_GAP = 10            # px between wrapped caption lines
COL_CAPTION = "#e8e8e8"       # caption text on a dark STYLE background
COL_RULE = "#3a3b36"          # rule above the caption band on a dark STYLE background
COL_CAPTION_LIGHT = "#2b2b2b" # caption text on a light STYLE background
COL_RULE_LIGHT = "#d0d0d0"    # rule above the caption band on a light STYLE background
TYPE_SPEED = 0.1        # default seconds to reveal each new character — used by
                        # BOTH legacy --typing (typing_frames) and two-pass
                        # mode's writing pass (make_pass1_code_clip), which is
                        # why there is only ever one constant to change here
TYPE_MAXFRAMES = 450    # absolute cap on typing frames per beat, so a slow speed
                        # or a very long line can't blow a beat up unboundedly.
                        # Note this bounds the speed that can actually be
                        # DELIVERED: at FPS=30 a beat types at most
                        # TYPE_MAXFRAMES/FPS = 15s, so a group longer than
                        # 15/TYPE_SPEED characters (150 at the default) is
                        # compressed to fit rather than paced at TYPE_SPEED.
                        # Chosen to cover a 150-char line at TYPE_SPEED; the
                        # guard still bites on a deliberately slow
                        # --typing-speed (e.g. 2s/char clamps to 15s a beat)
TWO_PASS_SEP = "//"     # splits a #: narration into "writing pass // walkthrough pass"
ENTRY_SEP = "/"         # splits ONE pass's narration into "entry / completion",
                        # the two visits --order exec makes to a line. A single
                        # "/" therefore no longer means two-pass — see
                        # split_narration()/split_entry().
PART2_EMPTY_HOLD = 0.8  # seconds to hold a walkthrough-pass beat with no narration
PAUSE_DEFAULT = 0.8     # default seconds of silence held on each beat after its narration
MANUAL_AUDIO_DIR_DEFAULT = "./manual_audio"  # default --manual-audio-dir for CLI/notebook
PAUSE_MARKER_RE = re.compile(r"(\.{2,})")  # 2+ consecutive periods in narration = an inline pause
PAUSE_PER_PERIOD = 0.1  # seconds of silence per "." in a PAUSE_MARKER_RE run (".."->0.2s, "...."->0.4s)
SAY_PAUSE_MS_PER_PERIOD = 200  # ms per "." for the say backend's native [[slnc]] markup (see
                                # _say_pause_markup) — tuned separately from PAUSE_PER_PERIOD;
                                # say's own [[slnc]] reads differently than a spliced-in silence clip
SAY_EMPHASIS_RE = re.compile(r"(?<![A-Za-z])[A-Z]{2,}(?:\s+[A-Z]{2,})*(?![a-z])")
                                # a run of ALL-CAPS words (2+ letters each), for the say backend's
                                # native [[emph +]]/[[emph -]] markup — see _say_emphasis_markup
AUDIO_AR = "44100"      # normalise all clips so concat -c copy is safe
AUDIO_AC = "2"
MANUAL_AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".aiff", ".flac", ".ogg")  # --tts manual / --record

# ---------------------------------------------------------------------------
# Progress output. Everything informational the tool prints goes through
# _say() so -q/--quiet can silence it in one place. Errors deliberately do
# NOT: they go out via sys.exit()/stderr, which --quiet leaves alone, so a
# quiet run that fails still says why instead of looking like a success.
# ---------------------------------------------------------------------------
_QUIET = False


def _say(*args, **kwargs):
    """print() for progress, notes and warnings — silenced under --quiet."""
    if not _QUIET:
        print(*args, **kwargs)


@contextlib.contextmanager
def _quieted(quiet):
    """Run a block with _say() silenced when `quiet`. A module-level flag
    rather than a threaded parameter because this is cross-cutting: it would
    otherwise have to be added to trace_run(), resolve_footnotes(),
    _build_all_beats(), _render_from_beats() and _render_two_pass() alike,
    several of which already carry very long signatures. Restores the previous
    value, and nesting can only ever tighten it (an inner quiet=False cannot
    un-quiet an outer quiet=True)."""
    global _QUIET
    prev = _QUIET
    _QUIET = quiet or prev
    try:
        yield
    finally:
        _QUIET = prev


def _quiet_stdout():
    """Swallow whatever the traced snippet itself prints, under --quiet only.
    trace_run() executes the user's code, so a snippet with print() in it
    writes straight to the terminal — chatter that --quiet is expected to
    cover too. A no-op context manager when not quiet, so the snippet's output
    reaches the terminal exactly as before."""
    return contextlib.redirect_stdout(io.StringIO()) if _QUIET \
        else contextlib.nullcontext()


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


# The two styles above aren't registered with pygments, so get_style_by_name()
# can't find them — this is what makes them reachable by name from --style /
# SNIPPET_CAST_STYLE, where only a string can be passed. Names are checked
# here first, then against pygments' own registry (see resolve_style_args()).
BUILTIN_STYLES = {
    "dark-modern": DarkModernStyle,
    "light-modern": LightModernStyle,
}

# .theme files shipped inside the package (see load_theme), reachable by bare
# name from --style so they work from any directory, not just a checkout.
# Resolved lazily by _style_by_name(): the file is only read if the name is
# actually used, and load_theme() caches it after that.
THEME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "themes")
BUILTIN_THEMES = {"numpy": "numpy.theme"}


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


def _scan_comments(source: str):
    """1-based line number -> (comment_start_col, comment_text) for every
    COMMENT token. Shared by parse() and resolve_footnotes() so both find
    comments the same way — via tokenize, never a regex, so a '#' inside a
    string literal is never mistaken for one (critical invariant 5)."""
    comments = {}
    toks = tokenize.generate_tokens(io.StringIO(source).readline)
    try:
        for tok in toks:
            if tok.type == tokenize.COMMENT:
                comments[tok.start[0]] = (tok.start[1], tok.string)
    except tokenize.TokenError:
        pass  # tolerate incomplete input
    return comments


def _marker_text(comment: str):
    """The narration text of a MARKER comment token, or None for an ordinary
    '#' comment."""
    body = comment[1:].lstrip()             # drop leading '#'
    marker_body = MARKER[1:]                # part of marker after '#'
    if not body.startswith(marker_body):
        return None
    return body[len(marker_body):].strip()


def parse(source: str):
    lines = source.splitlines()
    comments = _scan_comments(source)

    code_lines, markers = [], []
    for i, raw in enumerate(lines, start=1):
        narration = None
        if i in comments:
            col, text = comments[i]
            narration = _marker_text(text)
            if narration is not None:
                raw = raw[:col].rstrip()    # strip the narration comment
        code_lines.append(raw)
        if narration:
            markers.append(Marker(i, narration, has_code=bool(raw.strip())))
    return code_lines, markers


def _auto_markers(code_lines):
    """Markers for a snippet that carries no `#:` narration at all: one
    empty-narration Marker per code line, so the normal first-exec/every-exec
    machinery still produces a beat sequence. Used only when the caller opted
    in (build(allow_unnarrated=True), i.e. an explicit --pause) — the point is
    a silent, evenly paced video to narrate later in a video editor, so every
    beat's clip is just its frame held for `pause` seconds and nothing is ever
    synthesized (see _render_from_beats).

    Comment-only lines deliberately get NO marker of their own: _reveal_groups()
    already reveals an unmarked line together with the next marked one, so a
    comment appears with the code it describes instead of costing a beat that
    would blank the state panel (a comment line has no trace Step). The last
    non-blank line is the exception — it always gets a marker, because lines
    after the final marker are never revealed at all, so a trailing comment
    block would otherwise stay invisible for the whole video."""
    markers, last = [], 0
    for i, raw in enumerate(code_lines, start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        last = i
        if not stripped.startswith("#"):
            markers.append(Marker(i, "", has_code=True))
    if last and (not markers or markers[-1].line_no != last):
        markers.append(Marker(last, "", has_code=False))
    return markers


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
    kind: str = "done"  # which visit of the line this is:
                        #   "done"  — the line has finished running; its
                        #             post-state (invariant 3). The only kind
                        #             recorded unless entries are asked for,
                        #             so every existing consumer sees exactly
                        #             the list it always did.
                        #   "call"  — a 'call' event: the parameters as just
                        #             bound, attached to the `def` line.
                        #   "enter" — the line is about to run; its PRE-state.
                        #             Recorded only when trace_run(entries=True)
                        #             (--order exec), since it doubles both the
                        #             snapshot cost and the list length.
                        # "call"/"enter" locals belong to a frame the line does
                        # not sit in the middle of, so env_before() and --every
                        # both filter down to "done" (see build_beats).


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


def trace_run(source, filename, entries=False):
    """Return an ordered list of Step, one per line execution (completion order).

    `entries=True` additionally records a "enter" Step at each line event —
    the state as the line is ABOUT to run, before its own effect. That is what
    lets --order exec highlight `y = f(x)` twice: once on entry showing `x`,
    then again, after the whole call has run, showing `y`. Off by default
    because it doubles both the number of _snapshot() calls and the length of
    the list, and nothing else needs it."""
    try:
        code = compile(source, filename, "exec")
    except SyntaxError as e:
        _say(f"  ! cannot trace (syntax error: {e}); panels will be empty.")
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
        if event == "call":
            # Entering a function: its locals are exactly the arguments as
            # just bound, and the natural line to show them against is the
            # `def` header — which otherwise only ever gets the module-level
            # step from executing the `def` STATEMENT (whose post-state has
            # no parameters in it at all). co_name filters out frames with no
            # `def` line of their own: "<module>", "<listcomp>", "<genexpr>",
            # "<dictcomp>", "<lambda>".
            if not frame.f_code.co_name.startswith("<"):
                disp, text = _snapshot(frame)
                steps.append(Step(frame.f_code.co_firstlineno, disp, text,
                                  id(frame), kind="call"))
        elif event == "line":
            close(frame)          # the previous line in this frame just finished
            if entries:
                disp, text = _snapshot(frame)
                steps.append(Step(frame.f_lineno, disp, text, id(frame),
                                  kind="enter"))
            pending[id(frame)] = frame.f_lineno
        elif event == "return":
            close(frame)
            pending.pop(id(frame), None)
        return tracer

    glb = {"__name__": "__main__", "__file__": filename}
    sys.settrace(tracer)
    try:
        with _quiet_stdout():      # the snippet's own print()s, under --quiet
            exec(code, glb)
    except Exception as e:
        _say(f"  ! snippet raised {type(e).__name__}: {e} "
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
    is unaffected (whole text stays in part2)."""
    if TWO_PASS_SEP in text:
        part1, _, part2 = text.partition(TWO_PASS_SEP)
        return part1.strip(), part2.strip()
    return "", text.strip()


def split_entry(text):
    """Split ONE pass's narration on the first ENTRY_SEP into
    (entry, completion), each stripped.

    --order exec visits a line twice — on the way in, before it has done
    anything, and again once it has finished — and those want different
    words: "we call add_one with 2" versus "it returned 3". No separator
    present -> ("", text): the whole thing narrates the completion, which is
    the visit that carries the narration in every other mode too.

    Runs AFTER split_narration() and after order_markers() has stripped any
    `N) ` prefix, so a numbered two-pass line reads `2) a // b / c` and the
    number still belongs to the pass, not to one half of it."""
    if ENTRY_SEP in text:
        entry, _, completion = text.partition(ENTRY_SEP)
        return entry.strip(), completion.strip()
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



# ---------------------------------------------------------------------------
# Footnote narration: keep a long narration out of the code's right margin by
# writing the SAME 'N)' label twice — once on the line it narrates, once on a
# comment-only block elsewhere holding the text, which may wrap over plain '#'
# lines. resolve_footnotes() appends the second occurrence's text to the
# first's and deletes the block:
#
#     assert fib(7) == 13  #: 1)
#
#     #: 1) Always begin by writing a test. That has the added
#     # benefit of running your function. / Call fib with seven.
#
# becomes, in memory:
#
#     assert fib(7) == 13  #: 1) Always begin by writing a test. That has
#            the added benefit of running your function. / Call fib with seven.
#
# It is a source -> source transform run BEFORE parse()/trace_run()/
# loop_body_ranges(), so every line number downstream re-derives from the
# rewritten text and nothing else in the pipeline needs to know about it.
#
# A label is a footnote purely by COUNT: two occurrences pair up, one is left
# exactly as it always was. That is what lets the old single-occurrence 'N)'
# order prefix and a two-occurrence footnote mix freely in one file — and it
# means a file that predates footnotes cannot change meaning, since every
# label in it occurs once.
#
# The merge is per pass (see _footnote_comment): the label is NOT re-attached
# to the walkthrough side, so the result is textually identical to having
# typed the body inline after the 'N)'. Numbering therefore stays per pass,
# exactly as order_markers() has always treated it — number the walkthrough
# side inside the body ('/ 2) text') if you want it ordered too. An earlier
# version did re-attach the label to both passes to keep them in step; that
# silently forced the walkthrough pass to be numbered, so ONE footnote in an
# otherwise walkthrough-unnumbered file tripped order_markers()' all-or-none
# check — the exact failure this design avoids.
# ---------------------------------------------------------------------------
def _footnote_comment(label, head, body):
    """The '#: ...' comment one footnote line is rewritten to: `body` (the
    second occurrence's text) appended to `head` (the first's own text, often
    empty), joined PER PASS — and, within the walkthrough pass, per HALF —
    so a '//' or a '/' on either side keeps its meaning.

    A separator on EITHER side makes this a two-pass narration, and the
    re-emitted line has to keep one even when pass 1 comes out empty — e.g.
    a reference reading `#: 3) /` whose body block carries only walkthrough
    text. Dropping it there (the old `if part1:` test) silently rewrote
    `3) /` + `Start from...` to `3) Start from...`, which re-parses as an
    UNnumbered pass 1 and a pass 2 numbered 3 — the label jumping passes.
    In a file whose walkthrough pass is otherwise unnumbered that trips
    order_markers()'s all-or-none check, so a footnote that was written
    exactly like its neighbours failed with a mix-of-numbering error. The
    label still goes on the pass-1 side only, so the result stays textually
    identical to having typed the body inline after the `N)`."""
    h1, h2 = split_narration(head)
    b1, b2 = split_narration(body)
    part1 = " ".join(p for p in (h1, b1) if p)
    # Merge the walkthrough side per HALF as well, so an entry narration in
    # the reference and a completion narration in the body (or vice versa)
    # each land where they belong instead of being concatenated into one
    # string that split_entry() would then cut in the wrong place.
    he, hc = split_entry(h2)
    be, bc = split_entry(b2)
    entry = " ".join(p for p in (he, be) if p)
    completion = " ".join(p for p in (hc, bc) if p)
    part2 = (f"{entry} {ENTRY_SEP} {completion}".strip()
             if (entry or ENTRY_SEP in h2 or ENTRY_SEP in b2) else completion)
    if part1 or TWO_PASS_SEP in head or TWO_PASS_SEP in body:
        head_side = f"{label}) {part1}".rstrip()
        return f"{MARKER} {head_side} {TWO_PASS_SEP} {part2}".rstrip()
    return f"{MARKER} {label}) {part2}"


def resolve_footnotes(source: str):
    """Merge each doubly-labelled `N)` narration into one line and drop the
    block that held the body, returning the rewritten source (the original,
    unchanged, if no label occurs twice).

    Of the two occurrences, the one on a line of its own supplies the body
    (and absorbs any plain `#` comment lines wrapped under it); the other
    receives it. Two comment-only occurrences fall back to source order —
    the second supplies. Two code-bearing ones can't be merged (deleting
    either would delete code), so they're left alone with a note."""
    lines = source.splitlines()
    comments = _scan_comments(source)

    def marker_at(i):
        """(col, narration text) if 1-based line `i` carries a MARKER."""
        if i not in comments:
            return None
        col, raw = comments[i]
        text = _marker_text(raw)
        return None if text is None else (col, text)

    def comment_only(i, col):
        return not lines[i - 1][:col].strip()

    def continuation_at(i):
        """The text of a footnote body's wrapped continuation: a whole-line
        plain '#' comment. None for anything else — code, a blank line, a
        '#:' marker or a trailing comment — each of which ends the block."""
        if i not in comments:
            return None
        col, raw = comments[i]
        if not comment_only(i, col) or _marker_text(raw) is not None:
            return None
        return raw[1:].strip()

    labelled = {}       # label -> [(line, col, text, comment_only)] in source order
    for i in range(1, len(lines) + 1):
        m = marker_at(i)
        if m is None:
            continue
        col, text = m
        label, rest = _parse_order(text)
        if label is not None:
            labelled.setdefault(label, []).append((i, col, rest, comment_only(i, col)))

    pastes, drop = {}, set()
    for label, occ in sorted(labelled.items()):
        if len(occ) == 1:
            continue        # the old single-occurrence 'N)' order prefix
        if len(occ) > 2:
            sys.exit(f"'{label})' appears {len(occ)} times (lines "
                     f"{', '.join(str(o[0]) for o in occ)}) — a footnote is "
                     f"exactly two: the line it narrates and its body.")
        alone = [o for o in occ if o[3]]
        if not alone:
            _say(f"note: '{label})' is used on two code lines "
                 f"({occ[0][0]} and {occ[1][0]}) — left alone; a footnote "
                 f"body has to sit on a line of its own.")
            continue
        # One on its own line supplies the body; if both are, the second does.
        body_occ = alone[-1] if len(alone) == 2 else alone[0]
        head_occ = occ[0] if occ[1] is body_occ else occ[1]

        body, stop = [body_occ[2]], body_occ[0] + 1
        while (cont := continuation_at(stop)) is not None:
            if cont:
                body.append(cont)
            stop += 1
        head_line, head_col, head_text, _ = head_occ
        pastes[head_line] = (head_col, _footnote_comment(
            label, head_text, " ".join(p for p in body if p)))
        drop.update(range(body_occ[0], stop))

    if not pastes:
        return source

    out = []
    for i, raw in enumerate(lines, start=1):
        if i in drop:
            continue
        if i in pastes:
            col, comment = pastes[i]
            raw = raw[:col] + comment
        out.append(raw)
    # Removing a trailing footnote block usually leaves the blank line that
    # separated it behind; plan_canvas() sizes the canvas from the full code
    # (and _render_code keeps blank rows, invariant 12), so those would add
    # dead height to every frame.
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out) + ("\n" if source.endswith("\n") else "")


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


@dataclass
class PanelColors:
    """The state panel's four resolved colors. Defaults are the module
    constants, i.e. exactly the look before --state-*-color existed."""
    bg: str = PANEL_BG
    name: str = COL_NAME
    value: str = COL_VALUE


def _mix(fg, bg, t):
    """`fg` blended `t` of the way toward `bg`, as '#rrggbb'."""
    a = [int(fg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(bg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def _panel_colors(state_bg=None, state_fg=None):
    """Resolve the state panel's colors from --state-bg-color/--state-fg-color
    (either may be None for "not given").

    `state_fg` sets ALL of the panel's text — names and values both — since
    it is a single knob for "the text in the box". Leave it unset to keep the
    default two-color scheme, or edit COL_NAME/COL_VALUE for finer control
    than one flag gives."""
    bg = state_bg or PANEL_BG
    if not state_fg:
        return PanelColors(bg=bg)
    return PanelColors(bg=bg, name=state_fg, value=state_fg)


@dataclass
class FontSizes:
    """Every text size one frame draws with, resolved once (Canvas.fonts) so
    all of a video's frames agree — the same 'resolve once, every frame draws
    from it' rule as Canvas.style/Canvas.panel (critical invariant 13).
    Always built through _font_sizes(), never constructed field-by-field: the
    fields are deliberately given no defaults, so a size can't silently freeze
    the module constants as they stood at IMPORT time (which would ignore a
    later `sc.FONT_SIZE = 40` — a documented way to change the size from a
    notebook)."""
    code: int
    panel: int
    caption: int


def _font_sizes(font_size=None):
    """Resolve `--font-size` into the four sizes one frame uses.

    `font_size` sets the CODE size; every other size keeps the OFFSET it has
    from FONT_SIZE in the module constants, so the frame scales as one piece
    and a `PANEL_FONT_SIZE` deliberately edited to differ from `FONT_SIZE`
    stays that much apart instead of being flattened back to a mirror. With
    the shipped `PANEL_FONT_SIZE = FONT_SIZE` that offset is 0, so the panel
    simply matches the code.

    `None` — and, equivalently, exactly `FONT_SIZE` — reproduces the
    constants unchanged, so a render that says nothing about fonts is
    identical to before this option existed.

    The caption's readability floor (14) is the one that expression always
    carried, now also capped at the size it is subordinate to — otherwise a
    tiny --font-size would leave the caption LARGER than the code it captions.
    Identical to the bare floor for every size from 14 up, i.e. everywhere the
    old constants could reach."""
    code = FONT_SIZE if font_size is None else max(FONT_SIZE_MIN, int(font_size))
    panel = max(FONT_SIZE_MIN, PANEL_FONT_SIZE + (code - FONT_SIZE))
    return FontSizes(code=code, panel=panel,
                     caption=min(code, max(14, code - 4)))


def render_panel(vars_dict, width, height, colors=None, fonts=None):
    """A fixed-size 'state' panel listing name = value pairs."""
    colors = colors or PanelColors()
    fonts = fonts or _font_sizes()
    img = Image.new("RGB", (width, height), colors.bg)
    d = ImageDraw.Draw(img)
    font = _mono_font(fonts.panel)
    asc, desc = font.getmetrics()
    lh = asc + desc + 8
    x, y = PANEL_PAD, PANEL_PAD
    for name, val in vars_dict.items():
        d.text((x, y), name, font=font, fill=colors.name)
        nw = d.textlength(name + " ", font=font)
        d.text((x + nw, y), f"= {val}", font=font, fill=colors.value)
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


def _warn_unused_entry_narration(markers, order):
    """Say something when a pass carries an `entry / completion` split that
    the chosen order will never show.

    Only --order exec visits a line twice, so anywhere else the entry half is
    silently dropped. That matters most as a MIGRATION signal: the pass
    separator used to be a single '/', so an older file's `write / explain`
    now parses as entry/completion and loses its writing pass without a word.
    Naming it turns that from a mystery into a one-character fix."""
    lines = [m.line_no for m in markers if split_entry(m.text)[0]]
    if lines and order != ORDER_EXEC:
        _say(f"note: {len(lines)} line(s) have an entry narration "
             f"(text before a single {ENTRY_SEP!r}) that only --order exec "
             f"shows: {', '.join(str(L) for L in lines)}. If you meant a "
             f"two-pass narration, the separator is {TWO_PASS_SEP!r}.")


ORDER_SOURCE = "source"   # --order: markers in source order (or N) order)
ORDER_EXEC = "exec"       # --order: markers in the order Python visits them


def _exec_beats(code_lines, markers, steps):
    """Beats in the order Python actually VISITS the lines (--order exec).

    Each marked line contributes one beat per kind of visit, in time order:
    "enter" (about to run — its pre-state), "call" (a function being entered,
    on its `def` line, showing the parameters as just bound) and "done" (it
    has finished — its post-state). So `result = fib(7)` is highlighted on
    entry with no `result` yet, the whole body plays, and it is highlighted
    again at the end with `result = 13`.

    Only "done" carries the narration: a line's `#:` comment describes what it
    DID, which is not true yet on the way in. Entry/call beats are therefore
    silent, and an "enter" immediately followed by its own "done" with the
    same state is dropped as a pure duplicate — that is every line whose
    execution is instantaneous, such as a module-level `def`. A line that
    gives its entry its own words (`entry / completion`) is never collapsed:
    the frames match but the narration does not.

    A marker whose line never runs contributes NO beat (its narration is
    dropped), but its code is still revealed, with the final beat, so the
    snippet never ends up with permanent holes in it.

    Comment-only markers have nothing to execute, so each is slotted directly
    after the "done" beat of the nearest preceding marked code line — or first,
    if nothing precedes it, which is where an intro line naturally sits.

    Every beat carries `revealed=None` — the WHOLE snippet is on screen from
    the first frame and only the highlight moves, exactly as in --every mode
    and for the same reason: playback jumps around (call site, then the body,
    then back to the call site), so revealing lines in that order would make
    code appear in a scattered, hole-punched sequence rather than reading as
    a program. It also means a line that never runs is on screen like any
    other, so no special handling is needed to avoid leaving holes."""
    code_marks = {m.line_no: m for m in markers if m.has_code}
    comment_marks = [m for m in markers if not m.has_code]

    # First visit of each (line, kind), in time order.
    visits, seen = [], set()
    for st in steps:
        if st.line_no in code_marks and (st.line_no, st.kind) not in seen:
            seen.add((st.line_no, st.kind))
            visits.append(st)

    # Drop an "enter" that its own "done" follows immediately with nothing
    # changed — the line ran instantaneously, so the two frames are identical.
    # A `def` line is arrived at twice: once as the statement that defines the
    # function, and again when the function is CALLED. An entry narration on
    # such a line describes stepping into it, so it belongs to the call — the
    # definition keeps only its completion words.
    called = {st.line_no for st in visits if st.kind == "call"}
    pruned = []
    for i, st in enumerate(visits):
        nxt = visits[i + 1] if i + 1 < len(visits) else None
        redundant = (st.kind == "enter" and nxt is not None
                     and nxt.kind == "done" and nxt.line_no == st.line_no
                     and nxt.disp == st.disp
                     # ...unless the line gives the entry its OWN words, in
                     # which case the two beats differ in what they SAY even
                     # though the panel is identical, and dropping one would
                     # silently lose that narration.
                     and (st.line_no in called
                          or not split_entry(code_marks[st.line_no].text)[0]))
        if not redundant:
            pruned.append(st)

    # Comment-only markers ride after the nearest preceding code line's "done"
    # — but only a line that actually GETS a beat counts as preceding, or a
    # comment sitting under a function that is never called would be dropped
    # along with it.
    visited = sorted({st.line_no for st in pruned})
    after = {}          # code line_no -> [comment markers to emit after it]
    leading = []
    for cm in comment_marks:
        prior = [L for L in visited if L < cm.line_no]
        if prior:
            after.setdefault(prior[-1], []).append(cm)
        else:
            leading.append(cm)

    def env_before(line_no):
        env = {}
        for st in steps:
            if st.kind == "done" and st.line_no < line_no:
                env = st.text
        return env

    beats = []
    for cm in leading:
        beats.append(Beat(revealed=None, highlight=None,
                          narration=interpolate(split_entry(cm.text)[1],
                                                env_before(cm.line_no)),
                          state={}))
    for st in pruned:
        m = code_marks[st.line_no]
        entry, completion = split_entry(m.text)
        # "call" counts as an arrival, like "enter": it is the moment Python
        # steps into the function, which is exactly what an entry narration is
        # for ("we call add_one with 2").
        text = completion if st.kind == "done" else entry
        beats.append(Beat(
            revealed=None, highlight=st.line_no,
            narration=interpolate(text, st.text), state=st.disp))
        if st.kind == "done":
            for cm in after.pop(st.line_no, []):
                beats.append(Beat(revealed=None, highlight=None,
                                  narration=interpolate(split_entry(cm.text)[1],
                                                        env_before(cm.line_no)),
                                  state={}))

    # Say so. Dropping narration is the documented behaviour, but silently
    # losing half a snippet's commentary looks like a bug in the tool rather
    # than an untaken branch or — much more often — a snippet that raised
    # part-way and never reached the rest (trace_run() reports that separately,
    # a few lines further up, which is easy to miss in a notebook).
    narrated = {b.highlight for b in beats if b.narration and b.highlight}
    dropped = [m.line_no for m in markers
               if m.has_code and m.text.strip() and m.line_no not in narrated]
    if dropped:
        _say(f"note: --order exec has no beat for {len(dropped)} narrated "
             f"line(s) that never ran to completion "
             f"({', '.join(str(L) for L in dropped)}) — an untaken branch, or "
             f"the snippet stopped early. Their code is still shown; only the "
             f"narration is dropped.")
    return beats


def build_beats(code_lines, markers, steps, every, loop_ranges=None,
                order=ORDER_SOURCE):
    loop_ranges = loop_ranges or {}
    code_marks = {m.line_no: m for m in markers if m.has_code}
    comment_marks = [m for m in markers if not m.has_code]
    # Call-entry steps describe the CALLEE's freshly-bound parameters, not the
    # scope the line sits in, so only the first-exec `first` map below wants
    # them: env_before() would misreport them as the caller's state, and
    # --every would gain a beat per call.
    line_steps = [st for st in steps if st.kind == "done"]

    def env_before(line_no):
        """Values from the last step that ran on a source line above this one."""
        env = {}
        for st in line_steps:
            if st.line_no < line_no:
                env = st.text
        return env

    if order == ORDER_EXEC:
        return _exec_beats(code_lines, markers, steps)

    if not every:
        first = {}  # line_no -> the Step whose state that line's beat shows
        for st in steps:
            prev = first.get(st.line_no)
            # A `def` line has two steps: executing the def STATEMENT (module
            # scope, no parameters) and entering the call (the parameters as
            # bound). Prefer the latter, so highlighting `def f(n):` shows
            # `n = 7` instead of an empty panel — the def statement's own
            # post-state is never what a walkthrough is talking about. First
            # call wins, so a second call can't overwrite it.
            if prev is None or (st.kind == "call" and prev.kind != "call"):
                first[st.line_no] = st
        groups = _reveal_groups(code_lines, markers)
        beats = []
        revealed = frozenset()   # markers may be given out of source order
                                  # (see order_markers) — accumulate whichever
                                  # groups have been visited so far; a group,
                                  # once revealed, is never taken away again.
        for m in markers:
            revealed = revealed | groups[m.line_no]
            # Only the completion half: source order has no entry visits to
            # narrate. _warn_unused_entry_narration() says so rather than
            # letting the text vanish without a word.
            if m.has_code:
                st = first.get(m.line_no)
                beats.append(Beat(
                    revealed=revealed, highlight=m.line_no,
                    narration=interpolate(split_entry(m.text)[1],
                                          st.text if st else {}),
                    state=st.disp if st else {}))
            else:
                beats.append(Beat(
                    revealed=revealed, highlight=None,
                    narration=interpolate(split_entry(m.text)[1],
                                          env_before(m.line_no)),
                    state={}))
        return beats

    # every-execution mode: drive beats from the trace, full code always shown.
    steps = line_steps          # call-entry steps add no beat of their own here
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
        exec_beats.append(Beat(None, st.line_no,
                               interpolate(split_entry(m.text)[1], st.text),
                               st.disp))

    # Slot comment-only markers by source position; interpolate each with the
    # state that exists just before its line runs.
    beats, ci = [], 0
    for eb in exec_beats:
        while ci < len(comment_marks) and comment_marks[ci].line_no <= eb.highlight:
            cm = comment_marks[ci]
            beats.append(Beat(None, None,
                              interpolate(split_entry(cm.text)[1],
                                          env_before(cm.line_no)), {}))
            ci += 1
        beats.append(eb)
    for cm in comment_marks[ci:]:                     # trailing outro comments
        beats.append(Beat(None, None,
                          interpolate(split_entry(cm.text)[1],
                                      env_before(cm.line_no)), {}))
    return beats


def _two_pass_beats(code_lines, markers, steps, order=ORDER_SOURCE):
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
    leaves pass 1 in default (top-to-bottom) order while pass 2 is reordered.

    A walkthrough pass carrying NO numbering of its own INHERITS the writing
    pass's order instead of falling back to source order. `#: 2) Write it /
    Explain it` is the ordinary way to write this — the number is naturally
    put once, on the pass that has one — and having only pass 1 honor it made
    the video jump around while writing and then march top-to-bottom while
    explaining. Ordering is still resolved per pass, so numbering pass 2
    explicitly ('/ 4) text') overrides the inheritance, and a file numbering
    neither pass is untouched.

    Note this is an ORDER-level inheritance, not a text rewrite: pass 2's
    texts stay unnumbered, so order_markers() never sees a mix and its
    all-or-none check is unaffected. (Re-attaching the label to pass 2's TEXT
    was tried once and was a real bug — it forced the walkthrough to be
    numbered, so a single footnote in an otherwise unnumbered walkthrough
    tripped that check. See resolve_footnotes()/CLAUDE.md.)"""
    parts = [split_narration(m.text) for m in markers]
    texts1 = [p[0] for p in parts]
    texts2 = [p[1] for p in parts]
    m1 = order_markers(markers, texts1)
    m2 = order_markers(markers, texts2)
    if (any(_parse_order(t)[0] is not None for t in texts1)
            and all(_parse_order(t)[0] is None for t in texts2)):
        rank = {m.line_no: i for i, m in enumerate(m1)}
        m2 = sorted(m2, key=lambda m: rank[m.line_no])
    beats1 = build_beats(code_lines, m1, steps=[], every=False)
    # --order exec applies to the WALKTHROUGH only: pass 1 is someone writing
    # the code, which happens top-to-bottom (or in the N) order they chose).
    beats2 = build_beats(code_lines, m2, steps=steps, every=False, order=order)
    return beats1, beats2


# ---------------------------------------------------------------------------
# Frame rendering: render onto a fixed-size canvas so every frame shares one
# resolution (required for clean concat).
# ---------------------------------------------------------------------------
def _render_code(code: str, hl_lines, style=None, font_size=None):
    """`style` is an ALREADY-RESOLVED pygments Style subclass (Canvas.style,
    i.e. _resolve_style()'s output, background override included). None
    resolves from the STYLE/BG_COLOR globals — only for standalone use; every
    render path passes the canvas's own style so one video can't mix two.
    `font_size` is likewise the already-resolved code size (Canvas.fonts.code);
    None means FONT_SIZE. Both must come from the canvas on every real render:
    a per-frame re-resolve could let one video mix two sizes, and a size the
    canvas was not measured at overflows it (critical invariant 1)."""
    if not code.strip():
        code = " "  # PIL cannot encode a zero-size image
    # Prefer a concrete font *file* over FONT_NAME's by-name OS lookup: pygments'
    # ImageFormatter loads a path directly (os.path.isfile check in FontManager),
    # which is portable across OSes that don't happen to have a font installed
    # under that exact name (e.g. "DejaVu Sans Mono" isn't a stock macOS font).
    if style is None:
        style = _resolve_style()
    fmt = ImageFormatter(
        font_name=_mono_font_path() or FONT_NAME,
        font_size=FONT_SIZE if font_size is None else font_size,
        style=style, line_numbers=False, hl_lines=hl_lines,
        image_pad=0, line_pad=LINE_PAD,
    )
    # stripnl=False: pygments' lexers strip leading/trailing blank lines by
    # default, which would silently collapse a partially-revealed frame's
    # leading blank rows (unrevealed lines rendered as "") and shove its
    # actual content up to row 1 — see _visible_code()/typing_frames().
    png = highlight(code, PythonLexer(stripnl=False), fmt)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    # A HL_PAD-wide background margin down each side, so a highlight on an
    # unindented line has somewhere to put its left padding — pygments starts
    # column 0 hard against x=0, which would otherwise clamp that side to
    # nothing while the right side got its full HL_PAD. Added unconditionally,
    # highlighted or not: plan_canvas() measures the canvas from an
    # unhighlighted render, so the two must always agree on the width.
    bg = style.background_color or "#000000"
    padded = Image.new("RGB", (img.width + 2 * HL_PAD, img.height), bg)
    padded.paste(img, (HL_PAD, 0))
    return _tighten_highlight(padded, code, hl_lines, style, HL_PAD) if hl_lines else padded


def _tighten_highlight(img, code, hl_lines, style, inset):
    """Redraw pygments' highlight band so it wraps the highlighted line's own
    text with HL_PAD of padding on the left and right — matching the padding
    the row already has above and below — instead of spanning the full image.

    pygments draws hl_lines as a band from x=0 to the image's right edge (see
    ImageFormatter.format), so out of the box there is no left padding at all
    and the right-hand gap is just however much shorter the line happens to be
    than the longest one in the frame.

    Both edges are rebuilt: the band is *trimmed* back with page background
    where it runs too far, and *extended* in hl_color where it stops too
    short — including out into the `inset` margin _render_code() adds down
    each side, which is background, not band, and which is the only reason an
    unindented line has anywhere to put its left padding.

    Repainting is safe because within the band's own rows the only things
    pygments has drawn are the band fill and that line's glyphs: it fills the
    rectangle first, then draws each line's text into its own row, and a row
    is exactly `fonth + line_pad` tall so no neighbouring glyph reaches in.

    The row geometry is pygments' own: rows are uniform, and the image is
    exactly `len(code.splitlines())` of them tall (verified across leading
    blanks, trailing blanks and the sparse shapes _visible_code() emits —
    pygments drops trailing blank rows and splitlines() agrees). The search
    for the line's text skips `inset` on each side, since those columns are
    background: counting them as text would put the bbox at the full image
    width and change nothing."""
    rows = len(code.splitlines())
    if not rows:
        return img
    line_h = img.height / rows
    bg = style.background_color or "#000000"
    # Same fallback chain ImageFormatter uses for an unset highlight_color.
    hl = style.highlight_color or "#f90"
    draw = ImageDraw.Draw(img)
    for line_no in hl_lines:
        y0, row_end = round((line_no - 1) * line_h), round(line_no * line_h)
        if y0 < 0 or y0 >= img.height:
            continue          # a highlight past the last rendered row
        # ImageDraw.rectangle takes an INCLUSIVE bottom, and pygments passes
        # `y + recth` — so its band is one row taller than the line box and
        # bleeds into the top row of the next line. Every rectangle here has
        # to reach that same row or a 1px stripe of the old full-width band
        # survives underneath. Safe to paint over: a row's first pixel row is
        # always above the glyph tops (the ink starts several px down).
        y_bot = row_end
        band = img.crop((inset, y0, img.width - inset, min(row_end, img.height)))
        ink = ImageChops.difference(band, Image.new("RGB", band.size, hl)).getbbox()
        if ink is None:
            # A blank highlighted line: nothing to wrap, so drop the whole
            # band rather than leave a stray full-width stripe.
            draw.rectangle([0, y0, img.width - 1, y_bot], fill=bg)
            continue
        left, right = inset + ink[0], inset + ink[2]   # text extent, right-exclusive
        x0, x1 = max(0, left - HL_PAD), min(img.width, right + HL_PAD)
        if x0 > 0:                        # band ran past the padding: trim
            draw.rectangle([0, y0, x0 - 1, y_bot], fill=bg)
        if x0 < left:                     # band stopped short: extend
            draw.rectangle([x0, y0, left - 1, y_bot], fill=hl)
        if right < x1:
            draw.rectangle([right, y0, x1 - 1, y_bot], fill=hl)
        if x1 < img.width:
            draw.rectangle([x1, y0, img.width - 1, y_bot], fill=bg)
    return img


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
    W: int               # full frame — equals cw/ch unless --screenflow padded it
    H: int
    code_w: int
    code_h: int
    panel_w: int
    cap_h: int
    bg: str
    captions: list       # per-beat list of wrapped caption lines (or None)
    cap_fg: str = COL_CAPTION
    cap_rule: str = COL_RULE
    style: type = None   # resolved pygments Style (background override applied),
                         # so every frame of one video renders from the same one
    panel: object = None # resolved PanelColors, same reason
    fonts: object = None # resolved FontSizes, same reason
    # The content block (code + panel, with the caption band under it) and its
    # top-left corner within the frame. Without --screenflow these are just
    # (W, H) at (0, 0); with it, the frame is the padded-out target and the
    # block is centred inside it. Everything positional draws off these, never
    # off W/H, so letterboxing never stretches the layout to the frame edges.
    cw: int = 0
    ch: int = 0
    off_x: int = 0
    off_y: int = 0


@functools.lru_cache(maxsize=None)
@functools.lru_cache(maxsize=None)
def _with_colors(style, bg, hl):
    """`style` (a Style subclass) with `background_color` and/or
    `highlight_color` replaced. Either may be None to keep the style's own.

    Subclassing is pygments' own documented way to tweak a style, and leaves
    the original class untouched — important, since STYLE may be a shared
    registered style. Cached because _render_code() resolves the style once
    per *frame*, and each fresh subclass would otherwise re-run StyleMeta."""
    over = {}
    if bg:
        over["background_color"] = bg
    if hl:
        over["highlight_color"] = hl
    if not over:
        return style
    return type(f"{style.__name__}Recolored", (style,), over)


def _resolve_style(style=None, bg_color=_USE_DEFAULT, hl_color=_USE_DEFAULT,
                   panel_bg=None):
    """`style` may be a registered pygments style name, a BUILTIN_STYLES key,
    or a Style subclass passed directly (pygments.formatter.Formatter accepts
    a name or a class already — see ImageFormatter's `style=` in
    _render_code() — this mirrors that same isinstance check for the one call
    site, get_style_by_name(), that only accepts a name). `None` falls back to
    the STYLE global.

    A string that names no registered style and no BUILTIN_STYLES key, but
    does point at a readable file, is loaded as a KSyntaxHighlighting/Pandoc
    `.theme` — see load_theme().

    `bg_color` and `hl_color`, if truthy, override the resolved style's own
    background_color / highlight_color; `None` means "no override, use the
    style's own", and the _USE_DEFAULT sentinel means "caller said nothing"
    -> the BG_COLOR / HIGHLIGHT_COLOR global.

    `hl_color` has one extra spelling, HIGHLIGHT_PANEL, which is the shipped
    HIGHLIGHT_COLOR default: it means "whatever the STATE panel background
    resolved to", so the band behind the current line and the STATE box are
    one surface and a --state-bg-color change carries the band along.
    `panel_bg` is that resolved background — plan_canvas() resolves the panel
    FIRST and passes it, so per-run --state-bg-color is honored; it falls
    back to the PANEL_BG global for standalone callers that have no canvas.
    Substituting here (rather than at the call sites) keeps this the single
    choke point, and makes the call idempotent: a concrete color passed in
    is returned unchanged. The overrides live here rather
    than at the call sites because this is the one choke point every consumer
    shares — plan_canvas()'s canvas fill, _render_code()'s pygments-rendered
    code block, and _tighten_highlight()'s band. Applying one to only some of
    them would paste a differently-colored rectangle onto the canvas, or
    repaint the band in a color it was never drawn in."""
    if style is None:
        style = STYLE
    if bg_color is _USE_DEFAULT:
        bg_color = BG_COLOR
    if hl_color is _USE_DEFAULT:
        hl_color = HIGHLIGHT_COLOR
    if hl_color == HIGHLIGHT_PANEL:
        hl_color = panel_bg or PANEL_BG
    if isinstance(style, str):
        style = _style_by_name(style)
    return _with_colors(style, bg_color, hl_color)


def style_names():
    """Every name --style accepts, for listings and error messages (a path to
    a .theme file is also accepted, but can't be enumerated)."""
    return (sorted(BUILTIN_STYLES) + sorted(BUILTIN_THEMES)
            + sorted(get_all_styles()))


def _style_by_name(name):
    """A style NAME (or a path to a .theme file) -> a pygments Style subclass.
    Package-local names first (BUILTIN_STYLES, then BUILTIN_THEMES), then
    pygments' own registry, then — only if the string actually points at a
    file — a .theme load. Checking a file last is what stops a stray
    `monokai.theme` in the working directory from shadowing a real style."""
    if name in BUILTIN_STYLES:
        return BUILTIN_STYLES[name]
    if name in BUILTIN_THEMES:
        return load_theme(os.path.join(THEME_DIR, BUILTIN_THEMES[name]))
    try:
        return get_style_by_name(name)
    except Exception:
        if os.path.isfile(name):
            return load_theme(name)
        raise


# ---------------------------------------------------------------------------
# KSyntaxHighlighting / Pandoc ".theme" files (`pandoc --print-highlight-style`,
# KDE/Kate's syntax themes) as a source of syntax colors, so a theme already
# used for a book or website can dress the screencast to match.
#
# The format is JSON: top-level "text-color"/"background-color" plus a
# "text-styles" map of token name -> {text-color, background-color, bold,
# italic, underline}. Its token vocabulary is coarser than pygments' in some
# places and finer in others, so THEME_TOKEN_MAP below is a deliberate,
# lossy mapping rather than a translation.
# ---------------------------------------------------------------------------
# The mapping below is the ONE place a .theme's token vocabulary meets
# pygments'. Edit it to retune how a theme is read; nothing downstream
# hardcodes a color.
#
# Two rules keep it honest, both learned from getting it wrong:
#
#  1. Map a pygments token onto the theme entry that covers the SAME set of
#     constructs — and when pygments is the coarser of the two, that means
#     the theme's more GENERAL entry. pygments' PythonLexer emits plain
#     Token.Keyword for `def`/`class` and `for`/`if`/`return` alike, so the
#     union has to land on the theme's "Keyword", not its narrower
#     "ControlFlow". (This started out on "ControlFlow" on the reasoning that
#     control-flow keywords are the more common half; that is backwards —
#     it recolored every declaration keyword too.)
#
#  2. Map only what the theme actually classifies. KSyntaxHighlighting's
#     Python definition colors keywords, builtins and literals — NOT the
#     identifiers the user writes. So Name.Function (the name after `def`),
#     Name.Class and Name.Namespace (`numpy` in `import numpy as np`) are
#     deliberately ABSENT here: they inherit Name -> "Variable", i.e. the
#     theme's plain text color, which is how pandoc renders them. Adding
#     them back invents a color the theme never asked for.
#
# Anything not listed falls back through pygments' own token inheritance to
# Token, which load_theme() sets from the theme's top-level "text-color" —
# so Punctuation, Name.Function and friends all come out as plain text.
THEME_TOKEN_MAP = {
    Comment:                "Comment",
    Keyword:                "Keyword",      # def class for if return pass as ...
    Keyword.Namespace:      "Import",       # import  from
    Keyword.Constant:       "Constant",     # True  False  None
    Operator:               "Operator",     # + - = < > ...
    Operator.Word:          "Keyword",      # in  is  and  or  not
    Number:                 "DecVal",
    Number.Float:           "Float",
    String:                 "String",
    String.Char:            "Char",
    String.Escape:          "SpecialChar",
    Name:                   "Variable",     # plain identifiers
    Name.Builtin:           "BuiltIn",      # print  range  len
    Name.Builtin.Pseudo:    "BuiltIn",      # self  cls
    Name.Exception:         "BuiltIn",      # ValueError  TypeError
    Name.Decorator:         "Attribute",    # @decorator
    Error:                  "Error",
}
THEME_HL_MIX = 0.10    # a .theme carries no highlight color, so one is derived
                       # by nudging its background this far toward black (light
                       # theme) or white (dark) — a band you can see but that
                       # doesn't shout, in place of pygments' pale-yellow default


def _theme_token_style(entry):
    """One "text-styles" entry -> a pygments style string ("bold #aa0000")."""
    parts = []
    for flag in ("bold", "italic", "underline"):
        if entry.get(flag):
            parts.append(flag)
    if entry.get("text-color"):
        parts.append(entry["text-color"])
    if entry.get("background-color"):
        parts.append(f"bg:{entry['background-color']}")
    return " ".join(parts)


def load_theme(path):
    """Build a pygments `Style` subclass from a KSyntaxHighlighting/Pandoc
    `.theme` JSON file.

    Returned as a class, so it can be assigned to `STYLE`, passed to
    `build(style=...)`, or named on the command line — `--style` treats a
    string that matches no known style name but does point at a file as one
    of these (see _style_by_name()).

    `highlight_color` is derived (THEME_HL_MIX), since the format has no
    field for it and pygments' unset default is a pale `#ffffcc` that reads
    badly on most backgrounds. `--highlight-color` overrides it.

    Cached on the path AND the file's mtime/size: _render_code() resolves the
    style once per frame, so re-reading and re-classing the file each time
    would be wasteful (and each fresh class would defeat _with_colors()' own
    cache) — but keying on the path alone made an edited theme invisible for
    the life of the process. That is barely noticeable for a one-shot CLI run
    and very noticeable in a Jupyter kernel, where every later
    `%%snippet-cast` in the session kept rendering the theme as it was when
    the kernel first read it, with a restart the only way out. The stat is
    cheap next to a frame render, and cannot change mid-render."""
    return _load_theme(path, _theme_stamp(path))


def _theme_stamp(path):
    """(mtime, size) of `path`, or None if it cannot be stat'd — the cache key
    that lets load_theme() notice an edited theme. Size is in there because
    mtime alone has coarse resolution on some filesystems, so two edits within
    the same tick could otherwise collide."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime, st.st_size)


@functools.lru_cache(maxsize=None)
def _load_theme(path, _stamp):
    """load_theme()'s cached body — `_stamp` is part of the key only, so an
    edit to the file produces a fresh entry rather than a stale hit."""
    with open(path) as fh:
        theme = json.load(fh)
    bg = theme.get("background-color") or "#ffffff"
    fg = theme.get("text-color") or "#000000"
    text_styles = theme.get("text-styles") or {}

    styles = {Token: fg}
    for token, key in THEME_TOKEN_MAP.items():
        entry = text_styles.get(key)
        if entry:
            spec = _theme_token_style(entry)
            if spec:
                styles[token] = spec

    toward = "#000000" if _is_light(bg) else "#ffffff"
    name = "".join(c for c in os.path.basename(path).split(".")[0].title()
                   if c.isalnum()) or "Theme"
    return type(f"{name}Style", (Style,), {
        "background_color": bg,
        "highlight_color": _mix(bg, toward, THEME_HL_MIX),
        "styles": styles,
    })


def _is_light(hex_color):
    """Perceived-brightness check on a '#rrggbb' background, so caption text
    (drawn straight onto the canvas, not inside its own contrasting panel —
    see PANEL_BG) can pick a readable color for either a dark or light
    STYLE — COL_CAPTION/COL_RULE assume dark, e.g. DarkModernStyle;
    COL_CAPTION_LIGHT/COL_RULE_LIGHT assume light, e.g. LightModernStyle."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) > 128


def plan_canvas(code_lines, beats, show_panel, subtitles,
                style=None, bg_color=_USE_DEFAULT,
                state_bg_color=None, state_fg_color=None,
                highlight_color=_USE_DEFAULT, font_size=None, screenflow=None):
    """Fix the canvas dimensions (and colors, and text sizes) every frame of
    one video shares. `style`/`bg_color`, the two `state_*_color`s and
    `font_size` are resolved exactly once, here, and carried on the returned
    Canvas — see _resolve_style(), _panel_colors() and _font_sizes() for what
    each accepts. Text size has to be resolved here in particular because it
    is what the canvas is MEASURED at: a frame drawn at any other size would
    not fit the dimensions this returns (critical invariant 1).

    `screenflow` is an already-parsed `(width, height)` from
    resolve_screenflow_arg(): the natural content-sized canvas is measured
    first, exactly as without it, and only then padded out to that frame with
    the content centred (Canvas.cw/ch/off_x/off_y). Measuring first is what
    keeps caption wrapping — and therefore the caption band's height —
    identical to the unpadded render instead of re-flowing to the wider
    frame."""
    # Panel first: the shipped --highlight-color default (HIGHLIGHT_PANEL)
    # resolves to whatever the panel background ends up being, so the band
    # behind the current line matches the STATE box even when the caller
    # moved it with --state-bg-color.
    panel = _panel_colors(state_bg_color, state_fg_color)
    style = _resolve_style(style, bg_color, highlight_color, panel_bg=panel.bg)
    fonts = _font_sizes(font_size)
    bg = style.background_color or "#000000"
    cap_fg, cap_rule = (COL_CAPTION_LIGHT, COL_RULE_LIGHT) if _is_light(bg) \
        else (COL_CAPTION, COL_RULE)
    full = _render_code("\n".join(code_lines), hl_lines=[], style=style,
                        font_size=fonts.code)
    code_w, code_h = full.width, full.height

    panel_w = 0
    if show_panel:
        font = _mono_font(fonts.panel)
        meas = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        longest = max(
            (meas.textlength(f"{n} = {v}", font=font)
             for b in beats for n, v in b.state.items()), default=0)
        panel_w = int(max(240, longest + 2 * PANEL_PAD))

        # The panel is drawn into an image exactly `code_h` tall (see
        # compose()); with a larger panel font a beat with many state
        # variables and few code lines could need more room than the code
        # column provides, so grow code_h (and the overall canvas) to fit —
        # never shrink the code column, only ever tall enough for both.
        asc, desc = font.getmetrics()
        lh = asc + desc + 8
        max_rows = max((len(b.state) for b in beats), default=0)
        panel_h = 2 * PANEL_PAD + lh * max(1, max_rows)
        code_h = max(code_h, panel_h)

    W = _even(PAD + code_w + (GAP + panel_w if panel_w else 0) + PAD)

    captions, cap_h = None, 0
    if subtitles:
        cfont = _mono_font(fonts.caption)
        asc, desc = cfont.getmetrics()
        clh = asc + desc + CAP_GAP
        wrap_w = W - 2 * PAD
        captions = [_wrap(b.narration, cfont, wrap_w) for b in beats]
        max_lines = max((len(c) for c in captions), default=1)
        cap_h = 2 * CAP_PAD + max_lines * clh

    H = _even(PAD + code_h + PAD + cap_h)

    # --screenflow: keep the content block at its natural size (text stays
    # crisp — nothing is ever scaled) and centre it in the requested frame.
    off_x = off_y = 0
    cw, ch = W, H
    if screenflow:
        tw, th = screenflow
        if W > tw or H > th:
            fits = max(FONT_SIZE_MIN,
                       int(fonts.code * min(tw / W, th / H)))
            raise ValueError(
                f"--screenflow {tw}x{th} is too small for this snippet: it "
                f"needs {W}x{H}. Try --font-size {fits} or smaller, drop "
                f"--subtitles/--state panel, or ask for a larger frame.")
        off_x, off_y = (tw - W) // 2, (th - H) // 2
        W, H = tw, th
    return Canvas(W, H, code_w, code_h, panel_w, cap_h, bg, captions,
                  cap_fg, cap_rule, style, panel, fonts, cw, ch, off_x, off_y)


def _plan_canvas_or_exit(*args, **kwargs):
    """plan_canvas() with its --screenflow "doesn't fit" ValueError turned
    into a clean exit. Unlike the other look options, this one cannot be
    validated at parse time: it depends on the measured canvas, which needs
    the beats, which needs trace_run() to have already run."""
    try:
        return plan_canvas(*args, **kwargs)
    except ValueError as e:
        sys.exit(str(e))


def _draw_caption(canvas, cv, lines):
    d = ImageDraw.Draw(canvas)
    # Positioned within the CONTENT BLOCK, not the frame: with --screenflow the
    # frame is larger, and the caption belongs under the code it captions
    # rather than pinned to the bottom edge of the letterbox.
    left, width = cv.off_x, cv.cw or cv.W
    top = cv.off_y + (cv.ch or cv.H) - cv.cap_h
    d.line([(left + PAD, top), (left + width - PAD, top)],
           fill=cv.cap_rule, width=2)
    cfont = _mono_font((cv.fonts or _font_sizes()).caption)
    asc, desc = cfont.getmetrics()
    clh = asc + desc + CAP_GAP
    y = top + CAP_PAD
    for ln in lines:
        w = d.textlength(ln, font=cfont)
        d.text((left + (width - w) / 2, y), ln, font=cfont, fill=cv.cap_fg)
        y += clh


def compose(cv, code_text, hl_lines, state, caption_lines, path, show_panel=True):
    """Render one full frame onto the fixed canvas and save it.

    `show_panel=False` leaves the state box off this frame while still
    RESERVING its space — the canvas is one fixed size for the whole video
    (invariant 1), so the box can only be hidden, never removed. Used for
    two-pass mode's writing pass, which runs with `steps=[]` and therefore
    has an empty box on every single frame."""
    fonts = cv.fonts or _font_sizes()
    canvas = Image.new("RGB", (cv.W, cv.H), cv.bg)
    ox, oy = cv.off_x, cv.off_y            # 0, 0 unless --screenflow centred it
    canvas.paste(_render_code(code_text, hl_lines=hl_lines, style=cv.style,
                              font_size=fonts.code), (ox + PAD, oy + PAD))
    if cv.panel_w and show_panel:
        canvas.paste(render_panel(state, cv.panel_w, cv.code_h, cv.panel, fonts),
                     (ox + PAD + cv.code_w + GAP, oy + PAD))
    if caption_lines is not None:
        _draw_caption(canvas, cv, caption_lines)
    canvas.save(path)
    return path


def typing_frames(cv, code_lines, revealed_before, new_group, state, caption_lines,
                  outdir, tag, typing_speed=TYPE_SPEED, n_frames=None,
                  reach_full=False, show_panel=True):
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
                              os.path.join(sub, f"{i:03d}.png"),
                              show_panel=show_panel))
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
    (a real narration file) or silence if `audio` is None.

    The clip always lasts the FULL frame sequence. With no `audio` that falls
    out of `anullsrc` being endless, so `-shortest` lands on the video; with a
    real narration file `apad` extends it with silence so it lands on the
    video there too. Without that pad, `-shortest` ended the clip the moment
    the narration did and simply dropped the remaining frames — a line whose
    typing needed longer than its narration stopped mid-word, and the next
    clip's fully-typed frame made the rest look typed in an instant. Typing
    now runs to completion at `typing_speed` and the narration is followed by
    silence.

    This never truncates narration (CLAUDE.md invariant 10): callers muxing
    real audio size the sequence to at least `ceil(duration * FPS)` frames
    first (see make_pass1_code_clip), so the video is the longer stream."""
    if audio:
        audio_in = ["-i", audio, "-af", "apad"]
    else:
        audio_in = ["-f", "lavfi", "-i", f"anullsrc=r={AUDIO_AR}:cl=stereo"]
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
    --typing-speed paired with brief narration), the reveal now runs to
    completion anyway and the narration is followed by silence — see
    make_typing_clip's `apad`. It used to be cut short there by `-shortest`
    at the audio length, which stopped the typing mid-word and let the next
    clip's fully-typed frame make the rest look typed in one jump. So the
    clip is always max(typed reveal, narration) long, and narration itself
    is still never truncated. Returns None
    if the group's joined text has < 2 characters (nothing worth animating
    — caller falls back to a static hold)."""
    stream = "\n".join(code_lines[i - 1] for i in new_group)
    if len(stream) < 2 or not stream.strip():
        return None
    total = len(stream)
    typing_n_frames = min(TYPE_MAXFRAMES, max(1, round(total * typing_speed * FPS)))
    frames = typing_frames(cv, code_lines, revealed_before, new_group, {}, caption_lines,
                           outdir, tag, n_frames=typing_n_frames, reach_full=True,
                           show_panel=False)
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


def _say_pause_markup(text):
    """Rewrite each PAUSE_MARKER_RE run of periods into macOS `say`'s own
    inline pause markup, `[[slnc N]]` (N milliseconds, SAY_PAUSE_MS_PER_PERIOD
    per period) — `say` interprets this natively, so the whole line is
    synthesized in ONE call with `say`'s own prosody carrying across the
    pause, instead of stitching two separately-synthesized fragments with a
    generated silence clip (see _synth_with_pauses, used for every other
    backend). A narration with no such run comes back unchanged (`.sub()`
    with no match is a no-op)."""
    return PAUSE_MARKER_RE.sub(
        lambda m: f"[[slnc {len(m.group(0)) * SAY_PAUSE_MS_PER_PERIOD}]]", text)


def _say_emphasis_markup(text):
    """Flank each run of 2+ consecutive ALL-CAPS words (SAY_EMPHASIS_RE) with
    macOS `say`'s own emphasis markup, `[[emph +]] ... [[emph -]]` — e.g.
    "Please NEVER DO THAT AGAIN" becomes "Please [[emph +]] NEVER DO THAT
    AGAIN [[emph -]]". A simple heuristic: no acronym detection, so a
    narration that mentions e.g. "the URL" gets it flanked too. The
    lookaround in SAY_EMPHASIS_RE excludes a mixed-case word entirely (e.g.
    "IDentifier" is left untouched, not sliced into "ID" + "entifier").
    A narration with no such run comes back unchanged."""
    return SAY_EMPHASIS_RE.sub(lambda m: f"[[emph +]] {m.group(0)} [[emph -]]", text)


def _say_markup(text):
    """Apply every say-specific inline markup transform to `text` before a
    single synth_say() call: inline pauses (_say_pause_markup) and ALL-CAPS
    emphasis (_say_emphasis_markup). Order doesn't matter between the two —
    one matches runs of periods, the other runs of uppercase letters, so
    they never overlap."""
    return _say_emphasis_markup(_say_pause_markup(text))


def _cached_synth(synth, audio_cache, text, work, tag, pause_mode="split"):
    """audio_cache-deduped synth call: identical narration text (e.g. an
    un-interpolated loop line, or the same line reused across passes) is
    synthesized once and reused. Same semantics as the legacy loop's inline
    cache check, factored out because two-pass rendering needs it at
    multiple call sites.

    `pause_mode` picks how `text`'s inline pause markers ('..') — and, for
    "say", ALL-CAPS emphasis too — are honored:
      "split" (default) — _synth_with_pauses(): split/synthesize/stitch with
        a generated silence clip. Used for every backend except the two below.
      "say"   — _say_markup(): rewrite pause markers to `[[slnc N]]` and
        ALL-CAPS runs to `[[emph +]] ... [[emph -]]` inline, then call
        `synth` exactly once. `say`-only, since it's the one backend with
        this native markup.
      "none"  — call `synth` exactly once on `text` unmodified. The manual
        backend only: splitting would consume more than one numbered
        recording per beat and desync --tts manual's file order with
        --export-script's (a human reads the dots as a natural pause cue when
        recording; nothing needs to be spliced)."""
    if text not in audio_cache:
        if pause_mode == "split":
            audio_cache[text] = _synth_with_pauses(synth, text, work, tag)
        elif pause_mode == "say":
            audio_cache[text] = synth(_say_markup(text), os.path.join(work, f"seg_{tag}"))
        else:
            audio_cache[text] = synth(text, os.path.join(work, f"seg_{tag}"))
    return audio_cache[text]


def _render_two_pass(code_lines, beats1, beats2, cv, work, synth, audio_cache,
                     typing_speed, pause, pause_mode):
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
                                      f"p1a_{k:03d}", pause_mode)
                duration = probe_duration(audio)
            else:
                audio, duration = None, len(stream) * typing_speed
            clip = make_pass1_code_clip(cv, code_lines, prev_revealed, new_group,
                                        caption, duration, work, f"p1_{k:03d}", audio=audio,
                                        typing_speed=typing_speed)
            if clip:
                clips.append(clip)
                pause_frame = compose(cv, _visible_code(code_lines, beat.revealed), [], {},
                                      caption, os.path.join(work, f"p1_pausehold_{k:03d}.png"),
                                      show_panel=False)
        elif beat.narration:
            hold = compose(cv, _visible_code(code_lines, beat.revealed), [], {},
                           caption, os.path.join(work, f"p1_hold_{k:03d}.png"),
                           show_panel=False)
            audio = _cached_synth(synth, audio_cache, beat.narration, work,
                                  f"p1b_{k:03d}", pause_mode)
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
        _say(f"  [pass1 {k+1}/{len(beats1)}] {beat.narration[:60] or '(silent)'}")

    off = len(beats1)
    # Pass 1 already typed everything up to the last marked line — pass 2
    # keeps that code on screen throughout instead of re-hiding and
    # progressively re-revealing it; only the highlight/state panel move.
    final_revealed = beats1[-1].revealed

    # --pause also separates the two passes themselves: the writing pass
    # ends on the fully-typed code and holds it for `pause` seconds before
    # the walkthrough starts talking. The in-loop guard above deliberately
    # skips the gap after pass 1's final beat so this one is the only clip
    # in that seam (and so no pause is ever appended after the whole video).
    # `pause_frame` is the last pass-1 beat's held frame; it is None only
    # for a comment-only final marker with no pass-1 narration, in which
    # case the same fully-typed frame is composed directly.
    if pause > 0 and beats2:
        # Still a pass-1 frame — the writing pass holding its finished code —
        # so the box stays hidden right up to the seam.
        hold = pause_frame or compose(
            cv, _visible_code(code_lines, final_revealed), [], {},
            cv.captions[off - 1] if cv.captions is not None else None,
            os.path.join(work, "p1_endhold.png"), show_panel=False)
        pclip = os.path.join(work, "p1_pause_end.mp4")
        make_pause_clip(hold, pause, pclip)
        clips.append(pclip)
    for k, beat in enumerate(beats2):
        caption = cv.captions[off + k] if cv.captions is not None else None
        hold = compose(cv, _visible_code(code_lines, final_revealed),
                       [beat.highlight] if beat.highlight else [],
                       beat.state, caption, os.path.join(work, f"p2_hold_{k:03d}.png"))
        clip = os.path.join(work, f"p2_clip_{k:03d}.mp4")
        if beat.narration:
            audio = _cached_synth(synth, audio_cache, beat.narration, work,
                                  f"p2_{k:03d}", pause_mode)
            make_clip(hold, audio, clip)
        else:
            make_pause_clip(hold, PART2_EMPTY_HOLD, clip)
        clips.append(clip)

        if pause > 0 and k < len(beats2) - 1:
            pclip = os.path.join(work, f"p2_pause_{k:03d}.mp4")
            make_pause_clip(hold, pause, pclip)
            clips.append(pclip)
        _say(f"  [pass2 {k+1}/{len(beats2)}] {beat.narration[:60] or '(silent)'}")

    return clips


def _build_all_beats(source_path, trace, every, allow_unnarrated=False,
                     order=ORDER_SOURCE):
    """Shared parse -> two-pass-detect -> validate -> trace -> beats
    preamble used by build(), export_script(), and record_narration().
    Returns (code_lines, beats1, beats2, unnarrated): beats1 is the two-pass
    'writing' pass (empty list for a file with no '/' narration split),
    beats2 is either the two-pass 'walkthrough' pass or, for a non-two-pass
    file, the complete single-pass beat sequence. `bool(beats1)` tells a
    caller whether two-pass mode was used.

    `allow_unnarrated` turns a snippet with no `#:` comments at all from an
    error into an auto-generated, silent beat sequence (_auto_markers());
    `unnarrated` reports whether that happened, so the renderer knows to hold
    each frame for `pause` seconds instead of synthesizing anything. Only
    build() opts in (on an explicit --pause) — --export-script and --record
    exist to produce/record narration, so a file with none is still an error
    there."""
    source = resolve_footnotes(open(source_path).read())
    code_lines, markers = parse(source)
    unnarrated = False
    if not markers:
        if not allow_unnarrated:
            sys.exit(f"No narration found. Add trailing '{MARKER} ...' "
                     f"comments, or pass --pause SECONDS (greater than 0) to "
                     f"render a silent video holding each line for that long.")
        markers = _auto_markers(code_lines)
        if not markers:
            sys.exit("Nothing to render: the snippet has no code lines.")
        unnarrated = True

    if order == ORDER_EXEC:
        if not trace:
            sys.exit("--order exec needs execution to know the order; "
                     "drop --no-trace.")
        if every:
            sys.exit("--order exec has no meaning with --every, which already "
                     "plays one beat per execution; drop one of them.")

    two_pass = any(TWO_PASS_SEP in m.text for m in markers)
    if two_pass and every:
        sys.exit("Two-pass narration ('/' in a marker) isn't supported with "
                 "--every; remove the '/' or drop --every.")
    if order == ORDER_EXEC and any(
            _parse_order(split_narration(m.text)[1] if two_pass else m.text)[0]
            is not None for m in markers):
        sys.exit("--order exec and numbered 'N) ' prefixes are two different "
                 "orders for the same pass — drop one. (In two-pass mode only "
                 "the walkthrough side is affected; number the writing side "
                 "instead if you want that ordered.)")
    if not two_pass:
        if every and any(_parse_order(m.text)[0] is not None for m in markers):
            sys.exit("Numbered 'N) ' order prefixes require first-exec mode; "
                     "drop --every, or remove the prefixes (a footnote "
                     "reference is one — inline its body to drop it).")
        markers = order_markers(markers, [m.text for m in markers])

    # The entry half only ever belongs to the walkthrough, so check the texts
    # that will actually be used: pass 2's in two-pass mode, the whole thing
    # otherwise.
    _warn_unused_entry_narration(
        [Marker(m.line_no, split_narration(m.text)[1] if two_pass else m.text,
                m.has_code) for m in markers], order)

    steps = (trace_run(source, source_path, entries=(order == ORDER_EXEC))
             if trace else [])
    if two_pass:
        beats1, beats2 = _two_pass_beats(code_lines, markers, steps, order)
    else:
        loop_ranges = loop_body_ranges(source) if every else {}
        beats1 = []
        beats2 = build_beats(code_lines, markers, steps, every=every,
                             loop_ranges=loop_ranges, order=order)
    return code_lines, beats1, beats2, unnarrated


def build(source_path, out_path, tts, trace=True, every=False,
          subtitles=False, typing=False, typing_speed=TYPE_SPEED, pause=PAUSE_DEFAULT,
          manual_audio_dir=None, style=None, bg_color=_USE_DEFAULT,
          state_bg_color=None, state_fg_color=None,
          highlight_color=_USE_DEFAULT, allow_unnarrated=False,
          font_size=None, screenflow=None, quiet=False,
          order=ORDER_SOURCE):
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
        it applies within both passes and at the seam between them (the
        writing pass holds its finished code for `pause` seconds before the
        walkthrough starts). Never appended after the video's final beat.
        With `allow_unnarrated=True` on a snippet that has no narration at
        all, it is instead the full length of every beat.
    allow_unnarrated :
        Render a snippet with no ``#:`` comments at all instead of exiting
        with "No narration found": one beat per code line, progressively
        revealed, each held for `pause` seconds with no audio synthesized
        (no TTS backend is used, whatever `tts` says). Intended for producing
        a silent, evenly paced screencast to narrate afterwards in a video
        editor. Requires `pause` > 0, since it is the whole length of each
        beat. The CLI turns this on exactly when ``--pause`` is given
        explicitly (or via `SNIPPET_CAST_PAUSE`), so a forgotten ``#:``
        still reports the error rather than silently rendering.
    font_size :
        Code font size in pixels for this render [default: `FONT_SIZE`].
        The state panel and the captions scale with it, each keeping the
        offset it has from `FONT_SIZE` in the module constants — so a
        `PANEL_FONT_SIZE` edited to differ stays that much apart. `None`
        means "use `FONT_SIZE`", which renders exactly as it did before this
        option existed. Values below `FONT_SIZE_MIN` are clamped (the CLI
        rejects them outright). Changing it resizes the whole canvas, which
        is fine — `plan_canvas()` measures the frame at this size — but it
        must be decided once per video, never per frame (invariant 1).
    screenflow :
        Target frame as a `(width, height)` pair (see
        `resolve_screenflow_arg()`), or None for a canvas sized to the
        snippet. The content block keeps its natural size and is CENTRED in
        that frame — nothing is scaled, so text stays crisp and the caption
        band stays under the code rather than pinned to the frame's bottom
        edge. A snippet whose natural canvas is larger than the frame raises
        `ValueError` (the CLI turns that into an exit naming a `font_size`
        that would fit) rather than being silently shrunk.
    quiet :
        Suppress every progress line, note and trace warning — and whatever
        the snippet itself prints while being traced. Errors are NOT
        suppressed: they still raise/`sys.exit` to stderr, so a quiet run
        that fails can't be mistaken for one that succeeded.
    manual_audio_dir :
        Directory of pre-recorded audio files for `tts="manual"`, named
        001.wav, 002.wav, ... (or .mp3/.m4a/.aiff/.flac/.ogg) matching
        `export_script()`'s numbering.
    style :
        Syntax highlighting theme for this render: a registered pygments
        style name, a `BUILTIN_STYLES` key (`"dark-modern"`/`"light-modern"`),
        a path to a KSyntaxHighlighting/Pandoc `.theme` file (see
        `load_theme()`), or a `pygments.style.Style` subclass. `None` uses
        the `STYLE` global.
    highlight_color :
        `"#rrggbb"` band behind the highlighted code line, overriding the
        style's own `highlight_color`. `HIGHLIGHT_PANEL` (`"panel"`, the
        shipped `HIGHLIGHT_COLOR` default) tracks the STATE panel background,
        including a per-run `state_bg_color`, so the band and the box read as
        one surface. `None` uses the style's; omit the argument to use the
        `HIGHLIGHT_COLOR` global. Worth setting for a
        style that declares none — pygments' unset default is a pale
        `#ffffcc` (`DarkModernStyle`/`LightModernStyle` are both in that
        boat); a style loaded from a `.theme` file gets one derived instead.
    state_bg_color :
        `"#rrggbb"` background for the state panel, overriding `PANEL_BG`.
        `None` keeps it.
    state_fg_color :
        `"#rrggbb"` for ALL of the state panel's text — variable names and
        values both. `None` keeps the default two-color scheme
        (`COL_NAME`/`COL_VALUE`), which is also where to go for finer control
        than one color gives.
    bg_color :
        `"#rrggbb"` background behind both the code and the canvas, overriding
        whatever background `style` declares (its syntax colors are left
        alone — pairing a dark background with a light style is on you).
        `None` means no override, i.e. the style's own background; omit the
        argument entirely to use the `BG_COLOR` global. Caption and rule
        colors adapt to whichever background wins, via `_is_light()`.

    Narration split into two passes
    --------------------------------
    A `#:` narration containing a `/` is split into "writing pass / walkthrough
    pass" text (see `split_narration`). If ANY marker in the file uses `/`,
    the whole video becomes two full, sequential passes: first the entire
    snippet is typed in (narrated by each line's part before `/`, no state
    panel, no highlight), then the existing walkthrough plays again from the
    top (narrated by the text after `/`, exactly today's single-pass
    mechanics). A file with no `/` anywhere renders exactly as before.

    Inline pauses (and, for `say`, emphasis) within a narration line
    -------------------------------------------------------------------
    A run of 2+ consecutive periods inside a `#:` narration (".." , "....",
    ...) inserts a pause mid-line instead of being spoken: `PAUSE_PER_PERIOD`
    seconds of silence per period (".." -> 0.2s, "...." -> 0.4s), with the
    text on either side synthesized separately and stitched together (see
    `_synth_with_pauses`). A single period is ordinary end-of-sentence
    punctuation and is untouched. `tts="say"` handles this differently — it
    rewrites the run in place to `say`'s own `[[slnc N]]` pause markup and
    synthesizes the whole line in one call instead (better prosody than two
    stitched fragments), and separately flanks any run of 2+ ALL-CAPS words
    with `say`'s `[[emph +]] ... [[emph -]]` (e.g. "Please NEVER DO THAT
    AGAIN" -> "Please [[emph +]] NEVER DO THAT AGAIN [[emph -]]") — see
    `_say_markup`. The manual backend ignores both: a human recording
    narration reads the dots as a pause cue and the caps as emphasis
    directly, and rewriting/splitting would desync `--tts manual`'s file
    numbering with `export_script()`'s.

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
    with _quieted(quiet):
        _build(source_path, out_path, tts, trace, every, subtitles, typing,
               typing_speed, pause, manual_audio_dir, style, bg_color,
               state_bg_color, state_fg_color, highlight_color,
               allow_unnarrated, font_size, screenflow, order)


def _build(source_path, out_path, tts, trace, every, subtitles, typing,
           typing_speed, pause, manual_audio_dir, style, bg_color,
           state_bg_color, state_fg_color, highlight_color,
           allow_unnarrated, font_size, screenflow, order=ORDER_SOURCE):
    """build()'s body, split out only so build() can wrap the whole thing in
    _quieted() without indenting every line of it."""
    if tts == "manual":
        if not manual_audio_dir:
            sys.exit("--tts manual requires --manual-audio-dir DIR.")
        synth = make_manual_backend(manual_audio_dir)
    else:
        synth = BACKENDS[tts]

    # `pause` is the whole length of an unnarrated beat, so 0 would mean
    # zero-length clips (ffmpeg's concat rejects them). Fold that into the
    # opt-in, so it is refused by _build_all_beats()'s message BEFORE
    # trace_run() executes the snippet, not after.
    code_lines, beats1, beats2, unnarrated = _build_all_beats(
        source_path, trace, every,
        allow_unnarrated=allow_unnarrated and pause > 0, order=order)
    _render_from_beats(code_lines, beats1, beats2, out_path, tts, synth, trace,
                       every, subtitles, typing, typing_speed, pause,
                       style, bg_color, state_bg_color, state_fg_color,
                       highlight_color, unnarrated=unnarrated,
                       font_size=font_size, screenflow=screenflow)


def _render_from_beats(code_lines, beats1, beats2, out_path, tts, synth, trace,
                       every, subtitles, typing, typing_speed, pause,
                       style=None, bg_color=_USE_DEFAULT,
                       state_bg_color=None, state_fg_color=None,
                       highlight_color=_USE_DEFAULT, unnarrated=False,
                       font_size=None, screenflow=None):
    """Render already-computed beats (from _build_all_beats()) to `out_path`.
    Factored out of build() so record_narration() can render straight from
    the beats its interactive session already built — reusing the SAME
    interpolated narration/state the user recorded against, and skipping a
    second trace_run() (a second full execution of the user's snippet).

    `unnarrated` renders the auto-generated, marker-less beat sequence: every
    beat is its frame held for `pause` seconds and `synth` is never called at
    all, so no TTS backend is needed and each frame lasts exactly as long as
    asked. (Two-pass mode needs a '/' in a marker, so beats1 is always empty
    here — only the single-pass path below has to handle it.)"""
    two_pass = bool(beats1)
    if two_pass and typing:
        _say("note: --typing has no effect in two-pass mode ('/' in a "
             "marker) — the writing pass always types the new code in.")
    # '..' narration pause markers: "say" rewrites them to its own inline
    # [[slnc N]] markup (one synth() call, natural prosody); other real
    # speech backends split/stitch with a generated silence clip; the manual
    # backend leaves text untouched — it must get exactly one synth() call
    # per beat, or its file numbering desyncs from --export-script's.
    pause_mode = "none" if tts == "manual" else "say" if tts == "say" else "split"

    work = tempfile.mkdtemp(prefix="screencast_")

    if two_pass:
        _say(f"{len(beats1)+len(beats2)} beats ({len(beats1)} pass-1 + "
             f"{len(beats2)} pass-2) -> {out_path}  (backend: {tts}, "
             f"trace: {'on' if trace else 'off'}, two-pass)")
        cv = _plan_canvas_or_exit(code_lines, beats1 + beats2, show_panel=trace,
                         subtitles=subtitles, style=style, bg_color=bg_color,
                         state_bg_color=state_bg_color,
                         state_fg_color=state_fg_color,
                         highlight_color=highlight_color, font_size=font_size,
                         screenflow=screenflow)
        audio_cache = {}
        clips = _render_two_pass(code_lines, beats1, beats2, cv, work, synth,
                                 audio_cache, typing_speed, pause, pause_mode)
        concat(clips, out_path, work)
        shutil.rmtree(work, ignore_errors=True)
        _say("done.")
        return

    beats = beats2
    mode = "every-exec" if every else "first-exec"
    extras = "".join(x for x in [" +subs" if subtitles else "",
                                 " +typing" if typing else ""])
    if unnarrated:
        if subtitles:
            _say("note: --subtitles has no effect without narration.")
        _say(f"{len(beats)} beats -> {out_path}  "
             f"(no narration: {pause:g}s per frame, "
             f"trace: {'on' if trace else 'off'}, {mode}{extras})")
    else:
        _say(f"{len(beats)} beats -> {out_path}  "
             f"(backend: {tts}, trace: {'on' if trace else 'off'}, {mode}{extras})")
    cv = _plan_canvas_or_exit(code_lines, beats, show_panel=trace, subtitles=subtitles,
                     style=style, bg_color=bg_color,
                     state_bg_color=state_bg_color, state_fg_color=state_fg_color,
                     highlight_color=highlight_color, font_size=font_size,
                     screenflow=screenflow)

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
        nclip = os.path.join(work, f"clip_{k:03d}.mp4")
        if unnarrated:
            # No narration to time against, so `pause` IS the beat length —
            # one hold clip, and no separate trailing gap clip (that would
            # make every frame 2*pause).
            make_pause_clip(hold, pause, nclip)
            clips.append(nclip)
        elif not beat.narration:
            # A silent beat — --order exec's entry/call visits, which carry no
            # narration by design. Hold the frame rather than synthesizing "":
            # an empty synth is a near-zero-length clip, and for --tts manual
            # it would consume a numbered recording and desync every beat
            # after it from --export-script's numbering (the same rule
            # _narration_sequence() already applies, and what two-pass mode
            # does for an empty part 2).
            make_pause_clip(hold, PART2_EMPTY_HOLD, nclip)
            clips.append(nclip)
        else:
            audio = _cached_synth(synth, audio_cache, beat.narration, work,
                                  f"{k:03d}", pause_mode)
            make_clip(hold, audio, nclip)
            clips.append(nclip)

            if pause > 0 and k < len(beats) - 1:
                pclip = os.path.join(work, f"pause_{k:03d}.mp4")
                make_pause_clip(hold, pause, pclip)
                clips.append(pclip)

        if beat.revealed is not None:
            prev_revealed = beat.revealed
        # Unnarrated beats have nothing to echo, so show the line instead.
        label = beat.narration[:60]
        if not label and beat.highlight:
            label = code_lines[beat.highlight - 1].strip()[:60]
        _say(f"  [{k+1}/{len(beats)}] {label or '(silent)'}")

    concat(clips, out_path, work)
    shutil.rmtree(work, ignore_errors=True)
    _say("done.")


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


def export_script(source_path, trace=True, every=False, quiet=False,
                  order=ORDER_SOURCE):
    """Parse `source_path`, build beats for both passes (or just the
    walkthrough pass, for a file with no '/'), and return the ordered,
    numbered narration script — the exact order/dedup `build()` uses to
    request audio — as a list of printable lines. Touches no ffmpeg/ffprobe,
    so it works even where those aren't installed. Use this to know exactly
    what to record for `tts="manual"`.

    `quiet` silences the trace's own warnings (and anything the snippet
    prints while being traced), leaving just the script — the returned lines
    are the RESULT, so they are never suppressed."""
    with _quieted(quiet):
        _, beats1, beats2, _ = _build_all_beats(source_path, trace, every,
                                                order=order)
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
                     frame_fn=None, font_size=None, screenflow=None,
                     order=ORDER_SOURCE,
                     style=None, bg_color=_USE_DEFAULT,
                     state_bg_color=None, state_fg_color=None,
                     highlight_color=_USE_DEFAULT):
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

    code_lines, beats1, beats2, _ = _build_all_beats(source_path, trace, every,
                                                    order=order)
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
        cv = _plan_canvas_or_exit(code_lines, beats1 + beats2, show_panel=trace, subtitles=False,
                         style=style, bg_color=bg_color,
                         state_bg_color=state_bg_color,
                         state_fg_color=state_fg_color,
                         highlight_color=highlight_color, font_size=font_size,
                         screenflow=screenflow)

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
                           trace, every, subtitles, typing, typing_speed, pause,
                           style, bg_color, state_bg_color, state_fg_color,
                           highlight_color, font_size=font_size,
                           screenflow=screenflow)
    return True


ENV_PREFIX = "SNIPPET_CAST_"


def _env_default(name, fallback):
    """A `SNIPPET_CAST_<NAME>` environment variable as a default value, typed
    to match `fallback` (bool/int/float/str), or `fallback` itself if unset.
    The bool check must stay FIRST: `isinstance(True, int)` is True, so an
    int branch ahead of it would turn every boolean flag's env var into
    int('true') -> a spurious exit."""
    val = os.environ.get(ENV_PREFIX + name.upper())
    if val is None:
        return fallback
    if isinstance(fallback, bool):
        return val.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(fallback, int):
        try:
            return int(val)
        except ValueError:
            sys.exit(f"{ENV_PREFIX}{name.upper()}={val!r} is not a valid integer.")
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


BG_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}\Z")
BG_COLOR_NONE = "none"   # --bg-color spelling for "use the style's own background"
STYLE_LIST_ARG = "list"  # --style spelling that prints every valid name and exits

SCREENFLOW_RE = re.compile(r"(\d{1,5})\s*[xX*]\s*(\d{1,5})\Z")
SCREENFLOW_TRUTHY = ("1", "true", "yes", "on")
# ...and the way to say "off". Without these the env var could only ever be
# turned ON: unset meant off, but every spelling of off — including the
# 'none' this codebase uses for exactly that in --bg-color, --highlight-color
# and the --state-*-colors — was a hard error. Setting
# SNIPPET_CAST_SCREENFLOW=none in a shell profile or a notebook setup cell
# then broke every later run.
SCREENFLOW_FALSEY = ("", "0", "false", "no", "off", BG_COLOR_NONE)


def resolve_screenflow_arg(raw):
    """Normalize a raw `--screenflow` value into `(width, height)`, or None
    when the option wasn't used. Shared by `main()` and the cell magic, which
    render the `ValueError` their own way — the same split as
    resolve_style_args()/resolve_panel_args(), so a bad spelling is caught at
    parse time rather than deep inside the first frame render (which is AFTER
    trace_run() has already executed the user's snippet).

    Accepts `WxH` and, so the environment variable can act as a plain
    on-switch the way the bare flag does, any of SCREENFLOW_TRUTHY (meaning
    SCREENFLOW_SIZE) — or any of SCREENFLOW_FALSEY, including `"none"`, to
    turn it back off. Odd dimensions are rounded up: libx264 needs even ones.
    """
    if raw is None or raw is False:
        return None
    if raw is True:
        raw = SCREENFLOW_SIZE
    text = _unquote(str(raw).strip())
    if text.lower() in SCREENFLOW_FALSEY:
        return None
    if text.lower() in SCREENFLOW_TRUTHY:
        text = SCREENFLOW_SIZE
    m = SCREENFLOW_RE.match(text)
    if not m:
        # The likeliest way to land here is `--screenflow input.py`: the value
        # is optional, so argparse hands the following positional to the flag
        # instead of to `input`. Say so rather than only rejecting the value.
        hint = ""
        if text.endswith(".py") or os.path.exists(text):
            hint = (f" — {text!r} looks like the input file; put it before the "
                    f"flag (snippet-cast {text} --screenflow) or give the flag "
                    f"its own size (--screenflow {SCREENFLOW_SIZE} {text}).")
        raise ValueError(f"--screenflow: expected WxH, e.g. {SCREENFLOW_SIZE}, "
                         f"got {text!r}{hint}")
    w, h = (_even(int(g)) for g in m.groups())
    if w < 2 or h < 2:
        raise ValueError(f"--screenflow: {text!r} is too small to hold a frame.")
    return w, h




def resolve_style_args(style, bg_color, highlight_color=None):
    """Normalize the raw `--style` / `--bg-color` / `--highlight-color` strings
    from `main()` or the cell magic into the triple `build()` takes, raising
    `ValueError` with a listing of valid names on a bad one.

    Shared so both front ends accept exactly the same spellings and reject
    the same mistakes at parse time. Validating here matters: an unknown
    style would otherwise surface as a pygments ClassNotFound raised from
    inside the first frame render (after the trace has already executed the
    user's snippet), and a malformed color as an even less obvious failure
    deep in PIL or in _is_light()'s '#rrggbb' slicing.

    `bg_color` is restricted to '#rrggbb' (or BG_COLOR_NONE) rather than the
    full range of color spellings PIL accepts, because _is_light() parses it
    by slicing those exact six hex digits to pick readable caption colors."""
    if isinstance(style, str):
        if style not in BUILTIN_STYLES and style not in BUILTIN_THEMES:
            try:
                get_style_by_name(style)
            except Exception:
                if not os.path.isfile(style):
                    raise ValueError(
                        f"--style: unknown style {style!r} — expected one of "
                        f"{', '.join(style_names())}, or a path to a .theme file")
                try:
                    load_theme(style)      # fail here, not mid-render
                except Exception as e:
                    raise ValueError(f"--style: {style!r} is not a readable "
                                     f".theme file ({e})")
    return (style,
            _hex_color_arg("--bg-color", bg_color,
                           "to use the style's own background"),
            _hex_color_arg("--highlight-color", highlight_color,
                           "to use the style's own highlight color",
                           allow=(HIGHLIGHT_PANEL,)))


def _unquote(value):
    """Strip one matched pair of surrounding quotes.

    The two front ends disagree about quoting and neither can be changed: on
    the CLI a bare '#rrggbb' would be swallowed as a shell comment, so the
    docs (rightly) show --bg-color '#1F1F1F' and the shell removes the quotes
    before argparse ever sees them. In a %%snippet-cast line there is no
    shell — IPython's parse_argstring hands the value over with the quotes
    still attached — so the exact spelling the docs teach was rejected as
    not-a-hex-color. Unquoting here makes both spellings work in both places
    (a no-op on the CLI, where they are already gone)."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1].strip()
    return value


def _hex_color_arg(flag, value, none_means, allow=()):
    """One raw color string from `main()`/the cell magic -> '#rrggbb' or None.

    BG_COLOR_NONE ('none') maps to None, which each caller reads as its own
    "no override" default. Only '#rrggbb' is accepted, not the wider set PIL
    would take, because _is_light() and _mix() both parse a color by slicing
    those exact six hex digits. `allow` lists extra literal spellings that
    pass through untouched (HIGHLIGHT_PANEL, for --highlight-color)."""
    if not isinstance(value, str):
        return value
    value = _unquote(value.strip())
    if value.lower() == BG_COLOR_NONE:
        return None
    if value.lower() in allow:
        return value.lower()
    if not BG_COLOR_RE.match(value):
        extra = "".join(f", {a!r}" for a in allow)
        raise ValueError(f"{flag}: {value!r} is not a '#rrggbb' hex color "
                         f"(or {BG_COLOR_NONE!r} {none_means}{extra})")
    return value


def resolve_panel_args(state_bg_color, state_fg_color):
    """Validate the raw `--state-bg-color`/`--state-fg-color` strings, as
    resolve_style_args() does for the code colors. Either may be None (or
    'none') for "leave the panel's own default" — see _panel_colors()."""
    return (_hex_color_arg("--state-bg-color", state_bg_color,
                           "to keep the default panel background"),
            _hex_color_arg("--state-fg-color", state_fg_color,
                           "to keep the default panel text colors"))


def resolve_output_path(output, output_dir, name):
    """The `-o/--output` path if given, else `output_dir/name.mp4` — and
    makes sure the destination directory exists."""
    out_path = output if output is not None else os.path.join(output_dir, f"{name}.mp4")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    return out_path


def main():
    """Console-script entry point (`snippet-cast`): parses argv and calls `build`."""
    ap = argparse.ArgumentParser(description="Narrated screencast from an annotated .py snippet.")
    ap.add_argument("input", nargs="?", help="annotated Python file")
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
    ap.add_argument("--style", default=None, metavar="NAME",
                    help="syntax highlighting theme: a built-in name "
                         f"({', '.join(sorted(BUILTIN_STYLES) + sorted(BUILTIN_THEMES))}), "
                         "any pygments style name, or a path to a Pandoc/KDE "
                         f".theme file (--style {STYLE_LIST_ARG} prints every name) "
                         f"[default: {STYLE}; env: SNIPPET_CAST_STYLE]")
    ap.add_argument("--bg-color", default=None, metavar="HEX",
                    help="background behind the code and canvas as '#rrggbb', "
                         f"overriding the style's own; {BG_COLOR_NONE!r} uses the "
                         f"style's [default: {BG_COLOR}; env: SNIPPET_CAST_BG_COLOR]")
    ap.add_argument("--highlight-color", default=None, metavar="HEX",
                    help="band behind the highlighted code line as '#rrggbb', "
                         f"overriding the style's own; {HIGHLIGHT_PANEL!r} "
                         "matches the STATE panel background (so the two read "
                         f"as one surface), {BG_COLOR_NONE!r} uses the style's "
                         f"[default: {HIGHLIGHT_COLOR}; "
                         "env: SNIPPET_CAST_HIGHLIGHT_COLOR]")
    ap.add_argument("--screenflow", nargs="?", const=SCREENFLOW_SIZE,
                    default=None, metavar="WxH",
                    help="render onto a fixed frame of this size with the "
                         "content centred, instead of a canvas sized to the "
                         "snippet — for dropping straight onto a video-editor "
                         "timeline. Nothing is scaled, so text stays crisp; "
                         "a snippet too big for the frame is an error naming "
                         "the --font-size that would fit "
                         f"[bare flag: {SCREENFLOW_SIZE}; env: "
                         "SNIPPET_CAST_SCREENFLOW]")
    ap.add_argument("--font-size", type=int, default=None, metavar="PX",
                    help="code font size in pixels; the state panel and captions "
                         "scale with it, each keeping its own offset "
                         f"[default: {FONT_SIZE}; env: SNIPPET_CAST_FONT_SIZE]")
    ap.add_argument("--state-bg-color", default=None, metavar="HEX",
                    help="background of the state panel as '#rrggbb'; "
                         f"{BG_COLOR_NONE!r} keeps the default "
                         f"[default: {PANEL_BG}; env: SNIPPET_CAST_STATE_BG_COLOR]")
    ap.add_argument("--state-fg-color", default=None, metavar="HEX",
                    help="text in the state panel as '#rrggbb' — names and "
                         "values both; "
                         f"{BG_COLOR_NONE!r} keeps the default green-on-white "
                         "scheme [env: SNIPPET_CAST_STATE_FG_COLOR]")
    ap.add_argument("--pause", type=float, default=None, metavar="SECONDS",
                    help="seconds of silence to hold on each beat's frame after "
                         "its narration finishes, before the next beat begins "
                         "(in two-pass mode, also between the two passes); "
                         "giving this explicitly also allows a snippet with NO "
                         f"{MARKER} narration at all, rendering one silent frame "
                         "per code line held for this long, to narrate later "
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
    ap.add_argument("--order", choices=[ORDER_SOURCE, ORDER_EXEC], default=None,
                    help="playback order of the narrated lines: "
                         f"{ORDER_SOURCE!r} (top to bottom, or the 'N) ' order "
                         f"the file gives) or {ORDER_EXEC!r} (the order Python "
                         "visits them — each line highlighted on entry with its "
                         "pre-state, then again on completion, where the "
                         "narration plays). 'exec' needs the trace and is "
                         "redundant with --every "
                         f"[default: {ORDER_SOURCE}; env: SNIPPET_CAST_ORDER]")
    ap.add_argument("-q", "--quiet", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="suppress progress, notes and the traced snippet's own "
                         "output; errors still go to stderr, and "
                         "--export-script/--style list still print their result "
                         "[env: SNIPPET_CAST_QUIET]")
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
    # Flag only, deliberately: the check below exists to catch someone
    # typing "--record --tts say", not to veto --record because a
    # project-wide activation env happens to name a backend.
    tts_explicit = args.tts is not None
    # Compared against the default, not merely "is it set": a project-wide
    # activation env (pixi's [tool.pixi.activation.env], a shell profile) may
    # materialise EVERY SNIPPET_CAST_* var at its default value, and that is
    # not the mistake this check exists to catch — which is passing an audio
    # directory while forgetting --tts manual. Treating a default-valued env
    # var as "explicit" made a bare invocation exit here and render nothing.
    _env_manual_dir = os.environ.get("SNIPPET_CAST_MANUAL_AUDIO_DIR")
    manual_dir_explicit = (
        args.manual_audio_dir is not None
        or (_env_manual_dir is not None
            and _env_manual_dir != MANUAL_AUDIO_DIR_DEFAULT))
    # Same trick for --pause: asking for a specific frame length is what opts
    # a narration-less snippet into a silent render (build(allow_unnarrated=)).
    # PAUSE_DEFAULT is > 0, so testing the resolved value can't tell "I want
    # silent frames this long" from "I never mentioned --pause" — and a
    # forgotten '#:' must still report No narration found.
    pause_explicit = (args.pause is not None
                      or (os.environ.get("SNIPPET_CAST_PAUSE") not in
                          (None, str(PAUSE_DEFAULT))))
    resolve_env_defaults(
        args, tts="say", no_trace=False, every=False, subtitles=False, typing=False,
        typing_speed=TYPE_SPEED, pause=PAUSE_DEFAULT, export_script=False,
        manual_audio_dir=MANUAL_AUDIO_DIR_DEFAULT, record=False, no_frame=False,
        quiet=False, order=ORDER_SOURCE,
        name="out", output_dir=".", style=STYLE,
        bg_color=BG_COLOR if BG_COLOR else BG_COLOR_NONE,
        state_bg_color=PANEL_BG, state_fg_color=None,
        highlight_color=HIGHLIGHT_COLOR, font_size=FONT_SIZE, screenflow=None)
    global _QUIET
    _QUIET = bool(args.quiet)     # covers every _say() from here on, including
                                  # the argument-validation notes just below
    if args.style == STYLE_LIST_ARG:
        # A listing query, not a render — the one invocation with no input
        # file, which is why `input` is nargs="?" above. Every other path
        # still requires it, with argparse's own wording.
        print("\n".join(style_names()))
        return
    # Resolved BEFORE the missing-input check on purpose: --screenflow takes an
    # optional value, so `snippet-cast --screenflow in.py` hands the file to the
    # flag and leaves `input` empty. Checking input first would answer that with
    # argparse's generic "required: input" instead of the hint that says where
    # the file actually went.
    try:
        args.screenflow = resolve_screenflow_arg(args.screenflow)
    except ValueError as e:
        sys.exit(str(e))
    if args.input is None:
        ap.error("the following arguments are required: input")
    try:
        args.style, args.bg_color, args.highlight_color = resolve_style_args(
            args.style, args.bg_color, args.highlight_color)
        args.state_bg_color, args.state_fg_color = resolve_panel_args(
            args.state_bg_color, args.state_fg_color)
    except ValueError as e:
        sys.exit(str(e))
    if args.tts not in BACKENDS:
        sys.exit(f"--tts: invalid choice {args.tts!r} (choose from {', '.join(BACKENDS)})")

    if args.every and args.no_trace:
        sys.exit("--every needs execution; drop --no-trace.")
    if args.typing and args.every:
        _say("note: --typing has no effect with --every (full code is already shown).")
    if args.pause < 0:
        sys.exit("--pause must be >= 0.")
    if args.typing_speed <= 0:
        sys.exit("--typing-speed must be > 0.")
    if args.font_size < FONT_SIZE_MIN:
        sys.exit(f"--font-size must be >= {FONT_SIZE_MIN}.")

    if args.record:
        if args.quiet:
            sys.exit("--quiet can't be used with --record: recording is an "
                     "interactive session whose prompts are that output.")
        if tts_explicit and args.tts != "manual":
            sys.exit(f"--record always uses the manual backend; got --tts {args.tts!r}. "
                     "Drop --tts (or set it to manual) when using --record.")
        args.tts = "manual"
    elif manual_dir_explicit and args.tts != "manual":
        sys.exit("--manual-audio-dir only applies with --tts manual (or --record).")

    if args.export_script:
        for line in export_script(args.input, trace=not args.no_trace,
                                  every=args.every, quiet=args.quiet,
                                  order=args.order):
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
                         show_frame=not args.no_frame, font_size=args.font_size,
                         screenflow=args.screenflow, order=args.order,
                         style=args.style, bg_color=args.bg_color,
                         state_bg_color=args.state_bg_color,
                         state_fg_color=args.state_fg_color,
                         highlight_color=args.highlight_color)
        return

    build(args.input, out_path, args.tts,
          trace=not args.no_trace, every=args.every,
          subtitles=args.subtitles, typing=args.typing,
          typing_speed=args.typing_speed, pause=args.pause,
          manual_audio_dir=args.manual_audio_dir,
          style=args.style, bg_color=args.bg_color,
          state_bg_color=args.state_bg_color, state_fg_color=args.state_fg_color,
          highlight_color=args.highlight_color, allow_unnarrated=pause_explicit,
          font_size=args.font_size, screenflow=args.screenflow,
          quiet=args.quiet, order=args.order)


if __name__ == "__main__":
    main()
