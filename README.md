# snippet-cast

Turn an annotated Python snippet into a narrated screencast video.

Narration is written as trailing `#:` comments on the snippet's own lines, so
the input stays valid, runnable Python:

```python
def fib(n):             #: We define fib, taking one argument, n.
    a, b = 0, 1          #: Start from the first two Fibonacci numbers.
    for _ in range(n):   #: Loop n times.
        a, b = b, a + b  #: Advance the pair; b becomes the running sum.
    return a             #: Return a — the nth Fibonacci number.
```

Each `#:` line becomes one "beat": the code is revealed up to that line, the
line is highlighted, and its narration is spoken. `snippet-cast` renders
syntax-highlighted code frames with a progressive reveal, a Python-Tutor-style
live variable panel, optional burned-in captions and a typing-in animation,
synthesises speech per line, and stitches everything into an MP4 with ffmpeg.

## Installation

Requires **Python 3.10+** and **ffmpeg** (with `ffprobe`) on `PATH`.

```bash
pip install snippet-cast
# or
pixi add snippet-cast
# or
conda install -c munch-group snippet-cast
```

## Usage

```bash
snippet-cast snippet.py -o out.mp4 --tts silent --subtitles   # fast, voiceless proof
snippet-cast snippet.py -o out.mp4 --typing --subtitles       # type each new line in
snippet-cast loop.py    -o out.mp4 --every --subtitles        # animate each loop iteration
```

Or from Python:

```python
from snippet_cast import build

build("snippet.py", "out.mp4", tts="silent", subtitles=True)
```

Or in a Jupyter notebook — write the snippet directly in a cell instead of a
separate `.py` file:

```
pip install snippet-cast[jupyter]
```

```
%load_ext snippet_cast.magic
```

```
%%snippet-cast -o out.mp4 --tts silent --subtitles
def fib(n):             #: We define fib, taking one argument, n.
    a, b = 0, 1          #: Start from the first two Fibonacci numbers.
    for _ in range(n):   #: Loop n times.
        a, b = b, a + b  #: Advance the pair; b becomes the running sum.
    return a             #: Return a — the nth Fibonacci number.
result = fib(7)          #: Call fib with seven; result becomes {result}.
```

The cell magic takes the same flags as the CLI and displays the rendered MP4
inline.

See [SETUP.md](SETUP.md) for configuring the Piper (local) and ElevenLabs
(cloud) text-to-speech backends, and `snippet-cast --help` for all options.

## Development

This repository is built from the munch-group library template.

### Initial set up

```bash
pixi run init
```

### Get updates to upstream fork

Add upstream if not already added

```bash
git remote add upstream https://github.com/munch-group/snippet-cast.git
```

Fetch upstream changes

```bash
git fetch upstream
```

Either rebase your changes on top of upstream (cleaner history)

```bash
git rebase upstream/main
```

Or, merge upstream into your fork (preserves history)

```bash
git merge upstream/main
```

If you want to see what's changed upstream before applying:

```bash
git log HEAD..upstream/main
```

See the actual diff

```bash
git diff HEAD...upstream/main
```

Then push your updated fork:

```bash
git push origin main
```

If you rebased and need to force push
    
```bash
git push origin main --force-with-lease
```
