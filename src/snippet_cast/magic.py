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
in a terminal), with one deliberate difference: `--tts` defaults to `silent`
here (not `say`), since it's the only backend guaranteed to work without any
setup, in any notebook environment.

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
    ORDER_EXEC,
    ORDER_SOURCE,
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
CACHE_DIR = ".snippet-cast"

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


def _cell_output_path(line, cell):
    """Default output path for a cell: CACHE_DIR/<hash of the cell>.mp4.

    Keyed on the cell's own text — the magic line AND the body — rather than a
    random name, which matters twice over. Two different cells never collide
    (today every cell defaults to `out.mp4`, so in a notebook of N cells the
    first N-1 videos are silently overwritten by the last). And re-running an
    UNCHANGED cell reuses its file instead of leaving another orphan behind,
    which a random name would do on every single execution — the directory
    would grow without bound over an afternoon of tweaking narration.

    Editing a cell does strand its previous file; the directory is hidden and
    self-ignoring, and nothing can safely tell which files other notebooks in
    the same folder still reference."""
    digest = hashlib.sha256((line + "\n" + cell).encode("utf-8")).hexdigest()[:12]
    os.makedirs(CACHE_DIR, exist_ok=True)
    # Keep the directory out of the student's git history without asking them
    # to remember a .gitignore entry.
    marker = os.path.join(CACHE_DIR, ".gitignore")
    if not os.path.exists(marker):
        with open(marker, "w") as fh:
            fh.write("*\n")
    return os.path.join(CACHE_DIR, f"{digest}.mp4")


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
                   "given (created if missing) [default: current directory; "
                   "env: SNIPPET_CAST_OUTPUT_DIR]")
    @argument("--tts", choices=list(BACKENDS), default=None,
              help="TTS backend [default: silent here — always works, no "
                   "setup; see SETUP.md for piper/elevenlabs; "
                   "env: SNIPPET_CAST_TTS] (--record implies manual; passing "
                   "--tts explicitly as anything else together with --record "
                   "is an error)")
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
                   "then again on completion, where the narration plays) "
                   f"[default: {ORDER_SOURCE}; env: SNIPPET_CAST_ORDER]")
    @argument("-q", "--quiet", action=argparse.BooleanOptionalAction,
              default=None,
              help="suppress progress, notes and the cell's own output; errors "
                   "still print, and --export-script still returns its script "
                   "[env: SNIPPET_CAST_QUIET]")
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
        # Captured before resolve_env_defaults fills in the "silent"/
        # manual_audio_dir fallbacks below, so --record can tell an explicit
        # --tts/env var apart from the hardcoded default it's about to
        # silently override.
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
        # Same trick for --pause: asking for a specific frame length is what
        # opts a narration-less cell into a silent render — PAUSE_DEFAULT is
        # > 0, so the resolved value can't tell that apart from a forgotten
        # '#:', which must still report No narration found.
        pause_explicit = (args.pause is not None
                          or (os.environ.get("SNIPPET_CAST_PAUSE") not in
                              (None, str(PAUSE_DEFAULT))))
        # Only fall back to the cache directory when the cell said nothing
        # about where its video should go — an explicit -o/-n/-d (or the
        # matching env var) still wins. Env vars count only when they DIFFER
        # from the default: a project-wide activation env may materialise all
        # of SNIPPET_CAST_* at their defaults, and "SNIPPET_CAST_NAME=out"
        # expresses no preference — treating it as one silently put every
        # cell back to overwriting a single out.mp4.
        output_explicit = (
            any(v is not None for v in (args.output, args.name, args.output_dir))
            or os.environ.get("SNIPPET_CAST_NAME", "out") != "out"
            or os.environ.get("SNIPPET_CAST_OUTPUT_DIR", ".") != ".")
        resolve_env_defaults(
            args, tts="silent", no_trace=False, every=False, subtitles=False,
            typing=False, typing_speed=TYPE_SPEED, pause=PAUSE_DEFAULT, export_script=False,
            manual_audio_dir=MANUAL_AUDIO_DIR_DEFAULT, record=False, no_frame=False,
            quiet=False, responsive=True, order=ORDER_SOURCE,
            name="out", output_dir=".", style=STYLE,
            bg_color=BG_COLOR if BG_COLOR else BG_COLOR_NONE,
            state_bg_color=PANEL_BG, state_fg_color=None,
            highlight_color=HIGHLIGHT_COLOR, font_size=FONT_SIZE,
            screenflow=None)
        # Tri-state, so it can't go through resolve_env_defaults(), whose
        # whole contract is "fill anything still None" — None is a meaningful
        # value here (auto-detect from the frame background).
        if args.light_controls is None:
            raw = os.environ.get("SNIPPET_CAST_LIGHT_CONTROLS")
            # "auto" (and empty) keep the detection, so the variable can be
            # present in an activation env without forcing a choice.
            if raw is not None and raw.strip().lower() not in ("", "auto"):
                args.light_controls = raw.strip().lower() in ("1", "true", "yes", "on")
        try:
            args.style, args.bg_color, args.highlight_color = resolve_style_args(
                args.style, args.bg_color, args.highlight_color)
            args.state_bg_color, args.state_fg_color = resolve_panel_args(
                args.state_bg_color, args.state_fg_color)
            args.screenflow = resolve_screenflow_arg(args.screenflow)
        except ValueError as e:
            print(f"snippet-cast: {e}", file=sys.stderr)
            return
        # Resolved once, AFTER the style/color strings are normalized, so the
        # luminance test sees the same background the frames are rendered on.
        light = _light_controls_for(args.style, args.bg_color,
                                    args.highlight_color, args.light_controls)
        if args.font_size < FONT_SIZE_MIN:
            print(f"snippet-cast: --font-size must be >= {FONT_SIZE_MIN}.",
                  file=sys.stderr)
            return
        if args.tts not in BACKENDS:
            print(f"snippet-cast: --tts: invalid choice {args.tts!r} "
                  f"(choose from {', '.join(BACKENDS)})", file=sys.stderr)
            return

        if args.record:
            if args.quiet:
                print("snippet-cast: --quiet can't be used with --record: "
                      "recording is an interactive session whose prompts are "
                      "that output.", file=sys.stderr)
                return
            if tts_explicit and args.tts != "manual":
                print(f"snippet-cast: --record always uses the manual backend; "
                      f"got --tts {args.tts!r}. Drop --tts (or set it to manual) "
                      "when using --record.", file=sys.stderr)
                return
            args.tts = "manual"
        elif manual_dir_explicit and args.tts != "manual":
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

            out_path = (resolve_output_path(args.output, args.output_dir, args.name)
                        if output_explicit else _cell_output_path(line, cell))

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
                      allow_unnarrated=pause_explicit,
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
