"""
Jupyter cell magic for snippet-cast: %%snippet-cast

Importing this module inside a live IPython/Jupyter kernel registers the
magic automatically:

    import snippet_cast.magic

A plain `import snippet_cast` does this for you too, as long as IPython is
already installed and a live kernel is running: `snippet_cast/__init__.py`
runs the identical `get_ipython()`-gated check and only then imports this
module. Outside a live kernel, or without IPython installed, that same check
bails out before ever importing this module — so `import snippet_cast` in a
plain script, or in an environment without the `jupyter` extra, still never
requires IPython. `%load_ext snippet_cast.magic` still works too, and is the
only option outside a live kernel, or to force re-registration after editing
this file under autoreload.

Then write an annotated snippet directly in a cell and render + display it
inline, instead of saving it to a separate .py file first:

    %%snippet-cast -o out.mp4 --tts silent --subtitles
    def fib(n):             #: We define fib, taking one argument, n.
        a, b = 0, 1         #: Start from the first two Fibonacci numbers.
        for _ in range(n):  #: Loop n times.
            a, b = b, a + b #: Advance the pair; b becomes the running sum.
        return a            #: Return a — the nth Fibonacci number.
    result = fib(7)         #: Call fib with seven; result becomes {result}.

All the flags `snippet-cast --help` lists are available here too (`--tts`,
`--every`, `--subtitles`, `--typing`/`--typing-speed`, `--pause`, `--no-trace`,
`--export-script`, `--tts manual --manual-audio-dir DIR`, `--record`
`--no-frame`, `-n/--name`, `-d/--output-dir` — see SETUP.md for the
interactive-recording workflow, which works the same in a notebook cell as
in a terminal). `--tts` defaults to `say` here, exactly as on the CLI — that
is macOS-only, so on another platform either pass `--tts silent` (a timing
stand-in that always works, with no setup) or set `SNIPPET_CAST_TTS` once in
an earlier cell.

Output is QUIET by default, again as on the CLI: the per-beat commentary and
every `note:` need `-v`/`--verbose`. Only a snippet that won't compile or
raises part-way still reports on its own (stderr), along with errors.

When the top of the cell is already spoken for — a Quarto page, where the
`#|` directives have to be the first lines, and so does `%%snippet-cast` —
use `video()` instead. It is this same front end as a plain function call,
taking the snippet as a string and returning the video to display:

    from snippet_cast import video

    video(code, tts="silent", subtitles=True)

Both share `_resolve_render_options()`/`_resolve_output_path()`, so they
resolve every option identically and cannot drift apart.

Every flag (except -o/--output) also has a `SNIPPET_CAST_<NAME>` environment
variable default, e.g. `os.environ["SNIPPET_CAST_PAUSE"] = "0.6"` in an
earlier cell — read fresh on every cell run, so setting one in cell N is
picked up by `%%snippet-cast` in cell N+1 (unlike an argparse `default=`,
which would only ever see the value from when this module was imported).
An explicit flag on the `%%snippet-cast` line always overrides its
environment variable. Piper/ElevenLabs config (the `PIPER_*`/`ELEVENLABS_*`
env vars) works exactly as on the command line.
"""
import argparse
import contextlib
import hashlib
import html
import os
import sys
import tempfile
from types import SimpleNamespace

from IPython import get_ipython
from IPython.core.magic import Magics, line_cell_magic, magics_class
from IPython.core.magic_arguments import argument, magic_arguments, parse_argstring
from IPython.display import HTML, Image, Video, clear_output, display

from .screencast import (
    BACKENDS,
    BG_COLOR,
    BG_COLOR_NONE,
    BUILTIN_STYLES,
    BUILTIN_THEMES,
    FONT_SIZE,
    FONT_SIZE_MIN,
    SCREENFLOW_SIZE,
    HIGHLIGHT_COLOR,
    HIGHLIGHT_PANEL,
    MANUAL_AUDIO_DIR_DEFAULT,
    ORDER,
    ORDER_EXEC,
    ORDER_SOURCE,
    OUTPUT_DIR_DEFAULT,
    PANEL_BG,
    PAUSE_DEFAULT,
    STYLE,
    TYPE_SPEED,
    build,
    export_script,
    record_narration,
    resolve_env_defaults,
    resolve_output_path,
    resolve_panel_args,
    resolve_screenflow_arg,
    resolve_style_args,
    _is_light,
    _resolve_style,
    _scan_comments,
)


class _LiveRecordView:
    """--record's notebook presentation: status text and the current frame
    each update ONE existing cell output in place (via IPython's
    `display_id`/`DisplayHandle.update()`) instead of a fresh `display()`
    call per print()/frame piling up as a growing stack of separate
    outputs. Used two ways at once by the cell magic: as `frame_fn`
    (record_narration()'s per-beat preview hook — this class is directly
    callable) and as a `contextlib.redirect_stdout` target (its `write()`/
    `flush()` capture every print() screencast.py makes during the call,
    keeping a short rolling window rather than the full scrollback).
    screencast.py itself stays print()/frame_fn-agnostic — none of this
    exists from its side, same as any other frame_fn/input_fn/etc caller."""

    def __init__(self, max_lines=8):
        self._max_lines = max_lines
        self._lines = []
        self._buf = ""
        self._status_handle = None
        self._frame_handle = None
        # Captured now, before the caller wraps sys.stdout with this object
        # (contextlib.redirect_stdout(view)) -- needed below so display()'s
        # OWN incidental stdout writes (if any) don't loop back into this
        # object's write() again while it's still the active redirect target.
        self._real_stdout = sys.stdout

    def write(self, s):
        self._buf += s
        added = False
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line:
                self._lines.append(line)
                added = True
        if not added:
            # print() calls .write() twice per line: once with the content,
            # once more with just the trailing "\n" (its default `end`).
            # Updating on the FIRST (no newline yet, no complete line) would
            # flash the display through an incomplete/placeholder state on
            # every single print() -- wait for a full line instead.
            return
        self._lines = self._lines[-self._max_lines:]
        text = "\n".join(self._lines) or " "  # never empty: display() dislikes ""
        # HTML + <pre>, not a bare str: display() renders a plain string via
        # repr() (quoted, with literal \n escapes -- confirmed, not just a
        # test-harness quirk), which is not what a multi-line status readout
        # should look like. <pre> preserves whitespace/newlines exactly,
        # unambiguously, in any HTML-capable frontend.
        rendered = HTML(f"<pre>{html.escape(text)}</pre>")
        with contextlib.redirect_stdout(self._real_stdout):
            if self._status_handle is None:
                self._status_handle = display(rendered, display_id=True)
            else:
                self._status_handle.update(rendered)

    def flush(self):
        pass

    def __call__(self, path):
        img = Image(filename=path)
        with contextlib.redirect_stdout(self._real_stdout):
            if self._frame_handle is None:
                self._frame_handle = display(img, display_id=True)
            else:
                self._frame_handle.update(img)

    def clear(self):
        """Empty the status/frame areas entirely. Call once the session's
        real result — the rendered video — is about to replace them, so the
        ephemeral per-beat scrollback doesn't linger underneath it. Do NOT
        call this on an aborted/errored/incomplete session — that trail
        (e.g. 'aborted — no changes made', or a 'still have no recording'
        note) is exactly what the user needs to see, not something to wipe."""
        with contextlib.redirect_stdout(self._real_stdout):
            clear_output(wait=True)


# The rendered frame is sized to the snippet (see plan_canvas), so a wide line
# of code makes a wide video. RESPONSIVE_STYLE caps it at whatever container it
# lands in — a Quarto HTML column, a narrow notebook pane — while `height:auto`
# keeps the aspect ratio. It never scales a small video UP, so it only ever
# takes effect when the video would otherwise overflow.
RESPONSIVE_STYLE = "max-width:100%;height:auto"

# Chrome/Safari draw the native control bar on a tall black gradient scrim —
# on a light theme it covers roughly the bottom two-thirds of the frame and
# hides the code. Dropping the scrim alone is not enough: the glyphs are
# WHITE, so they vanish against a light background. invert(1) on the panel
# flips them to black; it is scoped to the controls, so the video itself is
# untouched (verified in headless Chrome: frame luminance is identical with
# and without the filter). Firefox ignores -webkit- pseudo-elements entirely
# and keeps its own controls, which already have a legible flat backdrop.
# Two variants, and they need DISTINCT class names: a Quarto page can hold a
# light cell and a dark one, and two <style> blocks targeting the same class
# would leave the later rule governing BOTH videos.
# Two variants, and they need DISTINCT class names: a Quarto page can hold a
# light cell and a dark one, and two <style> blocks targeting the same class
# would leave the later rule governing BOTH videos.
CONTROLS_CLASSES = {
    False: "snippet-cast-controls-dark",    # light frame: flip glyphs to dark
    True:  "snippet-cast-controls-light",   # dark frame: leave them white
}


def _controls_css(light):
    """(class name, `<style>` block) for the video's control bar.

    The gradient always goes: Chrome/Safari draw the native controls on a tall
    black scrim that covers roughly the bottom two-thirds of the frame and
    hides the code. What varies is the glyphs, which the UA draws WHITE:
    against a light frame they then disappear, so `filter:invert(1)` flips
    them dark; against a dark frame they are already legible and inverting
    them is what makes them disappear (measured in headless Chrome on a
    monokai render: peak luminance 31 inverted vs 255 left alone).

    So `light` means "light-coloured glyphs", i.e. the dark-frame case. The
    filter is scoped to the panel, never the video — frame luminance is
    identical with and without it."""
    cls = CONTROLS_CLASSES[bool(light)]
    rule = "background-image:none!important;"
    if not light:
        rule += "filter:invert(1);"
    return cls, f"<style>.{cls}::-webkit-media-controls-panel{{{rule}}}</style>"


def _light_controls_for(style, bg_color, highlight_color, override):
    """Whether the control glyphs should stay light (white).

    `override` is the tri-state `--light-controls`: True/False force it, None
    (the default) picks from the frame's own resolved background via
    `_is_light()` — the same luminance test plan_canvas() uses to choose
    caption colors. Auto-detecting means the shipped light theme and
    `--style monokai` both come out right with no flag at all; the override is
    there for the cases luminance cannot judge, such as a busy custom theme."""
    if override is not None:
        return bool(override)
    try:
        bg = _resolve_style(style, bg_color, highlight_color).background_color
        return not _is_light(bg or "#000000")
    except Exception:
        return False   # a bad style is reported elsewhere; don't fail on display


def _help_text(parser):
    """The parser's own help, cleaned of magic_arguments' docstring styling.

    `MagicArgumentParser.format_help()` is written for a reST docstring: it
    opens with a `::` literal-block marker and calls the magic
    `%snippet_cast`. Neither reads well in a cell, where this is being printed
    for a person to read."""
    lines = parser.format_help().splitlines()
    while lines and lines[0].strip() in ("", "::"):
        lines.pop(0)
    return "\n".join(lines).replace("%snippet_cast", "%%snippet-cast")


def _video(out_path, embed, responsive, light_controls=False):
    """`IPython.display.Video` for the finished file.

    `responsive` styles the `<video>` ELEMENT rather than wrapping it in a
    styled div: a wrapper would be capped at 100% while the video inside kept
    overflowing it. Done through Video's own `html_attributes` (which replaces
    the default `"controls"` wholesale — hence repeating it here) so the
    embed/base64 and plain-src paths both keep working untouched.

    The control-bar restyling is unconditional (see _controls_css) and needs a
    real `<style>` block — an inline `style` attribute cannot target a
    `::-webkit-media-controls-*` pseudo-element — so this returns `HTML`
    rather than `Video`. `display()` takes either. `light_controls` selects
    which of the two variants.

    CLI-side there is deliberately no equivalent — these are purely about how
    a notebook/Quarto front end lays the result out, and `snippet-cast` writes
    a file rather than displaying one.
    """
    cls, css = _controls_css(light_controls)
    attrs = ["controls", f'class="{cls}"']
    if responsive:
        attrs.append(f'style="{RESPONSIVE_STYLE}"')
    video = Video(out_path, embed=embed, html_attributes=" ".join(attrs))
    return HTML(css + video._repr_html_())


# Where a cell's video goes when it was given no -o/-n/-d of its own. A dot
# directory beside the notebook rather than the notebook's own folder, so a
# student running the notebook ends up with one hidden, self-ignoring
# directory instead of out.mp4 / hello.mp4 / ... scattered next to their work.
# It stays RELATIVE on purpose: an absolute path (a system tempdir, say) is
# not servable by a notebook front end and is not copied by Quarto, so the
# video would render as a 300x150 black box. Verified that Quarto's resource
# globbing does reach into a dot directory.
#
# It IS OUTPUT_DIR_DEFAULT, not a second directory that happens to match: a
# cell naming its video with -n lands beside the hashed ones, and so does a
# plain `snippet-cast` run from the terminal. Only the FILE NAME differs
# between the two — hashed here, `-n`/`out` there.
CACHE_DIR = OUTPUT_DIR_DEFAULT

# Quarto reads its per-cell options from `#|` comments at the top of a cell
# (`#| fig-column: margin`, `#| echo: false`, ...). They are directives to the
# renderer, not part of the snippet, so they must not be typed out, narrated
# or highlighted in the video.
DIRECTIVE_PREFIX = "#|"


def _strip_directives(cell):
    """Drop whole lines that are `#|` cell directives.

    Found through `tokenize`, not a regex, for the same reason parse() does
    (critical invariant 5): a `#|` inside a string literal is not a comment,
    and blanket line-matching would corrupt code like
    `sql = \"\"\"...\n#| not a directive\n\"\"\"`. Only a comment that IS the
    whole line counts — a trailing `x = 1  #| ...` is left alone.

    Whole lines go, rather than being blanked: everything downstream re-derives
    its line numbers from the rewritten text (same trick as
    resolve_footnotes()), and a blank row would otherwise take up height in
    every frame, since plan_canvas() sizes the canvas from the full code and
    _render_code() keeps blank rows (invariant 12)."""
    lines = cell.splitlines(keepends=True)
    drop = set()
    for line_no, (col, text) in _scan_comments(cell).items():
        if text.startswith(DIRECTIVE_PREFIX) and not lines[line_no - 1][:col].strip():
            drop.add(line_no)
    if not drop:
        return cell
    return "".join(ln for i, ln in enumerate(lines, start=1) if i not in drop)


def _hashed_output_path(*parts):
    """Default output path for a snippet given no -o/-n/-d of its own:
    CACHE_DIR/<hash of `parts`>.mp4. The cell magic hashes the magic line AND
    the cell body; video() hashes the snippet string it was handed.

    Keyed on the snippet's own text rather than a random name, which matters
    twice over. Two different cells never collide (before this, every cell
    defaulted to `out.mp4`, so in a notebook of N cells the first N-1 videos
    were silently overwritten by the last). And re-running an UNCHANGED cell
    reuses its file instead of leaving another orphan behind, which a random
    name would do on every single execution — the directory would grow
    without bound over an afternoon of tweaking narration.

    Editing a cell does strand its previous file; the directory is hidden and
    self-ignoring, and nothing can safely tell which files other notebooks in
    the same folder still reference.

    resolve_output_path() makes the directory and drops the self-ignoring
    `.gitignore` — CACHE_DIR *is* OUTPUT_DIR_DEFAULT, so a hashed cell video
    and a plain `snippet-cast` run land in the same place."""
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]
    return resolve_output_path(None, CACHE_DIR, digest)


def _resolve_output_path(args, *hash_parts):
    """Where a rendered snippet goes. An explicit -o/-n/-d (or `out=`/`name=`/
    `output_dir=`) wins, as does a SNIPPET_CAST_NAME/SNIPPET_CAST_OUTPUT_DIR
    that DIFFERS from the default; otherwise the hashed cache name.

    Env vars count only when they differ from the default because a
    project-wide activation env (pixi's [tool.pixi.activation.env], a shell
    profile) may materialise all of SNIPPET_CAST_* at their defaults, and
    "SNIPPET_CAST_NAME=out" expresses no preference — treating it as one
    silently put every cell back to overwriting a single out.mp4.

    Must be called BEFORE anything resolves `name`/`output_dir` from the
    environment: the "did the caller say anything?" test is `is None`, which
    the resolution step is about to erase. It does that resolution itself."""
    output_explicit = (
        any(v is not None for v in (args.output, args.name, args.output_dir))
        or os.environ.get("SNIPPET_CAST_NAME", "out") != "out"
        or os.environ.get("SNIPPET_CAST_OUTPUT_DIR",
                          OUTPUT_DIR_DEFAULT) != OUTPUT_DIR_DEFAULT)
    resolve_env_defaults(args, name="out", output_dir=OUTPUT_DIR_DEFAULT)
    if output_explicit:
        return resolve_output_path(args.output, args.output_dir, args.name)
    return _hashed_output_path(*hash_parts)


def _resolve_render_options(args):
    """Fill in every SNIPPET_CAST_* default the RENDER options have, validate
    them, and work out the control-glyph color — the whole option-resolution
    half of a notebook front end, shared by the `%%snippet-cast` cell magic
    and `video()` so the two can never drift apart.

    Deliberately does NOT cover the OUTPUT options (-o/-n/-d, see
    _resolve_output_path) or the magic-only ones (--export-script, --record,
    --no-frame): a caller that has them resolves them itself.

    Mutates `args` in place and returns the handful of "was this given
    explicitly, as opposed to defaulted?" answers its callers still need —
    each one captured here BEFORE resolution erases the None that expresses
    it. Raises ValueError, carrying the bare message, for every bad value;
    the cell magic prefixes it with "snippet-cast: " and prints, while
    video() lets it propagate."""
    # Captured before resolve_env_defaults fills in the tts/manual_audio_dir/
    # quiet fallbacks below, so --record can tell an explicit --tts or env var
    # apart from the hardcoded default it is about to silently override.
    #
    # Flag only, deliberately: the check that uses this exists to catch
    # someone typing "--record --tts say", not to veto --record because a
    # project-wide activation env happens to name a backend.
    tts_explicit = args.tts is not None
    # Same "flag only" rule, and for the same reason: --quiet is ON by default
    # now, so a bare --record must NOT trip the "recording is interactive"
    # check — only someone who actually typed -q did the thing it catches.
    quiet_explicit = args.quiet is not None
    # Compared against the default, not merely "is it set": a project-wide
    # activation env may materialise EVERY SNIPPET_CAST_* var at its default
    # value, and that is not the mistake this check exists to catch — which is
    # passing an audio directory while forgetting --tts manual. Treating a
    # default-valued env var as "explicit" made a bare invocation exit here
    # and render nothing.
    _env_manual_dir = os.environ.get("SNIPPET_CAST_MANUAL_AUDIO_DIR")
    manual_dir_explicit = (
        args.manual_audio_dir is not None
        or (_env_manual_dir is not None
            and _env_manual_dir != MANUAL_AUDIO_DIR_DEFAULT))
    # Same trick for --pause: asking for a specific frame length is what opts
    # a narration-less snippet into a silent render — PAUSE_DEFAULT is > 0, so
    # the resolved value can't tell that apart from a forgotten '#:', which
    # must still report No narration found.
    pause_explicit = (args.pause is not None
                      or (os.environ.get("SNIPPET_CAST_PAUSE") not in
                          (None, str(PAUSE_DEFAULT))))
    resolve_env_defaults(
        args, tts="say", no_trace=False, every=False, subtitles=False,
        typing=False, typing_speed=TYPE_SPEED, pause=PAUSE_DEFAULT,
        manual_audio_dir=MANUAL_AUDIO_DIR_DEFAULT,
        quiet=True, verbose=False, responsive=True, order=None, style=STYLE,
        bg_color=BG_COLOR if BG_COLOR else BG_COLOR_NONE,
        state_bg_color=PANEL_BG, state_fg_color=None,
        highlight_color=HIGHLIGHT_COLOR, font_size=FONT_SIZE, screenflow=None)
    # -v/--verbose is simply the inverse of -q/--quiet, which is on by
    # default; it wins when both are given, since it is the one that had to be
    # typed to mean anything. (--no-quiet says the same thing.)
    if args.verbose:
        args.quiet = False
    # Tri-state, so it can't go through resolve_env_defaults(), whose whole
    # contract is "fill anything still None" — None is a meaningful value here
    # (auto-detect from the frame background).
    if args.light_controls is None:
        raw = os.environ.get("SNIPPET_CAST_LIGHT_CONTROLS")
        # "auto" (and empty) keep the detection, so the variable can be
        # present in an activation env without forcing a choice.
        if raw is not None and raw.strip().lower() not in ("", "auto"):
            args.light_controls = raw.strip().lower() in ("1", "true", "yes", "on")
    args.style, args.bg_color, args.highlight_color = resolve_style_args(
        args.style, args.bg_color, args.highlight_color)
    args.state_bg_color, args.state_fg_color = resolve_panel_args(
        args.state_bg_color, args.state_fg_color)
    args.screenflow = resolve_screenflow_arg(args.screenflow)
    if args.font_size < FONT_SIZE_MIN:
        raise ValueError(f"--font-size must be >= {FONT_SIZE_MIN}.")
    if args.tts not in BACKENDS:
        raise ValueError(f"--tts: invalid choice {args.tts!r} "
                         f"(choose from {', '.join(BACKENDS)})")
    # Resolved AFTER the style/color strings are normalized, so the luminance
    # test sees the same background the frames are rendered on.
    light = _light_controls_for(args.style, args.bg_color,
                                args.highlight_color, args.light_controls)
    return SimpleNamespace(light=light, pause_explicit=pause_explicit,
                           tts_explicit=tts_explicit,
                           quiet_explicit=quiet_explicit,
                           manual_dir_explicit=manual_dir_explicit)



def video(code, tts=None, out=None, name=None, output_dir=None, trace=None,
          every=None, subtitles=None, typing=None, typing_speed=None,
          pause=None, order=None, style=None, bg_color=None,
          highlight_color=None, state_bg_color=None, state_fg_color=None,
          font_size=None, screenflow=None, manual_audio_dir=None, quiet=None,
          verbose=None, embed=False, responsive=None, light_controls=None):
    """Render an annotated snippet STRING and return the video, ready to
    display. `%%snippet-cast` as a plain function call.

    Reach for this instead of the cell magic whenever the top of the cell is
    already spoken for — a Quarto page, where the `#|` directives must be the
    first lines — or when the snippet is being built up in Python rather than
    typed out. `code` is exactly the text you would write under
    `%%snippet-cast`::

        from snippet_cast import video

        video('''
        def add_one(n):  #: We define a function // n points to {n}.
            return n + 1 #: ...and return one more // returns {n} plus one.
        y = add_one(2)   #: Call it // y now points to {y}.
        ''', tts="silent", subtitles=True)

    Returns an ``IPython.display.HTML`` — leave it as the cell's last
    expression and the video shows up inline, restyled exactly as the cell
    magic's is (see _video/_controls_css). `build()` is the equivalent for a
    snippet that already lives in its own .py file, and returns nothing.

    Every parameter mirrors the same-named `snippet-cast` option and, left at
    None, resolves the same way the cell magic's does: an explicit argument
    beats `SNIPPET_CAST_<NAME>` in the environment, which beats the shipped
    default (so `tts` is `say`, `order` is `exec`, and output is QUIET —
    pass `verbose=True` for the per-beat progress). `trace` is the one
    renamed: it follows `build()` rather than the `--no-trace` flag, so
    `trace=False` is what drops the state panel. `bg_color="none"` (and the
    same for the other colors) is the spelling for "use the style's own",
    matching the CLI.

    `out` sets the path outright; `name`/`output_dir` build one as
    ``output_dir/name.mp4``. Given none of the three — and no
    SNIPPET_CAST_NAME/SNIPPET_CAST_OUTPUT_DIR either — the video goes to
    `.snippet-cast/<hash of the snippet>.mp4`, so re-running an unchanged
    cell reuses its file and two snippets in one notebook never collide.

    `embed`, `responsive` and `light_controls` are display-only, exactly as
    on the cell magic; they have no CLI equivalent because `snippet-cast`
    writes a file rather than showing one.

    Raises `ValueError` — carrying the message `snippet-cast` would have
    printed — for a bad option or a snippet the renderer refuses (no
    narration, a rejected flag combination). Anything the snippet itself
    raises while being traced is reported by `build()` as it always is.

    Quarto `#|` directives are NOT stripped from `code`, unlike the cell
    magic's body: there they had to be, because the cell body WAS the
    snippet; here the directives sit above the call, outside the string, and
    silently deleting lines from a string the caller assembled deliberately
    would be the more surprising behavior.

    Recording narration and exporting a script stay on `record_narration()`
    and `export_script()`; both take a path, so write the snippet to a file
    first.
    """
    args = SimpleNamespace(
        tts=tts, output=out, name=name, output_dir=output_dir,
        # The public spelling follows build()'s `trace`, but the environment
        # variable is SNIPPET_CAST_NO_TRACE, so the negated name is what
        # resolve_env_defaults() has to see. None must stay None — it is what
        # says "nobody has expressed a preference yet".
        no_trace=None if trace is None else not trace,
        every=every, subtitles=subtitles, typing=typing,
        typing_speed=typing_speed, pause=pause, order=order, style=style,
        bg_color=bg_color, highlight_color=highlight_color,
        state_bg_color=state_bg_color, state_fg_color=state_fg_color,
        font_size=font_size, screenflow=screenflow,
        manual_audio_dir=manual_audio_dir, quiet=quiet, verbose=verbose,
        responsive=responsive, light_controls=light_controls)
    opts = _resolve_render_options(args)
    if opts.manual_dir_explicit and args.tts != "manual":
        raise ValueError("manual_audio_dir only applies with tts='manual'.")
    # Before anything fills name/output_dir in from the environment.
    out_path = _resolve_output_path(args, code)

    fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="snippet_cast_video_")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(code)
        try:
            build(tmp_path, out_path, args.tts,
                  trace=not args.no_trace, every=args.every,
                  subtitles=args.subtitles, typing=args.typing,
                  typing_speed=args.typing_speed, pause=args.pause,
                  manual_audio_dir=args.manual_audio_dir,
                  style=args.style, bg_color=args.bg_color,
                  state_bg_color=args.state_bg_color,
                  state_fg_color=args.state_fg_color,
                  highlight_color=args.highlight_color,
                  allow_unnarrated=opts.pause_explicit,
                  font_size=args.font_size, screenflow=args.screenflow,
                  quiet=args.quiet, order=args.order)
        except SystemExit as e:
            # build() reports a refused snippet or flag combination the way a
            # command-line tool does. That is right for `snippet-cast` and
            # wrong for a function: re-raise it as the ordinary exception a
            # caller can catch, and that a Quarto render fails loudly on
            # instead of quietly producing no video.
            raise ValueError(str(e.code)) from None
    finally:
        os.unlink(tmp_path)

    return _video(out_path, embed, args.responsive, opts.light)


@magics_class
class SnippetCastMagics(Magics):
    """Registers %%snippet-cast. Load with `%load_ext snippet_cast.magic`."""

    @magic_arguments()
    @argument("-o", "--output", default=None, metavar="PATH",
              help="explicit output MP4 path — overrides -n/--name and "
                   "-d/--output-dir if given")
    @argument("-n", "--name", default=None, metavar="NAME",
              help="basename (without extension) for the output file in "
                   "--output-dir, when -o/--output isn't given "
                   "[default: out; env: SNIPPET_CAST_NAME]")
    @argument("-d", "--output-dir", default=None, metavar="DIR",
              help="directory for the output file when -o/--output isn't "
                   f"given (created if missing) [default: {OUTPUT_DIR_DEFAULT}; "
                   "env: SNIPPET_CAST_OUTPUT_DIR]")
    @argument("--tts", choices=list(BACKENDS), default=None,
              help="TTS backend [default: say — macOS only, so pass "
                   "--tts silent (a no-setup timing stand-in) elsewhere; see "
                   "SETUP.md for piper/elevenlabs; env: SNIPPET_CAST_TTS] "
                   "(--record implies manual; passing --tts explicitly as "
                   "anything else together with --record is an error)")
    @argument("--no-trace", action="store_true", default=None,
              help="don't execute the snippet; skip the state panel "
                   "[env: SNIPPET_CAST_NO_TRACE]")
    @argument("--every", action=argparse.BooleanOptionalAction, default=None,
              help="one beat per execution of a line (animates loops) "
                   "[env: SNIPPET_CAST_EVERY]")
    @argument("--subtitles", action=argparse.BooleanOptionalAction, default=None,
              help="burn the narration text as a caption "
                   "[env: SNIPPET_CAST_SUBTITLES]")
    @argument("--typing", action=argparse.BooleanOptionalAction, default=None,
              help="type newly revealed lines character-by-character "
                   "[env: SNIPPET_CAST_TYPING]")
    @argument("--typing-speed", type=float, default=None, metavar="SECONDS",
              help=f"seconds to reveal each newly typed character "
                   f"[default: {TYPE_SPEED}; env: SNIPPET_CAST_TYPING_SPEED]")
    @argument("--style", default=None, metavar="NAME",
              help="syntax highlighting theme: a built-in name "
                   f"({', '.join(sorted(BUILTIN_STYLES) + sorted(BUILTIN_THEMES))}), "
                   "any pygments style name, or a path to a Pandoc/KDE .theme "
                   f"file [default: {STYLE}; env: SNIPPET_CAST_STYLE]")
    @argument("--bg-color", default=None, metavar="HEX",
              help="background behind the code and canvas as '#rrggbb', overriding "
                   f"the style's own; {BG_COLOR_NONE!r} uses the style's "
                   f"[default: {BG_COLOR}; env: SNIPPET_CAST_BG_COLOR]")
    @argument("--highlight-color", default=None, metavar="HEX",
              help="band behind the highlighted code line as '#rrggbb', "
                   f"overriding the style's own; {HIGHLIGHT_PANEL!r} matches "
                   "the STATE panel background (so the two read as one "
                   f"surface), {BG_COLOR_NONE!r} uses the style's "
                   f"[default: {HIGHLIGHT_COLOR}; env: SNIPPET_CAST_HIGHLIGHT_COLOR]")
    @argument("--screenflow", nargs="?", const=SCREENFLOW_SIZE,
              default=None, metavar="WxH",
              help="render onto a fixed frame of this size with the content "
                   "centred, instead of a canvas sized to the snippet — for "
                   "dropping straight onto a video-editor timeline. Nothing is "
                   "scaled, so text stays crisp "
                   f"[bare flag: {SCREENFLOW_SIZE}; env: SNIPPET_CAST_SCREENFLOW]")
    @argument("--font-size", type=int, default=None, metavar="PX",
              help="code font size in pixels; the state panel and captions "
                   "scale with it, each keeping its own offset "
                   f"[default: {FONT_SIZE}; env: SNIPPET_CAST_FONT_SIZE]")
    @argument("--state-bg-color", default=None, metavar="HEX",
              help="background of the state panel as '#rrggbb'; "
                   f"{BG_COLOR_NONE!r} keeps the default "
                   f"[default: {PANEL_BG}; env: SNIPPET_CAST_STATE_BG_COLOR]")
    @argument("--state-fg-color", default=None, metavar="HEX",
              help="text in the state panel as '#rrggbb' — names and values "
                   f"both; {BG_COLOR_NONE!r} keeps the "
                   "default scheme [env: SNIPPET_CAST_STATE_FG_COLOR]")
    @argument("--pause", type=float, default=None, metavar="SECONDS",
              help="seconds of silence held on each beat's frame after its "
                   "narration (in two-pass mode, also between the two passes); "
                   "giving this explicitly also allows a cell with NO '#:' "
                   "narration at all, rendering one silent frame per code line "
                   "held for this long, to narrate later "
                   f"[default: {PAUSE_DEFAULT}; env: SNIPPET_CAST_PAUSE]")
    @argument("--manual-audio-dir", default=None, metavar="DIR",
              help="directory of pre-recorded audio for --tts manual "
                   f"[default: {MANUAL_AUDIO_DIR_DEFAULT}; "
                   "env: SNIPPET_CAST_MANUAL_AUDIO_DIR]")
    @argument("--export-script", action=argparse.BooleanOptionalAction, default=None,
              help="print the ordered narration script instead of rendering "
                   "[env: SNIPPET_CAST_EXPORT_SCRIPT]")
    @argument("--record", action=argparse.BooleanOptionalAction, default=None,
              help="interactively record narration via the system microphone "
                   "(macOS only), then build with --tts manual (implied "
                   "automatically); see SETUP.md "
                   "[env: SNIPPET_CAST_RECORD]")
    @argument("--responsive", action=argparse.BooleanOptionalAction,
              default=None,
              help="style the displayed <video> so it never exceeds the width "
                   "of whatever it is rendered into (Quarto HTML, a wide "
                   "notebook, a narrow column) instead of keeping the exact "
                   "pixel size the snippet happened to produce; on by "
                   "default, --no-responsive keeps the intrinsic size "
                   "[default: True; env: SNIPPET_CAST_RESPONSIVE]")
    @argument("--light-controls", action=argparse.BooleanOptionalAction,
              default=None,
              help="keep the video controls' glyphs light (white) instead of "
                   "flipping them dark — for a dark theme such as "
                   "--style monokai. Left unset the right one is chosen from "
                   "the frame's own background, so this is rarely needed "
                   "[env: SNIPPET_CAST_LIGHT_CONTROLS]")
    @argument("-h", "--help", action="store_true", default=False,
              help="show this message, with every option and its default, and "
                   "stop without rendering the cell")
    @argument("--order", choices=[ORDER_SOURCE, ORDER_EXEC], default=None,
              help="playback order of the narrated lines: "
                   f"{ORDER_SOURCE!r} (top to bottom, or the 'N) ' order the "
                   f"cell gives) or {ORDER_EXEC!r} (the order Python visits "
                   "them — each line highlighted on entry with its pre-state, "
                   "then again on completion, where the narration plays). "
                   "Left at the default, 'exec' steps aside for a cell it "
                   "can't serve (--no-trace, --every, 'N) ' numbering, an "
                   "unnarrated --pause render); passing it explicitly makes "
                   f"those an error [default: {ORDER}; env: SNIPPET_CAST_ORDER]")
    @argument("-q", "--quiet", action=argparse.BooleanOptionalAction,
              default=None,
              help="suppress progress, 'note:' advice and the cell's own "
                   "output. ON BY DEFAULT — use -v/--verbose (or --no-quiet) "
                   "to see them. A snippet that won't compile or raises still "
                   "reports on stderr, as do errors, and --export-script still "
                   "returns its script [default: on; env: SNIPPET_CAST_QUIET]")
    @argument("-v", "--verbose", action="store_true", default=None,
              help="print the per-beat progress and every 'note:' — the "
                   "inverse of -q/--quiet, which is on by default. Wins over "
                   "-q if both are given [env: SNIPPET_CAST_VERBOSE]")
    @argument("--no-frame", action="store_true", default=None,
              help="with --record, don't pop each beat's rendered frame in "
                   "the system image viewer [env: SNIPPET_CAST_NO_FRAME]")
    @argument("--embed", action="store_true",
              help="embed the video as base64 in the notebook instead of linking the file")
    @line_cell_magic("snippet-cast")
    def snippet_cast(self, line, cell=None):
        """Render `cell` (an annotated Python snippet) into a screencast and
        display it inline. See the module docstring for a full example.

        Registered as a LINE magic too, purely so `--help` can be asked for on
        its own. IPython refuses a `%%`-form cell whose body is empty — the
        check is `cell == ''` in `InteractiveShell.run_cell_magic`, which
        raises before any magic function is reached, so `%%snippet-cast
        --help` with nothing under it cannot be handled here. Registering the
        name as a line magic is IPython's own remedy: `%snippet-cast --help`
        works, and its refusal message then ends "Did you mean the line magic
        %snippet-cast (single %)?" instead of leaving the reader stuck."""
        args = parse_argstring(self.snippet_cast, line)
        # Before anything else — including resolve_env_defaults() and the
        # argument validation below — so `%%snippet-cast --help` answers on
        # its own, whatever the rest of the line or the cell body says.
        # magic_arguments builds its parser with add_help=False, so without
        # this `--help` is simply an unrecognized argument and the cell fails.
        if args.help:
            print(_help_text(self.snippet_cast.parser))
            return
        if cell is None:
            # Invoked as `%snippet-cast ...` with no cell under it. Everything
            # below needs a snippet to render.
            print("snippet-cast: %snippet-cast on its own only answers "
                  "--help. To render a snippet use the cell form, "
                  "%%snippet-cast, with the code on the lines below it.",
                  file=sys.stderr)
            return
        # The three magic-only options; every other one is resolved by the
        # shared _resolve_render_options() below, which video() uses too.
        resolve_env_defaults(args, export_script=False, record=False,
                             no_frame=False)
        try:
            opts = _resolve_render_options(args)
        except ValueError as e:
            print(f"snippet-cast: {e}", file=sys.stderr)
            return
        light = opts.light

        if args.record:
            # Recording is an interactive session whose prompts ARE its
            # output, so the quiet default must never silence it. Only an
            # explicit -q is the mistake worth refusing.
            if args.quiet and opts.quiet_explicit:
                print("snippet-cast: --quiet can't be used with --record: "
                      "recording is an interactive session whose prompts are "
                      "that output.", file=sys.stderr)
                return
            args.quiet = False
            if opts.tts_explicit and args.tts != "manual":
                print(f"snippet-cast: --record always uses the manual backend; "
                      f"got --tts {args.tts!r}. Drop --tts (or set it to manual) "
                      "when using --record.", file=sys.stderr)
                return
            args.tts = "manual"
        elif opts.manual_dir_explicit and args.tts != "manual":
            print("snippet-cast: --manual-audio-dir only applies with --tts "
                  "manual (or --record).", file=sys.stderr)
            return

        fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="snippet_cast_cell_")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(_strip_directives(cell))

            if args.export_script:
                try:
                    for narration_line in export_script(
                            tmp_path, trace=not args.no_trace, every=args.every,
                            quiet=args.quiet, order=args.order):
                        print(narration_line)
                except SystemExit as e:
                    print(f"snippet-cast: {e.code}", file=sys.stderr)
                return

            out_path = _resolve_output_path(args, line, cell)

            if args.record:
                view = _LiveRecordView()
                try:
                    with contextlib.redirect_stdout(view):
                        committed = record_narration(
                            tmp_path, args.manual_audio_dir, out_path,
                            trace=not args.no_trace, every=args.every,
                            subtitles=args.subtitles, typing=args.typing,
                            typing_speed=args.typing_speed, pause=args.pause,
                            show_frame=not args.no_frame, frame_fn=view,
                            font_size=args.font_size, screenflow=args.screenflow,
                            order=args.order,
                            style=args.style, bg_color=args.bg_color,
                            state_bg_color=args.state_bg_color,
                            state_fg_color=args.state_fg_color,
                            highlight_color=args.highlight_color)
                except SystemExit as e:
                    print(f"snippet-cast: {e.code}", file=sys.stderr)
                    return
                if not committed:
                    return  # aborted mid-session; record_narration already said so
                if not os.path.exists(out_path):
                    return  # committed, but build_after was skipped (a
                             # missing-recordings note is already in view —
                             # leave it visible rather than clearing it)
                view.clear()
                display(_video(out_path, args.embed, args.responsive, light))
                return

            try:
                build(tmp_path, out_path, args.tts,
                      trace=not args.no_trace, every=args.every,
                      subtitles=args.subtitles, typing=args.typing,
                      typing_speed=args.typing_speed, pause=args.pause,
                      manual_audio_dir=args.manual_audio_dir,
                      style=args.style, bg_color=args.bg_color,
                      state_bg_color=args.state_bg_color,
                      state_fg_color=args.state_fg_color,
                      highlight_color=args.highlight_color,
                      allow_unnarrated=opts.pause_explicit,
                      font_size=args.font_size, screenflow=args.screenflow,
                      quiet=args.quiet, order=args.order)
            except SystemExit as e:
                print(f"snippet-cast: {e.code}", file=sys.stderr)
                return
        finally:
            os.unlink(tmp_path)

        display(_video(out_path, args.embed, args.responsive, light))


def _bodiless_cell_to_line_magic(lines):
    """Rewrite a bodiless `%%snippet-cast ...` into its line-magic form.

    IPython refuses a `%%` cell whose body is empty — `cell == ''` in
    `InteractiveShell.run_cell_magic`, which raises before any magic function
    is reached — so `%%snippet-cast --help` typed on its own could never be
    answered from inside the magic. This runs in the documented
    input-transformer stage, BEFORE that check, so the form people naturally
    reach for works.

    Deliberately narrow: it fires only when the first line opens with
    `%%snippet-cast` and every line under it is blank. A cell with a snippet
    in it is returned untouched, and so is every other cell in the notebook —
    this runs on all of them."""
    if not lines or not lines[0].lstrip().startswith("%%snippet-cast"):
        return lines
    if any(line.strip() for line in lines[1:]):
        return lines
    return [lines[0].replace("%%snippet-cast", "%snippet-cast", 1)] + lines[1:]


def load_ipython_extension(ipython):
    """Called by `%load_ext snippet_cast.magic`."""
    ipython.register_magics(SnippetCastMagics)
    # Idempotent: %load_ext can be called again, and autoreload re-imports.
    if not any(getattr(t, "__name__", "") == "_bodiless_cell_to_line_magic"
               for t in ipython.input_transformers_cleanup):
        ipython.input_transformers_cleanup.append(_bodiless_cell_to_line_magic)


_ip = get_ipython()
if _ip is not None:
    # Auto-register on `import snippet_cast.magic` when already inside a
    # live kernel/shell, so callers don't have to know about %load_ext.
    load_ipython_extension(_ip)
