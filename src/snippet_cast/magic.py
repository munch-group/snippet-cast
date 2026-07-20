"""
Jupyter cell magic for snippet-cast: %%snippet-cast

Load the extension once per kernel session:

    %load_ext snippet_cast.magic

then write an annotated snippet directly in a cell and render + display it
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
`--export-script`, `--tts manual --manual-audio-dir DIR`), with one deliberate
difference: `--tts` defaults to `silent` here (not `say`), since it's the only
backend guaranteed to work without any setup, in any notebook environment.
Piper/ElevenLabs config (the `PIPER_*`/`ELEVENLABS_*` env vars) works exactly
as on the command line — set them with `os.environ[...] = ...` in an earlier
cell.
"""
import os
import sys
import tempfile

from IPython.core.magic import Magics, cell_magic, magics_class
from IPython.core.magic_arguments import argument, magic_arguments, parse_argstring
from IPython.display import Video, display

from .screencast import BACKENDS, TYPE_SPEED, build, export_script


@magics_class
class SnippetCastMagics(Magics):
    """Registers %%snippet-cast. Load with `%load_ext snippet_cast.magic`."""

    @magic_arguments()
    @argument("-o", "--output", default="out.mp4", metavar="PATH",
              help="output MP4 path [default: out.mp4]")
    @argument("--tts", choices=list(BACKENDS), default="silent",
              help="TTS backend [default: silent — always works, no setup; "
                   "see SETUP.md for piper/elevenlabs]")
    @argument("--no-trace", action="store_true",
              help="don't execute the snippet; skip the state panel")
    @argument("--every", action="store_true",
              help="one beat per execution of a line (animates loops)")
    @argument("--subtitles", action="store_true",
              help="burn the narration text as a caption")
    @argument("--typing", action="store_true",
              help="type newly revealed lines character-by-character")
    @argument("--typing-speed", type=float, default=TYPE_SPEED, metavar="SECONDS",
              help=f"seconds to reveal each newly typed character [default: {TYPE_SPEED}]")
    @argument("--pause", type=float, default=0.0, metavar="SECONDS",
              help="seconds of silence held on each beat's frame after its narration [default: 0]")
    @argument("--manual-audio-dir", metavar="DIR",
              help="directory of pre-recorded audio for --tts manual")
    @argument("--export-script", action="store_true",
              help="print the ordered narration script instead of rendering")
    @argument("--embed", action="store_true",
              help="embed the video as base64 in the notebook instead of linking the file")
    @cell_magic("snippet-cast")
    def snippet_cast(self, line, cell):
        """Render `cell` (an annotated Python snippet) into a screencast and
        display it inline. See the module docstring for a full example."""
        args = parse_argstring(self.snippet_cast, line)

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

            try:
                build(tmp_path, args.output, args.tts,
                      trace=not args.no_trace, every=args.every,
                      subtitles=args.subtitles, typing=args.typing,
                      typing_speed=args.typing_speed, pause=args.pause,
                      manual_audio_dir=args.manual_audio_dir)
            except SystemExit as e:
                print(f"snippet-cast: {e.code}", file=sys.stderr)
                return
        finally:
            os.unlink(tmp_path)

        display(Video(args.output, embed=args.embed))


def load_ipython_extension(ipython):
    """Called by `%load_ext snippet_cast.magic`."""
    ipython.register_magics(SnippetCastMagics)
