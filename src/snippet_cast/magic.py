"""
Jupyter cell magic for snippet-cast: %%snippet-cast

Importing this module inside a live IPython/Jupyter kernel registers the
magic automatically:

    import snippet_cast.magic

`%load_ext snippet_cast.magic` still works too (and is the only option
outside a live kernel, or to force re-registration after editing this file
under autoreload). `import snippet_cast` alone does *not* pull this module
in — that import is kept IPython-free on purpose.

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
import html
import os
import sys
import tempfile

from IPython import get_ipython
from IPython.core.magic import Magics, cell_magic, magics_class
from IPython.core.magic_arguments import argument, magic_arguments, parse_argstring
from IPython.display import HTML, Image, Video, clear_output, display

from .screencast import (
    BACKENDS,
    TYPE_SPEED,
    build,
    export_script,
    record_narration,
    resolve_env_defaults,
    resolve_output_path,
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
                   "env: SNIPPET_CAST_TTS]")
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
    @argument("--pause", type=float, default=None, metavar="SECONDS",
              help="seconds of silence held on each beat's frame after its "
                   "narration [default: 0; env: SNIPPET_CAST_PAUSE]")
    @argument("--manual-audio-dir", default=None, metavar="DIR",
              help="directory of pre-recorded audio for --tts manual "
                   "[env: SNIPPET_CAST_MANUAL_AUDIO_DIR]")
    @argument("--export-script", action=argparse.BooleanOptionalAction, default=None,
              help="print the ordered narration script instead of rendering "
                   "[env: SNIPPET_CAST_EXPORT_SCRIPT]")
    @argument("--record", action=argparse.BooleanOptionalAction, default=None,
              help="interactively record narration via the system microphone "
                   "(macOS only), then build with --tts manual — requires "
                   "--manual-audio-dir DIR; see SETUP.md "
                   "[env: SNIPPET_CAST_RECORD]")
    @argument("--no-frame", action="store_true", default=None,
              help="with --record, don't pop each beat's rendered frame in "
                   "the system image viewer [env: SNIPPET_CAST_NO_FRAME]")
    @argument("--embed", action="store_true",
              help="embed the video as base64 in the notebook instead of linking the file")
    @cell_magic("snippet-cast")
    def snippet_cast(self, line, cell):
        """Render `cell` (an annotated Python snippet) into a screencast and
        display it inline. See the module docstring for a full example."""
        args = parse_argstring(self.snippet_cast, line)
        resolve_env_defaults(
            args, tts="silent", no_trace=False, every=False, subtitles=False,
            typing=False, typing_speed=TYPE_SPEED, pause=0.0, export_script=False,
            manual_audio_dir=None, record=False, no_frame=False,
            name="out", output_dir=".")
        if args.tts not in BACKENDS:
            print(f"snippet-cast: --tts: invalid choice {args.tts!r} "
                  f"(choose from {', '.join(BACKENDS)})", file=sys.stderr)
            return

        fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="snippet_cast_cell_")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(cell)

            if args.export_script:
                try:
                    for narration_line in export_script(
                            tmp_path, trace=not args.no_trace, every=args.every):
                        print(narration_line)
                except SystemExit as e:
                    print(f"snippet-cast: {e.code}", file=sys.stderr)
                return

            out_path = resolve_output_path(args.output, args.output_dir, args.name)

            if args.record:
                if not args.manual_audio_dir:
                    print("snippet-cast: --record requires --manual-audio-dir DIR.",
                          file=sys.stderr)
                    return
                view = _LiveRecordView()
                try:
                    with contextlib.redirect_stdout(view):
                        committed = record_narration(
                            tmp_path, args.manual_audio_dir, out_path,
                            trace=not args.no_trace, every=args.every,
                            subtitles=args.subtitles, typing=args.typing,
                            typing_speed=args.typing_speed, pause=args.pause,
                            show_frame=not args.no_frame, frame_fn=view)
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
                display(Video(out_path, embed=args.embed))
                return

            try:
                build(tmp_path, out_path, args.tts,
                      trace=not args.no_trace, every=args.every,
                      subtitles=args.subtitles, typing=args.typing,
                      typing_speed=args.typing_speed, pause=args.pause,
                      manual_audio_dir=args.manual_audio_dir)
            except SystemExit as e:
                print(f"snippet-cast: {e.code}", file=sys.stderr)
                return
        finally:
            os.unlink(tmp_path)

        display(Video(out_path, embed=args.embed))


def load_ipython_extension(ipython):
    """Called by `%load_ext snippet_cast.magic`."""
    ipython.register_magics(SnippetCastMagics)


_ip = get_ipython()
if _ip is not None:
    # Auto-register on `import snippet_cast.magic` when already inside a
    # live kernel/shell, so callers don't have to know about %load_ext.
    load_ipython_extension(_ip)
