# Project Configuration for Claude

This file contains preferences and guidelines for working in this project.

## What this repository is

**snippet-cast** is a distributable Python library and CLI (`snippet-cast`) that
turns an **annotated Python snippet** into a **narrated screencast video**.
Narration is written as trailing `#:` comments on the snippet's own lines, so
the input stays valid, runnable Python. The tool renders syntax-highlighted
code frames with a progressive reveal, a Python-Tutor-style live variable
panel, optional burned-in captions and a typing-in animation, synthesises
speech per line, and stitches everything into an MP4 with ffmpeg. There is no
framework and no web server — it is a plain library + CLI, packaged with the
repo's usual pixi/setuptools/conda/PyPI scaffolding.

### Commands

Requires **Python 3.10+** (uses `int | None` annotations at runtime) and
**ffmpeg + ffprobe on PATH** (declared as a `[tool.pixi.dependencies]` conda
package). Python deps `pillow`/`pygments` are declared in `[project.dependencies]`;
`piper-tts` is an optional extra (`pip install snippet-cast[piper]`) since it
isn't published on conda-forge — kept out of the hard deps so the conda-forge
build's auto-mirrored `run:` requirements don't break.

```bash
# environment (pixi is this project's env manager)
pixi install                     # installs ffmpeg + pillow + pygments + snippet-cast (editable)

# run — proofing loop (no audio backend needed, fast)
pixi run snippet-cast test/data/fib.py  -o out.mp4 --tts silent --subtitles

# run — feature combinations
pixi run snippet-cast test/data/fib.py  -o out.mp4 --typing --subtitles      # first-exec + typing
pixi run snippet-cast test/data/loop.py -o out.mp4 --every  --subtitles      # per-iteration walkthrough
pixi run snippet-cast test/data/fib.py  -o out.mp4 --no-trace                # code + highlight only
pixi run snippet-cast test/data/twopass.py -o out.mp4 --tts silent --subtitles   # two-pass ('/' in narration)
pixi run snippet-cast test/data/footnote.py -o out.mp4 --tts silent --subtitles  # footnote bodies ('#: N)')
pixi run snippet-cast test/data/twopass.py --export-script                      # narration script to record
pixi run snippet-cast test/data/plain.py -o out.mp4 --pause 2                   # NO '#:' at all: 2s silent frame per line

# theme / background (per run — no source edit needed)
pixi run snippet-cast --style list                                              # every valid --style name
pixi run snippet-cast test/data/fib.py -o out.mp4 --tts silent --style github-dark --bg-color none
pixi run snippet-cast test/data/fib.py -o out.mp4 --tts silent --style light-modern --bg-color none
pixi run snippet-cast test/data/fib.py -o out.mp4 --tts silent --style dark-modern --highlight-color '#2a2d2e'
pixi run snippet-cast test/data/fib.py -o out.mp4 --tts silent --font-size 40           # bigger text
pixi run snippet-cast test/data/fib.py -o out.mp4 --tts silent --screenflow             # 1920x1080, content centred
pixi run snippet-cast test/data/fib.py -o out.mp4 --tts silent --screenflow 1280x720 --font-size 40
pixi run snippet-cast test/data/fib.py -o out.mp4 --tts silent --style src/snippet_cast/themes/numpy.theme --bg-color none
SNIPPET_CAST_STYLE=nord pixi run snippet-cast test/data/fib.py -o out.mp4 --tts silent

# real voices (see SETUP.md)
pixi run snippet-cast test/data/fib.py  -o out.mp4 --tts piper
pixi run snippet-cast test/data/fib.py  -o out.mp4 --tts elevenlabs

# programmatic use
python -c "from snippet_cast import build; build('test/data/fib.py', 'out.mp4', tts='silent')"

# smoke-verify an output
ffprobe -v error -show_entries format=duration \
        -show_entries stream=codec_type,width,height -of default=nw=1 out.mp4
```

Automated tests live in `test/test_screencast.py` and cover parsing, tracing,
and beat-construction logic without needing ffmpeg; a full-render smoke test
runs only when ffmpeg and the configured `FONT_NAME` are both resolvable on
the host (`pytest -q`). See [Verifying changes](#verifying-changes) for the
manual recipe used to sanity-check rendered video output.

### Repository layout

| Path | Purpose |
|---|---|
| `src/snippet_cast/screencast.py` | The entire tool (~700 lines): parse → trace → beats → render → TTS → assemble. |
| `src/snippet_cast/__init__.py` | Public API: exports `build` (programmatic), `export_script`, `record_narration`, and `main` (CLI entry point). |
| `src/snippet_cast/magic.py` | Jupyter `%%snippet-cast` cell magic (`pip install snippet-cast[jupyter]`; both `import snippet_cast` and `import snippet_cast.magic` auto-register it inside a live kernel, or use `%load_ext snippet_cast.magic`). `__init__.py` only imports it conditionally — behind the same `get_ipython()`-gated check `magic.py` itself uses — so `import snippet_cast` outside a live kernel, or without IPython installed, still never requires IPython. It's a thin wrapper: writes the cell to a temp `.py` file, calls `build()`/`export_script()`/`record_narration()`, displays the result with `IPython.display.Video`. `--record`'s `input()` prompts work the same in a notebook cell as a terminal — no special-casing needed. |
| `SETUP.md` | How to configure every TTS backend (`say`, `manual`/`--record`, Piper, ElevenLabs). |
| `test/data/fib.py`, `test/data/loop.py`, `test/data/twopass.py`, `test/data/footnote.py`, `test/data/plain.py` | Sample snippets used by tests and for manual verification (`twopass.py` exercises `/`-split, two-pass narration; `footnote.py` exercises `#: N)` footnote bodies; `plain.py` carries NO narration at all, for the `--pause`-only silent render). |
| `test/test_screencast.py` | Automated tests: parsing, tracing, beat construction, and a full-render smoke test. |
| `*.mp4` | Generated outputs (not source; safe to delete / gitignore). |

### Architecture

Data flows through five stages; each has a clear boundary, so most edits touch
only one. Names below are the actual functions/classes in
`src/snippet_cast/screencast.py`.

```
source.py
  └─ parse()            -> code_lines[], markers[Marker]      # strip #: narration
  └─ trace_run()        -> steps[Step]                        # run under sys.settrace
  └─ build_beats()      -> beats[Beat]                        # mode-specific assembly
  └─ plan_canvas()      -> Canvas   (+ compose(), typing_frames())  # fixed-size frames
  └─ synth_*() + make_clip() + concat()  -> out.mp4           # TTS + ffmpeg
```

Key data structures:

- **`Marker`** `(line_no, text, has_code)` — a parsed `#:` annotation. `has_code`
  is False for comment-only (intro/outro) lines.
- **`Step`** `(line_no, disp, text, frame_id)` — one *execution* of a line, in
  completion order. `disp` = `{name: repr}` for the panel; `text` =
  `{name: str(value)}` for `{var}` interpolation; `frame_id` = `id(frame)`.
- **`Beat`** `(revealed, highlight, narration, state)` — one render-ready unit
  = one frame + one narration clip. `narration` is already interpolated;
  `revealed` is a `frozenset[int]` of 1-based source lines visible at this
  beat (see `_visible_code()`); `revealed=None` means "show all code".
- **`Canvas`** — fixed dimensions + per-beat wrapped caption lines, computed once
  so every frame shares one resolution.

#### Two modes (set by `--every`)

- **first-exec (default):** one beat per marked line, using that line's *first*
  execution for state/interpolation. Code is **progressively revealed** up to the
  highlighted line. Typing animation applies here.
- **every-exec (`--every`):** one beat per *execution*, in trace order, so loops
  animate iteration-by-iteration. The **full snippet is shown from the start** and
  the highlight follows execution (progressive reveal is intentionally disabled
  here — a bottom driver call would otherwise make the reveal jump around).

#### Narration separators: `//` between passes, `/` between visits

Two levels, and the order they are applied in matters:

```
first-pass  //  second-pass entry  /  second-pass completion
```

- `TWO_PASS_SEP` is **`//`** — `split_narration()` splits on the first one.
- `ENTRY_SEP` is **`/`** — `split_entry()` splits ONE pass's text into
  `(entry, completion)`, the two visits `--order exec` makes to a line.

Allowed shapes: `narration`, `entry / completion`, `pass1 // pass2`, and
`pass1 // entry / completion`. Every mode narrates the COMPLETION half;
only `--order exec` has an entry visit to show the other one on.

`split_entry()` runs AFTER `split_narration()` and after `order_markers()`
has stripped any `N) ` prefix, so `2) a // b / c` numbers the pass, not one
half of it.

**This was a breaking change** — the pass separator used to be a single `/`,
so an older file's `write / explain` now parses as entry/completion and
quietly loses its writing pass. There is no way to detect that from the text
alone, so `_warn_unused_entry_narration()` names every line carrying an entry
narration the chosen order cannot show, and points at `//`. `test/data/*.py`,
the test fixtures and `tmp.py` were migrated; note `footnote.py`'s separators
sit on wrapped `#` continuation lines, which a `#:`-anchored migration regex
does not see.

Two consequences inside `_exec_beats()`:
- A `"call"` visit counts as an arrival and takes the ENTRY text — it is the
  moment Python steps into the function. A `def` line is arrived at twice
  (defining it, then entering it), so its entry words play once, at the call;
  the definition keeps only its completion words.
- The enter/done collapse is **skipped when the line gives its entry its own
  words**: the two frames match but the narration does not, so collapsing
  would silently drop it.

`_footnote_comment()` merges per pass AND, within the walkthrough, per half,
so an entry narration in the reference and a completion narration in the body
each land where they belong.

Hazard unchanged in kind but not in likelihood: a literal `/` in prose
("and/or", "input/output") now splits entry from completion. It used to split
the passes.

#### Two-pass narration (orthogonal to the above, first-exec only)

`split_narration(text)` splits a `#:` narration on the first `/` into
`(part1, part2)`. If **any** marker's raw text contains `/`, `build()` takes an
early branch (`build()`'s `two_pass` flag) that calls `_two_pass_beats()` —
which calls the *unmodified* `build_beats()` **twice**: once with
`steps=[]` (part1 text; forces `state={}` everywhere, since `first.get(...)`
always misses) for **pass 1** ("writing" — always typed, via
`make_pass1_code_clip()`/`probe_duration()`, narration and typing start
together, opening on a blank canvas (`typing_frames()`'s `start_blank` path)),
and once with the real `steps` (part2 text) for **pass 2** ("walkthrough" —
same per-beat highlight/state/narration as single-pass first-exec mode, but
`_render_two_pass()` deliberately ignores each beat's `revealed` here and
always composes the full code pass 1 already typed (`_visible_code(code_lines,
final_revealed)`, `final_revealed = beats1[-1].revealed`) — only the
highlight and state panel move per beat; the code is never hidden and
re-revealed). `_render_two_pass()` renders all of pass 1 then all of pass 2,
concatenated into one video. A file with no `/` anywhere never takes this
branch — the original single-pass loop in `build()` is untouched, so behavior
for existing snippets doesn't change.

Pass 1's typed reveal is paced by `typing_speed`, same as legacy `--typing`
(capped at `TYPE_MAXFRAMES`) — `make_pass1_code_clip()` no longer lets a real
narration's `probe_duration()` silently override that pace outright (a prior
bug: `--typing-speed` had zero effect whenever pass 1 had non-empty
narration, since frame count was `ceil(duration * FPS)` with characters
spread evenly across ALL of it). `duration` is now only a FLOOR: if typing
finishes before the narration does, the fully-typed frame is padded with
duplicate frame files for the remainder (never truncating narration, per
invariant 10); if `typing_speed` would need MORE time than the narration
provides, the reveal is — same as before this fix — cut short by
`make_typing_clip`'s `-shortest` at the real audio length. `--pause` applies
**within both passes AND at the seam between them** (a duplicated prior bug:
only pass 2's loop had pause logic at all) via the same "no trailing pause"
guard (`k < len(beatsN) - 1`) in each pass independently, plus one explicit
transition clip appended after pass 1's loop (held on the last pass-1 frame,
i.e. the fully-typed code, so the walkthrough doesn't start talking the
instant the writing pass stops). That in-loop guard is what keeps the seam
gap the only clip in that seam — and what keeps a pause from ever landing
after the video's final beat.

#### Execution order (`--order exec`, first-exec only)

`--order {source,exec}` (`SNIPPET_CAST_ORDER`, `build(order=...)`) is the
third answer to "what order do the beats play in", alongside source order and
`N)` numbering. `ORDER_EXEC` hands beat construction to `_exec_beats()`
instead of `build_beats()`'s usual loop.

Each marked line contributes one beat per KIND of visit, in time order:
`"enter"` (about to run — its pre-state), `"call"` (a function being entered,
on its `def` line, showing the parameters as just bound) and `"done"` (it has
finished — its post-state). So `result = fib(7)` is highlighted on entry with
no `result` yet, the whole body plays, and it is highlighted again at the end
showing `result = 13`. `fib.py` goes from 7 beats to 12.

**Only `"done"` carries the narration** — a line's `#:` describes what it DID,
which is not true yet on the way in. Entry/call beats are silent, so
`_render_from_beats()` holds them for `PART2_EMPTY_HOLD` rather than
synthesizing `""`: an empty synth is a near-zero-length clip, and under
`--tts manual` it would consume a numbered recording and desync every later
beat from `--export-script`'s numbering (the same rule `_narration_sequence()`
already applies). An `"enter"` whose own `"done"` follows immediately with an
identical state is dropped as a pure duplicate — that is every instantaneous
line, such as a module-level `def`.

**Every beat carries `revealed=None`** — the whole snippet is on screen from
the first frame and only the highlight moves, exactly as in `--every` mode and
for the same reason: playback jumps around (call site, then the body, then
back to the call site), so revealing lines in that order would make code
appear in a scattered, hole-punched sequence instead of reading as a program.
It also removes any need to special-case never-executed lines, which are on
screen like every other. (Two-pass mode already did this for pass 2 —
`_render_two_pass()` ignores `revealed` there because pass 1 has already
typed the code in.) Typing is skipped as a consequence, since
`_render_from_beats()` only types when `revealed is not None`.

Ordering rules that are easy to get wrong:
- A marker whose line NEVER runs contributes no beat, so its narration is
  dropped — but its code is on screen throughout like everything else.
- A comment-only marker is slotted after the `"done"` of the nearest
  preceding code line **that actually got a beat** — not merely the nearest
  preceding marked line, or a comment under a never-called function would be
  dropped along with it. Nothing preceding it means first, which is where an
  intro line naturally sits.
- Dropped narration is **reported**, listing the lines. Losing half a
  snippet's commentary reads as a bug in the tool rather than as an untaken
  branch or — far more often — a snippet that raised part-way and never
  reached the rest. `trace_run()` does report the exception, but a few lines
  earlier and easy to miss in a notebook.

A line unwound by an exception still gets a `"done"` beat: the `return` event
fires as the frame unwinds, so `close()` records its state at the moment it
blew up. That is informative, but note it means such a line IS narrated even
though it never completed normally.

`trace_run(entries=True)` is what records the `"enter"` steps, and it is
**off by default**: it doubles both the `_snapshot()` calls and the length of
`steps`, and nothing else needs them. `Step.kind` replaced the old
`call_entry` bool; `build_beats()` filters to `kind == "done"` for
`env_before()` and `--every`, exactly as it filtered out `call_entry` before.

Refused combinations, all `sys.exit`: `--no-trace` (there is no order without
running), `--every` (already one beat per execution), and `N)` prefixes in the
affected pass (two different answers to the same question). In two-pass mode
it applies to the WALKTHROUGH only — pass 1 is someone writing the code, which
happens top-to-bottom.

#### Custom narration order (first-exec only, orthogonal to two-pass)

Any marker's (post-`split_narration()`) text may carry a leading `N)` —
`_parse_order()` strips it, returning `(order, text)` or `(None, text)` if
absent. `order_markers(markers, texts)` pairs markers with their per-pass
texts, requires **all-or-none** numbering within that pass (`sys.exit` on a
mix), and — only when every text is numbered — sorts the markers by that
number (stable sort; unnumbered passes are left in source order, today's
default). `build()`/`export_script()` call it once for single-pass mode
(texts = each marker's whole `.text`); `_two_pass_beats()` calls it twice,
once per split-off pass, so pass 1 and pass 2 can use independent orders.

**A walkthrough pass with no numbering of its own INHERITS the writing
pass's order** rather than falling back to source order. `#: 2) Write it /
Explain it` is how people naturally write this — the number goes once, on
the pass that has one — and ordering only pass 1 made the video jump around
while writing and then march top-to-bottom while explaining. Numbering pass
2 explicitly (`/ 4) text`) still overrides it, and a file numbering neither
pass is untouched. The inheritance is done at the ORDER level in
`_two_pass_beats()` (rank pass 2's markers by their position in pass 1's
result), NOT by rewriting pass 2's text: its texts stay unnumbered, so
`order_markers()` never sees a mix and its all-or-none check is unaffected.
Re-attaching the label to pass 2's *text* was tried once and was a real bug
— see the footnote section's warning.

Reordering reveals genuinely out of order — it does NOT force code to appear
as a growing top-down prefix. `_reveal_groups(code_lines, markers)` partitions
[1, last marker's line] into one contiguous, non-overlapping group per marker
(a marker's group = itself plus any unmarked lines back to the previous
marker); `build_beats()` accumulates a running `frozenset` union of the groups
visited so far (in playback order) into each beat's `revealed`, instead of a
simple `m.line_no` high-water mark. Because groups are disjoint and every
marker is visited exactly once, EVERY beat always has a non-empty new group
to reveal, regardless of play order — jumping ahead to a later line no longer
drags earlier, not-yet-visited lines along with it. `_visible_code(code_lines,
revealed)` turns a `revealed` set into renderable text: any line NOT in the
set renders as an empty string at its own row, so revealed lines always stay
at their fixed position no matter what order they arrived in. `typing_frames()`
/`make_pass1_code_clip()` take `(code_lines, revealed_before, new_group)`
instead of a `(base_lines, new_lines)` prefix pair, typing `new_group`'s
characters directly into its own row range while everything in
`revealed_before` stays fully shown and everything else stays blank. Rejected
together with `--every` (there, beat order already follows the execution
trace, not marker order, so reordering markers would have no effect on code
beats and would silently desync the every-mode comment-slotting logic, which
assumes `comment_marks` stays in ascending line order).

#### Footnote narration (first-exec only, layered on the `N)` order prefix)

A long narration can be moved out of the code's right margin by using the
same `N)` label **twice**: once on the line it narrates, once on a
comment-only block elsewhere holding the text (which may wrap over plain `#`
lines). `resolve_footnotes(source)` — a **source -> source transform**, called
at the very top of `_build_all_beats()` before `parse()`/`trace_run()`/
`loop_body_ranges()` — unwraps the block's text into one line, **appends** it
to the other occurrence's own text, and deletes the block.

Doing it as a source rewrite is the whole trick: everything downstream
re-derives its line numbers from the rewritten text, so removing lines needs
no remapping of `Marker.line_no`, `Step.line_no` (which comes from tracing
that same string) or `loop_body_ranges()`'s AST — and nothing else in the
pipeline knows the feature exists. Doing it at the marker level instead would
require renumbering all three in lockstep.

`_scan_comments()`/`_marker_text()` are factored out of `parse()` and shared,
so the transform finds comments via `tokenize` too — a `#:` inside a string
literal is not a label (critical invariant 5).

**Pairing is by COUNT, not by shape.** A label used once is the ordinary
`N)` order prefix and is left completely alone (silently); a label used twice
is a footnote; three or more is an error. This is what lets old-format
single-occurrence prefixes and new-format footnotes mix in one file, and it
means nothing written before footnotes existed can change meaning — every
label in such a file occurs once. Of the two occurrences, whichever is on a
line of its own supplies the body (if both are, the second does; if neither
is, they can't be merged without deleting code, so they're left alone with a
note).

`_footnote_comment()` merges the two texts **per pass** (`split_narration()`
on each, concatenate part1s and part2s) and re-emits `N) part1 / part2`. The
label is deliberately NOT re-attached to the walkthrough side, so the result
is textually identical to having typed the body inline after the `N)` — and
`N)` therefore keeps its normal per-pass meaning. **An earlier version did
re-attach it to both passes** (to stop the passes ordering differently); that
silently forced the walkthrough pass to be numbered, so a single footnote in
a file whose walkthrough pass was otherwise unnumbered tripped
`order_markers()`'s all-or-none check. Don't reintroduce it — number the
walkthrough side inside the body (`/ 2) text`) if it needs ordering.

**The mirror-image bug, also fixed:** the re-emit must KEEP the separator
whenever either side carried one, even when pass 1 comes out empty. The
original `if part1:` test dropped it, so a reference reading `#: 3)` plus a
body of `#: 3) / Start from...` (equally, `#: 3) /` plus a plain body) was
rewritten to `3) Start from...` — which re-parses as an unnumbered pass 1 and
a pass 2 numbered 3, i.e. the label jumping passes. In exactly the file the
paragraph above describes (every writing line numbered, every walkthrough
line not) that tripped the same all-or-none check, so a footnote written like
all its neighbours failed with the mix-of-numbering error. The invariant to
hold onto is the one in the paragraph above: a footnote must produce exactly
the beats you would get by typing the body inline after the `N)` — pinned by
`test_footnote_empty_pass_one_matches_the_inline_spelling`.

Inheriting the order prefix also inherits `--every` rejection. After removing
a block the transform strips trailing blank lines it left behind —
`plan_canvas()` sizes every frame from the full code and `_render_code()`
keeps blank rows (invariant 12), so they'd add dead height to the whole video.

#### Unnarrated snippets: `--pause` as the frame length (orthogonal to everything above)

A snippet with **no `#:` comments at all** normally exits with "No narration
found". Passing `--pause SECONDS` explicitly opts into rendering it anyway, as
a silent, evenly paced video — one progressively revealed frame per code line,
each held for exactly `pause` seconds — to narrate afterwards in a video
editor (ScreenFlow and friends). `build(allow_unnarrated=True)` is the
programmatic switch; `_build_all_beats()` returns whether it fired, and
`_render_from_beats(unnarrated=True)` is what honors it.

The trigger is **`--pause` being given explicitly, not its resolved value**:
`PAUSE_DEFAULT` is 0.8, so a resolved-value test could not tell "hold each
frame this long" apart from "I never mentioned `--pause`" — and a forgotten
`#:` must keep reporting the error rather than silently rendering. `main()`
and `magic.py` each capture `pause_explicit` (`args.pause is not None or
os.environ.get("SNIPPET_CAST_PAUSE") is not None`) BEFORE
`resolve_env_defaults()` fills the fallback in, exactly like the neighbouring
`tts_explicit`/`manual_dir_explicit`. `build()` then ANDs it with `pause > 0`
before passing it down, so `--pause 0` (which would mean zero-length clips,
which ffmpeg's `concat` rejects) is refused by the same message *before*
`trace_run()` executes the snippet, not after.

`_auto_markers(code_lines)` builds the stand-in markers: one empty-text
`Marker` per code line. Comment-only lines deliberately get **no marker of
their own** — `_reveal_groups()` already reveals an unmarked line together
with the next marked one, so a comment appears with the code it describes
instead of costing a beat that would blank the state panel (a comment line has
no trace `Step`). The **last non-blank line always gets one** regardless,
because `_reveal_groups()` never assigns lines after the final marker to any
group, so a trailing comment block would otherwise stay invisible for the
whole video; when that last line is a comment its marker is `has_code=False`,
i.e. an ordinary outro beat.

Rendering: in the single-pass loop each beat is ONE `make_pause_clip(hold,
pause)` and **no separate trailing gap clip** — `pause` is the beat's whole
length here, so appending the usual gap on top would make every frame
`2*pause`. `synth` is never called, so no TTS backend is needed whatever
`--tts` says. Two-pass mode can't be reached (it needs a `/` in a marker, and
there are no markers), so only the single-pass path handles it. `--typing`,
`--every` and `--no-trace` all compose normally; `--subtitles` prints a
no-effect note. `--export-script` and `--record` never opt in — they exist to
produce or record narration, so a file with none stays an error there.

#### Inline pauses within a narration line (orthogonal to everything above)

A run of 2+ consecutive periods inside a `#:` narration (after `split_narration`/
`_parse_order` have already done their own splitting/stripping — this operates
on final beat narration text, at synth time, not at marker-parsing time) is an
inline pause, not spoken: `PAUSE_MARKER_RE` (`r"(\.{2,})"`, capturing group —
`re.split` silently drops the delimiter without one, which was a real bug
caught by a test expecting both sides of the split) matches the run. A single
period is ordinary end-of-sentence punctuation and never matches (`{2,}`).
How the run is honored — and, for `say` only, a second markup transform for
ALL-CAPS emphasis — is decided per-backend by a three-way `pause_mode`:

- `"split"` (every backend except the two below) — `_synth_with_pauses()`
  splits the text on the run, synthesizes each non-empty side separately, and
  generates `PAUSE_PER_PERIOD` seconds of silence per period in the run
  (`_make_silence()`, an `anullsrc` clip) in its place, then stitches
  everything back into one audio file with `_concat_audio_pieces()` (ffmpeg's
  `concat` *filter*, not the `-c copy` demuxer `concat()` uses for whole clips
  — the filter decodes each input first, so pieces from different backends
  never need matching containers/sample rates going in).
- `"say"` — macOS `say` has its *own* native inline markup, so instead of
  splitting into separate synth calls, `_say_markup()` rewrites the text in
  place and `say` gets ONE call with better prosody across the pause/emphasis
  than two stitched fragments would have:
  - `_say_pause_markup()` rewrites each run to `[[slnc N]]`, N =
    `SAY_PAUSE_MS_PER_PERIOD` (200) milliseconds *per period* — tuned
    independently of (and currently double) `PAUSE_PER_PERIOD`, since `say`'s
    own `[[slnc]]` reads differently than a spliced-in silence clip.
  - `_say_emphasis_markup()` separately flanks each run of 2+ consecutive
    ALL-CAPS words (`SAY_EMPHASIS_RE`) with `say`'s `[[emph +]] ... [[emph
    -]]`, e.g. "Please NEVER DO THAT AGAIN" -> "Please [[emph +]] NEVER DO
    THAT AGAIN [[emph -]]". A simple heuristic, no acronym detection — a
    narration mentioning "the URL" gets it flanked too. The lookaround
    (`(?<![A-Za-z])...(?![a-z])`) excludes a mixed-case word entirely (e.g.
    "IDentifier" is left untouched, never sliced into "ID" + "entifier").
  - Both transforms operate on disjoint character classes (periods vs.
    uppercase letters) so `_say_markup()` can apply them in either order.
- `"none"` (the manual backend only) — call `synth` once on the text
  unmodified. Splitting (or rewriting) there would desync `--tts manual`'s
  file numbering — see below.

A narration with no `..` run (and, for `say`, no ALL-CAPS run either) takes a
fast path straight back to one plain, unmodified `synth()` call in every mode
— exactly as if this feature didn't exist.

`_cached_synth()` (the single choke point for every `synth()` call, both
passes and both two-pass and single-pass mode) takes this `pause_mode`
string: `_render_from_beats()` computes it once (`"none"` if
`tts=="manual"`, `"say"` if `tts=="say"`, else `"split"`) and threads it
through `_render_two_pass()`'s three call sites and its own single-pass loop.
The manual backend must always get exactly ONE `synth()` call per beat,
completely unmodified — splitting OR rewriting there would consume more than
one numbered recording per beat (or desync playback content from what a
human actually recorded) and silently desync `--tts manual`'s file order
from `export_script()`'s numbering (the same class of bug the manual-backend/
`--record` numbering invariants elsewhere in this file already guard
against). A human recording narration for `--tts manual`/`--record` just
reads the dots (and shouts the caps) as natural cues — nothing needs
splicing or rewriting.

### Critical invariants — do not break these

These are non-obvious and fail *silently* or only under specific flag
combinations:

1. **All frames must share one resolution.** Final assembly uses ffmpeg
   `concat -c copy`, which requires identical stream params. `plan_canvas()`
   fixes W/H once (even numbers, for libx264). Any per-frame content change must
   fit the existing canvas, not resize it.
2. **All audio is normalised to 44.1 kHz stereo AAC** (`AUDIO_AR`/`AUDIO_AC` in
   `make_clip` and `make_typing_clip`). This is what lets silent typing clips
   concat with real-backend clips (mp3/wav/aiff of varying rates). Removing the
   `-ar/-ac` flags reintroduces a concat-copy mismatch that only surfaces when
   `--typing` meets a non-silent backend.
3. **Trace post-state is captured on the *next* same-frame line event** (or the
   frame's return), not on the line itself — see `trace_run`. That deferral is
   why "state after line L runs" is correct, including nested-call side effects.

   **The one exception is a `def` line**, which gets a second, synthesized
   `Step(call_entry=True)` from the `call` event, holding the parameters as
   just bound (defaults included). Without it a `def` line's only step is the
   module-level one for executing the def STATEMENT — whose post-state
   contains no parameters at all — so highlighting `def fib(n):` showed an
   empty panel and `n` only appeared once the first body line was
   highlighted. `build_beats()`'s first-exec `first` map prefers the
   call-entry step over the statement one (first call wins, so recursion
   shows the outermost frame).

   These steps are consumed ONLY there. `build_beats()` filters them into
   `line_steps` for everything else, because their locals belong to the
   CALLEE's frame: `env_before()` would report them as the caller's scope,
   and `--every` would gain a beat per call. Frames with no `def` header of
   their own are skipped by a `co_name.startswith("<")` test — `<module>`,
   `<listcomp>`, `<genexpr>`, `<dictcomp>`, `<lambda>`. Note `co_firstlineno`
   points at the first DECORATOR for a decorated function, so the parameters
   would attach there rather than to the `def` line.
4. **Loop-header exit beat suppression** (`--every`): a marked `for`/`while` line
   fires one extra time when the loop exhausts. `build_beats` drops it using
   `loop_body_ranges()` (AST) + `frame_id` — the exit check's next same-frame step
   lands outside the loop body. Don't remove this or loops gain a phantom beat.
5. **Parsing uses `tokenize`, not regex**, so a `#` inside a string literal is
   never mistaken for a marker. Keep it that way.
6. **`_render_code` guards empty content** (`code = " "`); PIL cannot encode a
   zero-size image (the intro comment-only beat reveals no code yet).
7. **`--every`/tracing executes the snippet.** `trace_run` runs arbitrary user
   code. This is intended (it's the user's own teaching code) but keep the
   `--no-trace` escape hatch, and never execute untrusted input silently.
8. **Interpolation uses `str(value)` snapshotted at capture time** (not `repr`,
   not a live reference) so `{i}` → `0` not `'0'`, and mutation/aliasing can't
   corrupt earlier beats. `{{`/`}}` escape; unknown `{x}` is left literal.
9. **Two-pass mode is auto-detected, never forced.** `build()`/`export_script()`
   check `any(TWO_PASS_SEP in m.text for m in markers)` — a file with no `/`
   anywhere must render exactly as it did before this feature existed. Don't
   thread two-pass-only conditionals into the legacy single-pass loop; keep
   the two code paths separate (see `_render_two_pass()` vs. the loop at the
   end of `build()`).
10. **A pass-1 "writing" clip lasts `max(typed reveal, narration)` — neither
    stream is ever cut.** `make_pass1_code_clip()` sizes frame count from
    `ceil(duration * FPS)` (rounding up) so the video is never shorter than
    the audio; `make_typing_clip()` adds `apad` to the real-audio input so
    `-shortest` lands on the VIDEO rather than the audio, and the frames are
    never dropped either. Both halves are load-bearing and were bugs in turn:
    without the frame floor a long narration got truncated; without `apad` a
    line whose typing needed longer than its narration stopped mid-word and
    the next clip's fully-typed frame made the rest look typed in an instant.
    Only the *silent* (empty part1) sub-case is capped by `TYPE_MAXFRAMES`;
    the narrated sub-case is deliberately uncapped.
11. **`Beat.revealed` in first-exec mode is a running union of `_reveal_groups()`
    groups, not a `m.line_no` cutoff** (`build_beats()`'s `not every` branch).
    This is what lets `order_markers()` narrate lines genuinely out of source
    order — revealing only the specific line(s) each beat owns — without ever
    erasing code an earlier beat already showed or dragging along lines that
    haven't been visited yet.
12. **`PythonLexer(stripnl=False)` in `_render_code()`.** Pygments lexers
    strip leading/trailing blank lines by default; `_visible_code()` renders
    not-yet-revealed lines as empty strings, so a leading run of them (e.g.
    only line 7 of 7 revealed so far) would otherwise get stripped and shove
    the real content up to row 1 — silently breaking every out-of-order
    reveal. Don't drop `stripnl=False`, even though single-pass, top-to-bottom
    (no leading/trailing blanks) renders look identical either way.
13. **`STYLE` may be a pygments style name OR a `Style` subclass** — every
    call site must handle both. `ImageFormatter`/`Formatter._lookup_style`
    already do (pygments accepts either natively); `plan_canvas()`'s
    background-color lookup does not (`get_style_by_name()` requires a
    string), so it goes through `_resolve_style()` instead — don't call
    `get_style_by_name(STYLE)` directly. `_resolve_style()` is also where
    the background override is applied, so **both** consumers must go
    through it — `plan_canvas()` for the canvas fill and `_render_code()`
    for the pygments code block. Passing a bare `STYLE` to `ImageFormatter`
    again would paste a differently-colored code rectangle onto the canvas.
    Since `--style`/`--bg-color` made these per-render rather than global,
    `plan_canvas()` resolves them **exactly once** and stores the result on
    `Canvas.style`; `compose()` passes `cv.style` down to `_render_code()`.
    Resolving again per frame from the globals instead would let one video
    mix two themes (and would re-run `StyleMeta` per frame — the reason
    `_with_background()` is `lru_cache`d). Relatedly, caption/rule colors
    (`COL_CAPTION`/`COL_RULE`) are hardcoded for a DARK background; a light
    STYLE (e.g. `LightModernStyle`) needs `COL_CAPTION_LIGHT`/`COL_RULE_LIGHT`
    instead, or the caption is nearly invisible. `plan_canvas()` picks
    between them via `_is_light()` (perceived luminance of the resolved
    background) and stores the result on `Canvas.cap_fg`/`cap_rule` — don't
    reintroduce a hardcoded `COL_CAPTION`/`COL_RULE` reference in
    `_draw_caption()`.
14. **Inline `..` pause markers (and `say`'s ALL-CAPS emphasis rewrite) must
    never reach the manual backend.** `_cached_synth(..., pause_mode=...)` is
    `"none"` exactly when `tts == "manual"`, never `"split"` or `"say"`;
    either of those would call `synth_manual()` more than once for a beat
    whose narration contains a pause marker (`"split"`), or hand it rewritten
    `[[slnc]]`/`[[emph]]` text that doesn't match what a human actually
    recorded (`"say"`), silently shifting every subsequent beat's file number
    out of alignment with `--export-script`'s numbering — the same class of
    bug the manual-backend/`--record` numbering code elsewhere already
    guards against (see "TTS backends" below).

15. **The highlight band is redrawn by `_tighten_highlight()`, and that
    depends on three pygments behaviours.** `ImageFormatter.format()` (a)
    fills the band across the FULL image width, (b) fills it *before* drawing
    any text, and (c) passes an `ImageDraw.rectangle` bottom coordinate of
    `y + recth`, which is **inclusive** — so its band is one row taller than
    the line box and bleeds into the top row of the next line. (a) is why the
    band needs redrawing at all (no left padding, arbitrary right padding);
    (b) is what makes repainting safe, since anything still exactly
    `hl_color` inside those rows is band and nothing else; (c) is why every
    rectangle drawn here must reach `y_bot` — stopping a row short leaves a
    1px full-width stripe of the old band under the highlighted line (a real
    bug, caught visually then pinned down by pixel probe). Related: rows are
    uniform and the image is exactly `len(code.splitlines())` of them tall
    (verified against leading blanks, trailing blanks and `_visible_code()`'s
    sparse shapes), which is how the band's y-range is located without
    touching pygments internals.

16. **`_render_code()` adds an `HL_PAD` background margin down each side,
    always — highlighted or not.** It's what gives a highlight on an
    unindented line somewhere to put its left padding (pygments starts column
    0 hard against x=0). It must be unconditional because `plan_canvas()`
    measures the code column from an *unhighlighted* render while `compose()`
    draws highlighted ones; if only one grew, the column would be mismeasured
    and the state panel could overlap the code (invariant 1).

### TTS backends

A backend is any `synth(text, out_stem) -> path_to_audio_file`; `make_clip`
re-encodes whatever it returns, so the container/rate don't matter. Registered
in the `BACKENDS` dict: `say` (macOS), `silent` (timing stand-in), `piper`
(local, `pip install snippet-cast[piper]` or bare `pip install piper-tts`;
voices need a one-time `python -m piper.download_voices <voice>`),
`elevenlabs` (REST via stdlib urllib), `manual` (your own recordings —
`BACKENDS["manual"]` is `None`, a placeholder just so `--tts manual` shows up
in argparse's choices; `build()` special-cases `tts == "manual"` and builds a
real `synth` via `make_manual_backend(manual_audio_dir)`, a closure that
serves `001.wav, 002.wav, ...` in call order). Config and setup live in
**SETUP.md**. Note: `build()` **caches audio per unique narration string** —
matters for ElevenLabs billing, for repeated loop lines, and for keeping the
manual backend's file-numbering aligned with `export_script()`'s (see
`_cached_synth()`/`_format_script()` — both dedup on the exact same
first-seen-narration-text rule, so the Nth unique line in the exported script
is always the Nth call to the manual backend).

`build()`, `export_script()`, and `record_narration()` all share one parse ->
two-pass-detect -> validate -> trace -> beats preamble, `_build_all_beats(source_path,
trace, every, allow_unnarrated=False) -> (code_lines, beats1, beats2, unnarrated)`
— the single source of truth for two-pass detection, the `every`+two-pass /
`every`+order-prefix validation `sys.exit`s, and the no-narration
`sys.exit`/opt-in (see "Unnarrated snippets" below). `build()`'s render half (everything after that preamble) is its
own function, `_render_from_beats(code_lines, beats1, beats2, out_path, tts,
synth, trace, every, subtitles, typing, typing_speed, pause)` — `build()` is
just `_build_all_beats()` then `_render_from_beats()`. This split exists so
`record_narration()`'s `build_after` step can call `_render_from_beats()`
directly with the SAME `beats1`/`beats2` its interactive session already
built, instead of calling `build()` (which would call `_build_all_beats()`
again — a second `trace_run()`, i.e. a second full execution of the user's
snippet, confirmed to happen in an earlier version: a print in the snippet
showed up twice in one `--record` session's output). `_format_script()` and
`record_narration()` also share `_narration_sequence(beats1, beats2)`, a
generator yielding `(pass_no, beat_idx, beat, number, dup_of)` per beat —
`number` is the same 1-based, first-seen-unique-narration numbering the
manual backend consumes; `None` means the beat needs no recording of its own
(silent, or `dup_of` an earlier number). Anything that needs to walk "exactly
the beats `--tts manual` requests audio for" should build on
`_narration_sequence()`, not re-derive the dedup rule.

**`--record`** (`record_narration()`) interactively records narration for the
manual backend via the system microphone — macOS only for the recording
itself, no new dependency (shells out to `system_profiler`/`ffmpeg -f
avfoundation`/`afplay`, the same subprocess pattern as everything else in
this file). It walks `_narration_sequence()`, prompting only at beats with a
`number` (dup/silent beats are shown for context and skipped automatically),
and stages every change (new recordings to a session tempdir, deletions
deferred) so nothing touches `manual_audio_dir` until the whole walk
finishes without a Ctrl+C — an abort at any point, including mid-recording,
discards the session. Uses `input()` throughout (no raw keypress handling)
so the same code works from a terminal or a notebook cell — `magic.py`'s
cell magic wires `--record` straight to it too.

`_decide_recording()`'s default (blank Enter) is deliberately
context-dependent, not a fixed mapping: with an existing recording, Enter
means 'keep' (safe — something real is being kept). With NO existing
recording there is nothing to keep, so Enter is rejected there (re-prompts)
rather than silently returning `("keep", None)` — leaving a beat unrecorded
now requires the explicit `'s'` (skip). This was a real bug, not
hypothetical: `build(tts="manual")` (via `make_manual_backend()`) fails
outright — a plain `sys.exit` — on the first beat with no numbered file, and
a blank Enter used to be a silent way to end up in exactly that state.
`record_narration()` also does a final sweep after the walk (re-running
`_narration_sequence()` — cheap, no I/O) for any number still missing a
recording (skipped this session, or from an earlier one); if any remain, it
prints an itemized note and skips `build_after` rather than letting it hit
that same `sys.exit` — the auto-build silently attempting and failing was
the actual symptom that surfaced this whole issue.

Frame preview (`show_frame`) is injectable via `frame_fn(png_path)`, same
pattern as `input_fn`/`record_fn`/`play_fn` — this is how one function
serves two very different display contexts without `screencast.py` ever
importing IPython (a hard constraint — see "Conventions"): left at its
default `None`, `record_narration()` resolves it to `_show_frame_imgcat`
(shells out to `imgcat`, common across iTerm2/WezTerm/Kitty-style
terminals) if `imgcat` is on PATH, else prints a one-time note and disables
`show_frame` for the rest of the session rather than failing it over a
visual nicety.

`magic.py` passes its own `_LiveRecordView` instance instead — status text
and the current frame each update ONE existing cell output in place (via
`IPython.display`'s `display_id`/`DisplayHandle.update()`) instead of a
fresh `display()` per beat piling up as a growing stack of separate
outputs (the original `_show_frame_notebook`, one plain `display(Image(...))`
call per beat with no `display_id`, had exactly that problem — replaced).
One object serves two roles: it's `frame_fn` directly (`__call__(path)`),
and `contextlib.redirect_stdout(view)` wraps the whole `record_narration()`
call so its `write()`/`flush()` also capture every `print()`
`screencast.py` makes, keeping a short rolling window (`max_lines`) instead
of unbounded scrollback. **Recursion hazard, already hit and fixed**: don't
call `display()`/`.update()` from `write()`/`__call__` while `sys.stdout` is
*still* redirected to the same object — if `display()`'s own internals
happen to write anything to stdout, that write loops back into `write()`
again (observed as `RecursionError` deep in
`IPython.core.display_functions.display`, wrapped in IPython's "Unexpected
exception formatting exception" handler, which obscures the real cause).
Fixed by capturing `self._real_stdout = sys.stdout` in `__init__` — *before*
the caller wraps it — and temporarily restoring that specific object (not
`sys.__stdout__`, which bypasses ipykernel's own stdout routing and
wouldn't land in the cell) around each `display()`/`.update()` call.

Two more real bugs, both only surfaced by testing through the actual
IPython display machinery (a plain unit test with a stubbed-out `display()`
wouldn't have caught either):
1. `display()` on a bare Python `str` renders it via `repr()` — quoted,
   with literal `\n` escapes, not actual line breaks — confirmed this is
   real `display()` behavior, not a headless-test-harness artifact.
   `write()` wraps the text in `HTML(f"<pre>{html.escape(text)}</pre>")`
   instead; `<pre>` preserves whitespace/newlines exactly, unambiguously,
   in any HTML-capable frontend.
2. Python's `print()` calls the target's `.write()` **twice** per line —
   once with the content, once more with just the trailing `"\n"` (its
   default `end`). `write()` used to recompute and re-`display()`/`.update()`
   on every single call, including that first content-only one where
   `self._lines` is still empty — flashing the display through the "no
   complete line yet" placeholder state on every `print()`. Fixed by only
   updating once a `"\n"` actually completes a line (tracked via a local
   `added` flag in the split loop).

`_LiveRecordView.clear()` (`clear_output(wait=True)`, same
capture-real-stdout-first pattern as `write()`/`__call__`) empties the
status/frame areas entirely — called from `magic.py`'s `--record` branch
right before `display(Video(...))`, so the per-beat scrollback doesn't
linger as clutter under the actual result. **Only** called on a genuine
success — `committed=True` AND `out_path` actually exists. `record_narration()`
returning `True` does NOT by itself mean a video got built: it's also `True`
when the session committed cleanly but `build_after` was skipped because
beats still lack a recording (see the pre-build check above) — in that case
`out_path` is never created, and the cell magic must neither call
`view.clear()` (the "still have no recording" note is exactly what the user
needs to see next) nor attempt `display(Video(out_path, ...))` on a file
that doesn't exist (an easy latent crash — `IPython.display.Video`, like
`Image`, reads eagerly at construction, so this fails immediately, not
lazily on render). Guarded by a plain `os.path.exists(out_path)` check.
Two bugs worth knowing if you touch
`_decide_recording()`/`_record_until_enter()`, both confirmed via a real
`--record` session, not just reasoning about the code:
1. Sending SIGINT before ffmpeg has finished opening the device can produce
   **no output file at all**. `_record_until_enter()` polls for the file to
   appear before honoring the stop, and returns `False` (instead of leaving a
   broken file for `shutil.move` to choke on later) if a take still comes up
   empty; `_decide_recording()` sends that back to the *outer*
   `[Enter=keep, r=record, d=delete]` prompt.
2. Typing `r` (redo) at the `[Enter=accept, r=redo]` prompt must loop back
   into another recording attempt for the SAME beat, in its OWN inner loop —
   it must never fall through to that same outer prompt, because a plain
   Enter there (typed to confirm the redo, not realizing it landed on a
   different prompt) reads as "keep the recording that already exists" (none,
   for a first take), silently discarding the just-recorded audio with no
   error. This exact sequence — record, redo, Enter — was reproduced live: a
   2-beat session recorded both beats, committed only one, and the follow-up
   build failed with a missing-recording error for the discarded one.

`_record_until_enter()`'s ffmpeg call uses `-loglevel error` and reads
`stderr=subprocess.PIPE` once at the end on failure (surfacing ffmpeg's own
error — e.g. a mic permission problem — instead of silently discarding it).
The `-loglevel error` is load-bearing, not cosmetic: ffmpeg's default
verbosity writes continuous progress lines to stderr for the whole capture,
and since that pipe is drained only once at the end, an unsuppressed stream
would risk filling the OS pipe buffer and stalling a long recording (verified
`-loglevel error` produces zero stderr bytes on a normal capture). Also bails
out of `input_fn()` entirely if ffmpeg has already exited by the time the
startup poll finishes (e.g. permission denied) — waiting on Enter for a
recording that's already dead is pure confusion, not a real "press Enter to
stop" moment. Microphone permission on macOS is granted **per application**:
a terminal being allowed doesn't mean a notebook's host app (VS Code, Jupyter
Desktop, ...) is — check System Settings -> Privacy & Security -> Microphone
for whichever app is actually running the kernel if `--record` seems to hang
or hit repeated failures with no clear cause.

`_record_until_enter()` prints `"starting microphone..."` immediately, then
only prints `"recording — press Enter to stop."` once the startup poll has
actually confirmed capture began (the file exists) or bails to the failure
path — not immediately after the ffmpeg `Popen`, which would claim
"recording" before capture had necessarily started.

### CLI / notebook configuration: SNIPPET_CAST_* environment variables

Every `main()`/`%%snippet-cast` option **except `-o`/`--output`** has a
`SNIPPET_CAST_<NAME>` environment variable default (e.g. `SNIPPET_CAST_PAUSE`,
`SNIPPET_CAST_TTS`, `SNIPPET_CAST_NO_TRACE`) — precedence is explicit flag >
env var > hardcoded fallback. `resolve_env_defaults(args, **fallbacks)`
(shared by both `main()` and `magic.py`) fills in any `args` field still at
its `None` sentinel from `os.environ`; `_env_default()` types the raw string
against the fallback's Python type (`bool`/`float`/else `str`), with a
truthy-string set (`1`/`true`/`yes`/`on`) for booleans. `main()`'s
`add_argument(...)` calls all use `default=None` (never a literal default)
specifically so this resolution step is the single source of truth — a
literal `default=` there would silently never get overridden by the env var.

**Why `magic.py` can't just use argparse's own `default=`, unlike `main()`:**
`@magic_arguments()`/`@argument(...)` decorate the `snippet_cast` *method*,
so those decorator calls (including any `default=...`) run exactly once, at
class-body evaluation — i.e. module *import* time — not fresh per cell
execution the way `main()`'s `ArgumentParser()` (built fresh inside the
function body) is. A literal `os.environ.get(...)` in a decorator's
`default=` would only ever see the environment as it was when
`snippet_cast.magic` was first imported — silently ignoring an env var set
in a *later* cell, exactly the documented workflow
(`os.environ["SNIPPET_CAST_PAUSE"] = "0.6"` in one cell, `%%snippet-cast` in
the next). `resolve_env_defaults()` is instead called from inside the method
body, which *does* run fresh every cell — the fix.

Boolean flags (`--every`, `--subtitles`, `--typing`, `--record`,
`--export-script`) use `argparse.BooleanOptionalAction` (confirmed to work
through IPython's `magic_arguments`/`parse_argstring`, not just plain
argparse) so an env-var-forced-on default can still be turned back off for
one run via `--no-X` — in both `main()` and `magic.py`, kept in sync.
`--no-trace`/`--no-frame` are the exception: already negatively named, so
`BooleanOptionalAction` would produce an ugly `--no-no-trace`; they stay
plain `store_true` with `default=None`, resolved the same way — an env var
can force them on, with no CLI opt-out beyond not passing the flag /
env var (documented limitation, not a bug).

`-n/--name` (default `"out"`) and `-d/--output-dir` (default `.`, created if
missing) build the output path as `output_dir/name.mp4` via
`resolve_output_path()`; `-o/--output`, if given, overrides both outright and
has no env var of its own (SNIPPET_CAST_OUTPUT_DIR + SNIPPET_CAST_NAME
already cover the "change my default output location" case without one).

### Verifying changes

After any edit, run this sequence and eyeball a couple of frames:

```bash
pixi run python -c "import ast; ast.parse(open('src/snippet_cast/screencast.py').read())"  # syntax
pixi run snippet-cast test/data/fib.py  -o /tmp/a.mp4 --tts silent --typing --subtitles
pixi run snippet-cast test/data/loop.py -o /tmp/b.mp4 --tts silent --every --subtitles
for f in /tmp/a.mp4 /tmp/b.mp4; do ffprobe -v error -show_entries \
  format=duration -show_entries stream=width,height -of csv=p=0 "$f"; done
ffmpeg -y -ss 2 -i /tmp/b.mp4 -frames:v 1 /tmp/frame.png   # inspect visually
pixi run python -m pytest -q                               # automated checks
```

`test/test_magic.py` covers the `%%snippet-cast` cell magic via
`IPython.testing.globalipapp.get_ipython()` + `run_cell(...)` (no real kernel
needed); it's skipped automatically if IPython isn't installed.

For trace/interpolation logic, prefer a fast unit check over rendering video:

```bash
pixi run python -c "import snippet_cast.screencast as s; src=open('test/data/loop.py').read();
cl,mk=s.parse(src); st=s.trace_run(src,'test/data/loop.py'); lr=s.loop_body_ranges(src);
[print(b.highlight, b.state, '::', b.narration)
 for b in s.build_beats(cl,mk,st,every=True,loop_ranges=lr)]"
```

### Conventions

- **`screencast.py` is single-file, stdlib-first.** Only hard third-party deps
  are Pillow and Pygments; everything else (HTTP for ElevenLabs, AST, tokenize)
  is stdlib. Keep new deps out of this file unless there's a strong reason.
  `magic.py` is the one deliberate exception — it needs IPython, so it's kept
  as its own optional module rather than pulled into `screencast.py`.
- **Tunables are module-level constants** at the top (`MARKER`, `STYLE`, `FONT_*`,
  `FPS`, `TYPE_*`, `AUDIO_*`, colours). Add config there, not as magic numbers.
- **ffmpeg is called via `subprocess.run`** with stdout/stderr to DEVNULL and
  `check=True`. Follow that pattern; surface real errors (see `synth_piper`).
- Private helpers are `_prefixed`. Rendering is split: `_render_code`
  (pygments, plus a hand-drawn pass over the highlight band in
  `_tighten_highlight`) vs `render_panel`/`_draw_caption` (hand-drawn PIL).

### Common changes

- **Add a TTS backend:** write `synth_x(text, out)->path`, add to `BACKENDS`. Done.
- **Recolor the state panel:** `--state-bg-color '#rrggbb'` /
  `--state-fg-color '#rrggbb'` (or the `SNIPPET_CAST_STATE_*_COLOR` env vars,
  or `build(state_bg_color=..., state_fg_color=...)`) —
  `resolve_panel_args()`/`_panel_colors()`/`PanelColors`. See the theme bullet
  below for why `--state-fg-color` covers names and values together.
- **Output resolution** is DERIVED, not set: `W = even(PAD + code_w + [GAP +
  panel_w] + PAD)`, `H = even(PAD + code_h + PAD + cap_h)`. Steer it with
  `--font-size`, `--no-trace` (drops the panel) and `--subtitles`, or fix it
  outright with `--screenflow` (below). Note width and height are not
  independent once `--subtitles` is on: `--no-trace` narrows the canvas, so
  captions wrap onto more lines and the video gets TALLER.
- **Recolor the highlight band:** `--highlight-color '#rrggbb'`
  (`SNIPPET_CAST_HIGHLIGHT_COLOR`, `build(highlight_color=...)`). Applied
  through `_resolve_style()`/`_with_colors()` like `--bg-color`, which is what
  keeps pygments' band and `_tighten_highlight()`'s repainted edges the same
  color — overriding only one would leave two-tone edges.

  **The shipped default is `HIGHLIGHT_COLOR = HIGHLIGHT_PANEL` (`"panel"`),
  which tracks the STATE panel background** so the band behind the current
  line and the STATE box read as one surface — and it tracks the *resolved*
  one, so `--state-bg-color` carries the band with it. That is why
  `plan_canvas()` resolves the panel BEFORE the style and passes
  `panel_bg=panel.bg` down; `_resolve_style()` does the substitution (falling
  back to the `PANEL_BG` global for standalone callers with no canvas), which
  keeps it the single choke point and makes the call idempotent — a concrete
  color passed in comes back unchanged.

  Two consequences of that default. First, `PANEL_BG` now sets two surfaces,
  so the "must stay a visible step away from the page background" rule below
  governs the band as well. Second, `_resolve_style()` now ALWAYS applies an
  override, so it always returns a `_with_colors()` subclass rather than the
  style class itself — a test asserting `is load_theme(...)` had to become
  `issubclass` (it also pins that resolving twice returns one cached class,
  since `_render_code()` resolves per frame).

  `'none'` is the escape hatch back to the style's own; that matters for a
  style declaring no `highlight_color`, since pygments' unset default is a
  pale `#ffffcc` and **both** shipped `Style` classes are in that boat — so
  `--style dark-modern --highlight-color none` gives a pale-yellow band,
  where plain `--style dark-modern` now gets the panel color. The CLI can
  tell "not given" from `'none'` because `resolve_env_defaults()`'s fallback
  is the `HIGHLIGHT_COLOR` global (the literal `"panel"`) while `'none'`
  maps to Python `None` — `_hex_color_arg()` grew an `allow=` list so the
  `"panel"` spelling passes validation.
- **Use a Pandoc/KDE `.theme` file:** `--style path/to/x.theme` —
  `load_theme()` maps its `text-styles` onto pygments tokens via
  `THEME_TOKEN_MAP` — **the one place the two token vocabularies meet, and
  the only thing to edit when a theme reads wrong.** No color is hardcoded
  anywhere downstream. `_style_by_name()` only tries a file load once the
  string matches no built-in and no registered pygments name, so a `.theme`
  can never shadow a real style name.

  Two rules govern the mapping, both learned by getting it wrong (the first
  version colored `def`/`for`/`return` dark red and the name after `def` dark
  red too, neither of which is how the theme renders in pandoc):

  1. **Map onto the entry covering the same construct set — and where
     pygments is coarser, that is the theme's more GENERAL entry.**
     `PythonLexer` emits plain `Token.Keyword` for `def`/`class` *and*
     `for`/`if`/`return`, so the union goes to `"Keyword"`, never the
     narrower `"ControlFlow"`. Mapping the union onto the narrower entry is
     backwards and recolors the other half. Note `in`/`is`/`and`/`or`/`not`
     are `Token.Operator.Word`, not `Token.Keyword` — they need their own
     entry pointing at `"Keyword"` too.
  2. **Map only what the theme actually classifies.** KSyntaxHighlighting's
     Python definition colors keywords, builtins and literals, NOT
     identifiers the user writes — so `Name.Function` (the name after
     `def`), `Name.Class` and `Name.Namespace` are deliberately ABSENT and
     inherit `Name` -> `"Variable"`, i.e. the theme's plain text color.
     Adding them back invents a color the theme never asked for.

  Anything unlisted falls through pygments' own token inheritance to `Token`,
  which `load_theme()` sets from the theme's top-level `text-color`. Verify a
  mapping change through the *lexer*, not by eye — see
  `test_theme_colors_a_real_snippet_token_by_token`, which pins every token
  of a real snippet; a per-entry guess can look plausible and still be wrong
  for the token pygments actually emits.

  The format has no highlight color, so one is derived by nudging the
  background `THEME_HL_MIX` toward black or white (per `_is_light`) rather
  than inheriting pygments' pale default. `load_theme()` is cached on the path
  **plus the file's mtime/size** (`_theme_stamp()`) because `_render_code()`
  resolves the style once per *frame*. The stamp is not optional: keyed on the
  path alone, an edited `.theme` stayed invisible for the life of the process
  — a shrug for a one-shot CLI run, but in a Jupyter kernel every later
  `%%snippet-cast` kept rendering the theme as it was when the kernel first
  read it, with a restart the only way out.

  **There is exactly ONE `numpy.theme`**, at `src/snippet_cast/themes/` — the
  only location `pyproject.toml`'s `package-data` ships. `data/numpy.theme` is
  a SYMLINK to it, kept because that is the path people reach for when
  editing; the tests load the packaged path. It used to be a second real file,
  and the two silently diverged twice in one session — colors edited in
  `data/` while `--style numpy` read `src/`, with no error, just an unchanged
  video. Don't turn it back into a copy. (`build/lib/.../numpy.theme` is a
  stale setuptools artifact, not a source; it is what `pip install .` copies
  into site-packages, where it can shadow `src/` entirely — `pixi run`
  re-syncs the editable install and clears that.)
- **Change theme/background:** a per-run option, not a source edit —
  `--style NAME` / `--bg-color '#rrggbb'` on the CLI and the cell magic,
  `SNIPPET_CAST_STYLE` / `SNIPPET_CAST_BG_COLOR` as env vars, or
  `build(style=..., bg_color=...)` programmatically. `STYLE`/`BG_COLOR`
  remain the module-level *defaults* those fall back to. **The shipped
  default is `STYLE = "numpy"` with `BG_COLOR = None`** — the packaged
  `numpy.theme` (a LIGHT theme, `#F3F4F5`), with `BG_COLOR` left at `None`
  precisely so the theme's own background comes through. Those two go
  together: setting `BG_COLOR` back to a dark color while `STYLE` is a light
  theme renders dark-on-dark. `PANEL_BG`/`COL_*` were retuned to light to
  match. The previous dark look is `--style monokai --bg-color '#1F1F1F'
  --state-bg-color '#181818'`. `--style` takes a `BUILTIN_STYLES` key, a
  `BUILTIN_THEMES` key, any registered pygments style name, a path to a
  `.theme` file, or — programmatically only, since the CLI
  can only pass a string — a
  `pygments.style.Style` subclass directly (no pygments registration/entry
  point needed; `_resolve_style()` handles all three — see critical invariant
  13). `--style list` prints every valid name and exits; **this is why
  `main()`'s `input` positional is `nargs="?"`** — it's the one invocation
  with nothing to render, and every other path still requires it via an
  explicit `ap.error()`. `BUILTIN_STYLES` maps `"dark-modern"`/
  `"light-modern"` to the two `Style` subclasses shipped in `screencast.py`
  (`DarkModernStyle`/`LightModernStyle`, colors taken directly from VS Code's
  own theme-defaults source for its built-in "Dark Modern"/"Light Modern"
  themes); the dict exists *because* those aren't registered with pygments,
  so `get_style_by_name()` can't find them and `--style` couldn't otherwise
  reach them. `BUILTIN_THEMES` does the same job for `.theme` files shipped
  *inside* the package (`src/snippet_cast/themes/`, declared in pyproject's
  `[tool.setuptools.package-data]` — verified present in a built wheel), so
  `--style numpy` resolves from an install rather than only inside a
  checkout; they're loaded lazily by `_style_by_name()`, which checks
  built-ins and the pygments registry BEFORE the filesystem so a stray file
  named `monokai` in the working directory can't shadow a real style.
  `style_names()` is the single source for every listing and error message.
  `resolve_style_args()` (shared by `main()` and `magic.py`, both
  of which pass the raw strings through it) validates a name against both
  sources and normalizes the `--bg-color` spelling `"none"` to Python `None`
  — raising `ValueError` that each front end renders its own way (`sys.exit`
  vs. a stderr print), so an unknown style is caught at parse time instead of
  as a pygments `ClassNotFound` from inside the first frame render, *after*
  the trace has already executed the user's snippet. `--bg-color` is
  deliberately restricted to `#rrggbb` (not the wider set PIL accepts)
  because `_is_light()` parses it by slicing those exact six hex digits.
  `plan_canvas()` picks readable caption/rule colors for whichever background
  actually wins via `_is_light()` (luminance) — see invariant 13.
  **Quoting differs between the front ends**, so `_hex_color_arg()` and
  `resolve_screenflow_arg()` both run values through `_unquote()`. On the CLI
  a bare `#rrggbb` would be eaten as a shell comment, so the docs show
  `--bg-color '#1F1F1F'` and the shell removes the quotes; in a
  `%%snippet-cast` line there is no shell, and IPython's `parse_argstring`
  hands the value over with the quotes attached — so the exact spelling the
  docs teach was rejected as not-a-hex-color. Stripping one matched pair
  makes both spellings work in both places (a no-op on the CLI).

  `bg_color` overrides whatever background the style itself declares without
  touching its syntax colors; it does NOT adapt them, so pairing a dark
  background with a light style is on the caller. Note the three-state
  argument: `bg_color=None` means "no override, use the style's own", which
  is NOT the same as the caller saying nothing — hence the `_USE_DEFAULT`
  sentinel as the parameter default down the whole chain (`build()` ->
  `_render_from_beats()` -> `plan_canvas()` -> `_resolve_style()`).
  The state panel has its own per-run pair, `--state-bg-color` /
  `--state-fg-color` (`SNIPPET_CAST_STATE_BG_COLOR` /
  `SNIPPET_CAST_STATE_FG_COLOR`, `build(state_bg_color=, state_fg_color=)`),
  validated by `resolve_panel_args()` and resolved once into a `PanelColors`
  carried on `Canvas.panel` — same "resolve once, every frame draws from it"
  rule as `Canvas.style`. `--state-fg-color` is deliberately ONE knob for all
  the panel's text: it sets names and values alike; the default
  navy-names/black-values split needs `COL_NAME`/`COL_VALUE` edited instead.

  The panel is **just the box and its rows** — no "STATE" title, and no
  `"(no state)"` placeholder for a line that never executed (a function
  defined but never called now shows an empty box). Both were removed as
  noise, and each took dead code with it: dropping the title freed a row in
  `plan_canvas()`'s `panel_h` (so a state-heavy snippet renders a shorter
  frame) and left `FontSizes.panel_header` with nothing to size; dropping the
  placeholder left `PanelColors.header`, `COL_HEADER` and `HEADER_DIM` with
  no reader at all. All four are gone — if you reintroduce either label, they
  come back with it. Those constants (`PANEL_BG`, `COL_HEADER`, `COL_NAME`,
  `COL_VALUE`) remain the fallbacks, and are independent of STYLE and
  `BG_COLOR` — which means **they do not follow a `--style` change**, so a
  dark style needs its own `--state-*-color` pair (that asymmetry is
  deliberate: the panel is its own contrasting box, see `render_panel()`).
  `PANEL_BG` must stay a visible step away from the active page background or
  the STATE box blends into it and disappears — a real bug twice over now
  (`#1e1f1c` against `#1F1F1F`, then `#181818` against the light default;
  now `#DDDEDF` against `#F3F4F5`). Since `--highlight-color` defaults to
  `HIGHLIGHT_PANEL`, that one constant sets BOTH the box and the band behind
  the current line.

  Two-pass mode's writing pass hides the box entirely
  (`compose(show_panel=False)`), since it runs with `steps=[]` and so has an
  empty box on every frame. Hidden, not removed: one canvas size serves the
  whole video (invariant 1), so the space stays reserved and the frames still
  concat. Every pass-1 frame builder passes it — the typed reveal
  (`make_pass1_code_clip` -> `typing_frames`), the narrated hold, the
  `--pause` hold, and the seam frame held between the passes.
  `LINE_PAD` is the px of vertical breathing room in each code row, and
  `HL_PAD` (defined as `LINE_PAD`) is how far the highlight band extends past
  its line's text on the left and right — kept equal so the band has the same
  padding on all four sides; raising `HL_PAD` alone would widen every frame,
  since the same value sets the side margins `_render_code()` adds (see
  invariants 15 and 16).
  Font SIZE is a per-run option like the colors — `--font-size PX`,
  `SNIPPET_CAST_FONT_SIZE`, `build(font_size=)` — see the dedicated bullet
  below; `FONT_SIZE`/`PANEL_FONT_SIZE` remain the *defaults* it falls back
  to, and `FONT_NAME` (the typeface) is still a source edit only.
  `PANEL_FONT_SIZE` is defined as `FONT_SIZE`, so
  the panel's name/value text mirrors the code by default and only needs its
  own literal if you deliberately want them to differ (`GAP` is the px
  separation between the code column and the panel); panel background/text
  colours (`PANEL_BG`,
  `COL_HEADER`, `COL_NAME`, `COL_VALUE`) are separate constants, not derived
  from STYLE — they're drawn in their own contrasting box regardless of the
  main background (see `render_panel()`), so they don't need to be. Both the
  hand-drawn panel (`_mono_font`) and the pygments code frame (`_render_code`)
  resolve a font file via `_mono_font_path()`/`_FONT_CANDIDATES` first,
  falling back to `FONT_NAME`'s by-name OS lookup only if none of those paths
  exist — add paths to `_FONT_CANDIDATES` for a new platform/font rather than
  relying on `FONT_NAME` alone, since pygments resolves bare names against
  the OS's installed fonts (e.g. "DejaVu Sans Mono" isn't a stock macOS font).
- **Change the code font size:** `--font-size PX` (`SNIPPET_CAST_FONT_SIZE`,
  `build(font_size=...)`, default `FONT_SIZE`). Resolved ONCE per render by
  `_font_sizes()` into a `FontSizes` carried on `Canvas.fonts` — same
  "resolve once, every frame draws from it" rule as `Canvas.style` and
  `Canvas.panel` (invariant 13), and here it is load-bearing for invariant 1
  too: `plan_canvas()` *measures* the canvas at this size, so a frame drawn
  at any other size would not fit the dimensions it fixed. `_render_code()`
  and `render_panel()` therefore take the size as an argument and must never
  read the `FONT_SIZE`/`PANEL_FONT_SIZE` globals again.

  `--font-size` sets the CODE size; the panel, the caption and the panel
  header each keep the OFFSET they have from `FONT_SIZE` in the module
  constants, so the frame scales as one piece and a `PANEL_FONT_SIZE`
  deliberately edited to differ stays that much apart instead of being
  flattened into a mirror. `font_size=None` — and, equivalently, exactly
  `FONT_SIZE` — reproduces the constants unchanged, which is what keeps
  every pre-existing render byte-identical (pinned by
  `test_render_at_default_font_size_is_byte_identical`). The caption/header
  readability floors (14/12) are additionally capped at the size they are
  subordinate to, so a tiny `--font-size` can't leave the caption larger
  than the code it captions.

  `FontSizes`'s fields deliberately have NO defaults: a default evaluated in
  the class body would freeze the constants as of IMPORT time and silently
  ignore a later `sc.FONT_SIZE = 40` (a documented notebook workaround).
  Build one only through `_font_sizes()`.

  Adding this also taught `_env_default()` about `int` — note the `bool`
  branch must stay FIRST, since `isinstance(True, int)` is True and an int
  branch ahead of it would turn every boolean flag's env var into
  `int("true")`.
- **Render onto a fixed frame:** `--screenflow [WxH]` (`SNIPPET_CAST_SCREENFLOW`,
  `build(screenflow=(w, h))`, bare flag / truthy env var = `SCREENFLOW_SIZE`,
  1920x1080). Named for the workflow it exists for: producing a clip that
  drops straight onto a video-editor timeline, which needs BOTH a fixed
  resolution and the content centred in it — hence one flag, not a
  `--resolution` plus a `--center`.

  `plan_canvas()` measures the natural content-sized canvas **first**, exactly
  as without the flag, and only then pads out to the target. Measuring first
  is load-bearing: caption wrapping uses the natural width, so the caption
  band's height (and the beats' wrapped lines) stay identical to the unpadded
  render instead of re-flowing to the wider frame.

  Nothing is ever SCALED — the content block keeps its natural size and is
  centred, so text stays crisp. Pair it with `--font-size` to actually fill a
  large frame. A snippet whose natural canvas exceeds the target raises
  `ValueError` naming a `--font-size` that would fit, rather than shrinking
  silently; `_plan_canvas_or_exit()` turns that into a clean exit for the
  three render paths. It is the one look option that CANNOT be validated at
  parse time — it depends on the measured canvas, hence on the beats, hence
  on `trace_run()` having already run.

  `Canvas` therefore carries the content block (`cw`/`ch`) and its offset
  (`off_x`/`off_y`) alongside the frame (`W`/`H`). **Everything positional
  draws off the block, never off `W`/`H`** — `compose()`'s code and panel
  pastes and all of `_draw_caption()` (band top, rule extent, text centring).
  Without the flag they are `(W, H)` at `(0, 0)`, so every existing render is
  byte-identical (pinned by
  `test_screenflow_frame_keeps_the_content_pixel_identical`, which crops the
  padded frame back to the block and compares pixels). Reintroducing a
  `cv.W - PAD` into the caption drawing would stretch the rule to the
  letterbox edges the moment `--screenflow` is used.

  The value is OPTIONAL (`nargs="?"` + `const`, verified to survive IPython's
  `parse_argstring`, not just plain argparse), which means
  `snippet-cast --screenflow in.py` hands the input file to the flag and
  leaves `input` empty. `resolve_screenflow_arg()` detects that shape and says
  so; `main()` resolves it BEFORE its missing-input check specifically so that
  hint wins over argparse's generic "required: input".
- **Video controls (cell magic ONLY), always restyled:** Chrome/Safari draw
  the native control bar on a tall black gradient scrim that covers roughly
  the bottom TWO-THIRDS of the frame and hides the code, so `_controls_css()`
  strips it unconditionally — there is no flag to bring it back. What IS
  selectable is the glyph colour, because the UA draws the glyphs WHITE:
  against a light frame they vanish once the scrim is gone, so
  `filter:invert(1)` flips them dark; against a dark frame they are already
  legible and inverting is what hides them (measured in headless Chrome on a
  monokai render: peak luminance 31 inverted vs 255 left alone).

  **`--light-controls` (`SNIPPET_CAST_LIGHT_CONTROLS`) is TRI-STATE.** Unset,
  `_light_controls_for()` picks from the frame's own resolved background via
  `_is_light()` — the same luminance test `plan_canvas()` uses for caption
  colors — so the shipped light theme and `--style monokai` both come out
  right with no flag at all; `--light-controls`/`--no-light-controls` force
  it. Because `None` is a MEANINGFUL value here it cannot go through
  `resolve_env_defaults()`, whose whole contract is "fill anything still
  None", so its env var is read explicitly in the magic body. The
  auto-detection is wrapped in a try/except: a bad `--style` is reported by
  `resolve_style_args()`, and picking a glyph colour must not raise a second,
  confusing error on top of it.

  This needs a real `<style>` block — an inline `style` attribute cannot
  target a `::-webkit-media-controls-*` pseudo-element — so `_video()` now
  ALWAYS returns `HTML` rather than `Video`; `display()` takes either, but a
  test asserting "the last displayed HTML is the live-record status" had to
  become an `any(...)` because the video itself is now an HTML too. The two
  variants use DISTINCT class names (`CONTROLS_CLASSES`), which is
  load-bearing rather than cosmetic: a Quarto page can hold a light cell and
  a dark one, and two `<style>` blocks targeting the same class would leave
  the later rule governing BOTH videos. Scoping to a class also keeps it from
  restyling every other video on the page. Firefox ignores `-webkit-`
  pseudo-elements and keeps its own controls, which already have a legible
  flat backdrop. Verified end-to-end through `quarto render` plus a
  headless-Chrome screenshot of a mixed light/dark page.

  Note `invert(1)` is a true inversion, not "paint the glyphs black" — right
  only because the UA glyphs are white today.
- **`--help` in a cell (cell magic ONLY):** `%%snippet-cast --help` prints
  every option with its default and env var, then stops without rendering —
  **including from a cell with nothing under it**, which takes two pieces.
  IPython refuses a `%%` cell whose body is empty (`cell == ''` in
  `InteractiveShell.run_cell_magic`) and raises BEFORE any magic function is
  reached, so it cannot be handled inside the magic at all. So the magic is
  registered with `@line_cell_magic` (making `%snippet-cast --help` work, and
  making IPython's own refusal end "Did you mean the line magic
  %snippet-cast (single %)?"), and `_bodiless_cell_to_line_magic`, an input
  transformer on `input_transformers_cleanup`, rewrites a bodiless
  `%%snippet-cast ...` to `%snippet-cast ...` before that check runs. The
  transformer sees EVERY cell in the notebook, so it is deliberately narrow —
  first line opening with `%%snippet-cast` and nothing but blank lines under
  it — and its registration is guarded against `%load_ext` being called twice.
  Invoked as a line magic with anything other than `--help`, the magic says
  to use the cell form: there is no snippet to render.
  It needs an EXPLICIT `@argument("-h", "--help", ...)`: `magic_arguments`
  builds its parser with `add_help=False`, so otherwise `--help` is just an
  unrecognized argument and the cell fails with a `UsageError`. Handled
  immediately after `parse_argstring()` — before `resolve_env_defaults()` and
  every validation — so it answers whatever else the line or the cell body
  says. `_help_text()` strips `MagicArgumentParser.format_help()`'s
  docstring styling: a leading `::` reST literal-block marker, and the prog
  name `%snippet_cast`, which is neither the cell-magic spelling nor
  hyphenated.
- **Quarto cell directives (cell magic ONLY):** `_strip_directives()` removes
  whole `#|` lines from the cell before anything else sees it. They configure
  Quarto (`#| fig-column: margin`), not the snippet, so they must not be typed
  out, narrated or highlighted. Found through `_scan_comments()`/`tokenize`
  rather than line matching, for the same reason `parse()` does (critical
  invariant 5): a `#|` inside a string literal is not a comment. Only a
  comment that IS the whole line counts, so a trailing `x = 1  #| ...` is left
  alone. Whole lines are dropped rather than blanked — everything downstream
  re-derives its line numbers from the rewritten text (the `resolve_footnotes()`
  trick), and a blank row would take up height in every frame (invariant 12).
- **Where a cell's video goes (cell magic ONLY):** with no `-o`/`-n`/`-d` (or
  their env vars), `_cell_output_path()` writes to
  `CACHE_DIR/<12-hex hash of the cell>.mp4` — `.snippet-cast/`, beside the
  notebook. Two problems, one fix. Every cell used to default to `out.mp4`,
  so in a notebook of N defaulted cells the first N-1 videos were silently
  OVERWRITTEN by the last (`docs/pages/example.ipynb` had 6 cells writing
  `out.mp4`, 3 writing `hello.mp4`, 2 writing `fibster.mp4`); and a student
  running the notebook got those files strewn through their own folder.

  Hashed, not random, and the difference matters: a random name would mint a
  new file on EVERY execution, so an afternoon of tweaking narration would
  leave the directory full of orphans. Hashing the cell's own text (magic
  line AND body) makes a re-run of an unchanged cell reuse its file. Editing
  a cell does strand the old one — the directory is hidden and writes a
  `.gitignore` containing `*` on creation, and nothing can safely tell which
  files another notebook in the same folder still references.

  The path stays RELATIVE on purpose. An absolute one (a system tempdir, the
  obvious first idea) is not servable by a notebook front end and is not
  copied by Quarto, so the video renders as the browser's 300x150 black
  fallback box. Quarto's resource globbing was verified to reach into a dot
  directory, so `resources: - "**/*.mp4"` picks these up — see the note on
  `docs/_quarto.yml` below.
- **Fit the video to its container (cell magic ONLY):** `--responsive`
  (`SNIPPET_CAST_RESPONSIVE`), **on by default** — `max-width` never scales a
  small video UP, so capping it is only ever an improvement;
  `--no-responsive` keeps the intrinsic size. The frame is sized to the snippet
  (`plan_canvas()`), so one wide line of code makes a wide video — 2080px for
  an 80-char line — and neither Quarto nor Bootstrap caps `<video>` width, so
  it overflows the content column. `_video()` in `magic.py` passes
  `RESPONSIVE_STYLE` (`max-width:100%;height:auto`) through
  `IPython.display.Video`'s own `html_attributes`, which styles the `<video>`
  ELEMENT — a styled wrapper div would itself be capped while the video inside
  kept overflowing it. `html_attributes` replaces the default wholesale, hence
  re-stating `controls`. Nothing is emitted unless asked for: the
  non-responsive call is byte-for-byte the pre-existing one (pinned by a
  test), and both the plain-src and embed/base64 paths keep working since
  Video builds the src either way. Verified through a real `quarto render`.

  **This is deliberately magic-only** — the one place the "a new option needs
  a matching `@argument` in BOTH `main()` and `magic.py`" rule does not apply.
  It is purely about how a front end lays the result out; `snippet-cast`
  writes a file and displays nothing, so there is no CLI equivalent to add.
- **Videos in the Quarto docs:** `docs/_quarto.yml` needs
  `project: resources: - "**/*.mp4"`. `%%snippet-cast` writes its `.mp4` as a
  side effect of executing the cell and displays it through a relative
  `<video src>`; Quarto does not discover a resource that way, so without the
  glob the videos are simply absent from `_build` and every one renders as a
  300x150 black box (this was a live bug). `--embed` is the alternative —
  self-contained pages, immune to both resource copying and `freeze`, at
  roughly +35% page size per video.
- **Silence the terminal:** `-q`/`--quiet` (`SNIPPET_CAST_QUIET`,
  `build(quiet=...)`, `export_script(quiet=...)`). Every informational print
  goes through `_say()`, a one-line wrapper over `print()` gated on the
  module-level `_QUIET`; `_quieted(bool)` is the context manager that sets it
  (restoring the previous value, and nesting can only ever TIGHTEN — an inner
  `quiet=False` cannot un-quiet an outer `quiet=True`).

  A module flag rather than a threaded parameter because this is
  cross-cutting: `trace_run()`, `resolve_footnotes()`, `_build_all_beats()`,
  `_render_from_beats()` and `_render_two_pass()` would all need it, and
  several already carry very long signatures. `build()` is a thin
  `_quieted()` wrapper around `_build()` purely so the body needn't be
  re-indented; `main()` sets `_QUIET` once directly, since a CLI run is a
  whole process and the argument-validation notes fire before `build()` is
  even called.

  Three deliberate exclusions:
  - **Errors are never silenced.** They go out via `sys.exit`/stderr, which
    `_say()` doesn't touch, so a quiet run that fails still says why.
  - **`--export-script` and `--style list` still print.** Those lines are the
    command's RESULT, not chatter — `-q` just strips the trace warnings
    around them, which is what makes `--export-script -q > script.txt` clean.
  - **`--record` rejects `--quiet`** outright: recording is an interactive
    session whose prompts ARE its output.

  `_quiet_stdout()` additionally redirects the traced snippet's own `print()`
  output (`trace_run()` executes user code) — a no-op when not quiet.
- **Play beats in execution order:** `--order exec` (`SNIPPET_CAST_ORDER`,
  `build(order=...)`) — `_exec_beats()`; see the section above for the
  entry/call/done visit model and its rules.
- **Change the narration marker:** `MARKER` (keep it a valid `#` comment prefix).
- **Adjust typing speed:** default is `TYPE_SPEED` (seconds/char, currently
  `0.1`), overridable per-run with `--typing-speed`. There is only ONE
  constant: both legacy `--typing` (`typing_frames()`) and two-pass mode's
  writing pass (`make_pass1_code_clip()`) default their `typing_speed`
  parameter to it, and both front ends fall back to it — so the two modes
  cannot drift apart.

  `TYPE_MAXFRAMES` is a safety cap on frames per beat regardless of speed,
  and it silently bounds the speed that can actually be DELIVERED: a beat
  types for at most `TYPE_MAXFRAMES / FPS` = 15s, so a reveal group longer
  than `15 / TYPE_SPEED` characters (150 at the default) is compressed to fit
  rather than paced at `TYPE_SPEED`. It is set to cover a 150-char line on
  pace; none of the shipped samples comes close.

  Raising it is cheap because a clip is `max(typing, narration)` long: when
  narration is the longer stream — the normal case for a real screencast —
  a bigger cap changes the typing's PACING but not the video's duration or
  size at all (`footnote.py` renders identically at 150 and 450 frames:
  46.9s, 0.30 MB). It only stretches the video where typing genuinely
  outruns the narration. Cost is otherwise linear at ~9ms and ~14KB of temp
  PNG per frame, and temp frames live until `concat()`. The `%03d` frame
  naming is NOT a 999-frame ceiling — Python's `:03d` is a minimum width and
  ffmpeg's pattern matches the same way (verified past 1000), which matters
  because the narration floor can already push a pass-1 sequence beyond it.
- **Two-pass narration:** add `/` to a `#:` narration (`split_narration`);
  first-exec only, auto-detected, no flag needed. `TWO_PASS_SEP` changes the
  separator character; `PART2_EMPTY_HOLD` is how long the walkthrough pass
  holds a beat whose part2 text is empty.
- **Footnote narration:** use the same `N)` label twice — once on the line it
  narrates, once on a comment-only block holding the text (wrapping over
  plain `#` lines) — `resolve_footnotes()`/`_footnote_comment()`, first-exec
  only, auto-detected, no flag needed. Pairing is by occurrence count, so
  single-occurrence `N)` order prefixes mix freely with it in one file.
- **Custom narration order:** add a leading `N)` to a `#:` narration
  (`_parse_order`/`order_markers`, `_ORDER_RE`); first-exec only, per-pass in
  two-pass mode, no flag needed — all-or-none per pass, else `sys.exit`.
- **Inline pauses:** write 2+ consecutive periods in a `#:` narration
  (`PAUSE_MARKER_RE`); `PAUSE_PER_PERIOD` seconds of silence per period
  (`--tts say` instead rewrites it to its own `[[slnc N]]` markup, N =
  `SAY_PAUSE_MS_PER_PERIOD` per period — see `_say_markup`). Works in any
  mode, both passes of two-pass mode, no flag needed — except `--tts manual`,
  which ignores it (critical invariant 14).
- **`say`-only ALL-CAPS emphasis:** a run of 2+ consecutive ALL-CAPS words in
  a `#:` narration is flanked with `say`'s `[[emph +]] ... [[emph -]]`
  (`SAY_EMPHASIS_RE`/`_say_emphasis_markup`) whenever `--tts say` is used; a
  no-op for every other backend, including `--tts manual` (critical
  invariant 14).
- **Manual-recording tooling:** `--export-script` (`export_script()` /
  `_format_script()`) and `--tts manual` (`make_manual_backend()`) — see the
  "Two-pass narration" architecture note above for how their numbering stays
  aligned with `build()`'s own audio-request order.
- **Interactive recording (`--record`):** `record_narration()` — see the "TTS
  backends" architecture note above. New CLI flags for it need a matching
  `@argument(...)` in both `main()` and `magic.py`'s cell magic (same rule as
  every other flag — see below); the microphone/playback/preview steps are
  each a small standalone function (`_default_input_device()`,
  `_record_until_enter()`, `_play()`, `_preview_code_text()`) with
  injectable `input_fn`/`record_fn`/`play_fn` params specifically so the
  keep/record/delete/abort control flow is unit-testable without real audio
  hardware — extend that pattern rather than inlining new I/O calls directly
  into `record_narration()`'s loop.
- **Jupyter `%%snippet-cast` cell magic:** lives in `src/snippet_cast/magic.py`
  (`SnippetCastMagics`). `import snippet_cast.magic` auto-registers it when
  run inside a live kernel (module-level `get_ipython()` check calls
  `load_ipython_extension()` itself); `snippet_cast/__init__.py` runs the
  same check (`_register_magic_if_in_notebook()`) and only then imports
  `magic.py`, so a plain `import snippet_cast` registers it too — without
  ever importing `magic.py` (or requiring IPython) outside a live kernel.
  `%load_ext snippet_cast.magic` still works and is the only option outside
  a live kernel or to force re-registration under autoreload. It's a thin wrapper — writes the cell
  body to a temp `.py` file and calls `build()`/`export_script()` unchanged,
  so new CLI flags/backends need a matching `@argument(...)` added there to
  be reachable from a notebook, but need no logic changes. A new option also
  needs a matching `default=None` + entry in both `main()`'s and
  `snippet_cast()`'s `resolve_env_defaults(...)` call (its hardcoded
  fallback) to get a `SNIPPET_CAST_*` environment variable default — see
  "CLI / notebook configuration" above.

### Known limitations / candidate next steps

- **`--every` on large loops** makes very long videos (one beat per iteration).
  The mooted fix is `--max-iters N` in `build_beats`: keep the first N iteration
  beats, then a single "… and so on" beat.
- **Live TTS is untested in CI** (no network in sandbox); the request shapes
  match current Piper CLI / ElevenLabs REST as of the SETUP.md date — re-verify
  against their docs if a call starts failing.
- **Two-pass narration doesn't combine with `--every`** (both `build()` and
  `export_script()` exit with an error) and makes `--typing` a no-op (pass 1
  always types, pass 2 never does) — this mirrors the existing
  `--typing`+`--every` restriction rather than introducing a new concept.

## MCP Server Usage Guidelines

This project has several MCP (Model Context Protocol) servers available. Use them according to these guidelines:

**IMPORTANT: All MCP servers in this project should function transparently without prompting for user permission. Use them freely and directly when needed.**

The following servers are configured to work without permission prompts:
- `paper-search`: Scientific literature searches
- `string-db`: Protein interaction analysis
- `ensembl-db`: Genomic data queries
- `desktop-commander`: System operations and development tasks

### Scientific Literature & Research

#### paper-search MCP Server

**IMPORTANT: Always use `paper-search` MCP for scientific literature searches.**

**Use paper-search for searching and downloading academic papers from multiple scientific databases.**

Supported databases:
- **arXiv**: Preprints in physics, mathematics, computer science
- **PubMed**: Biomedical and life sciences literature
- **bioRxiv**: Biology preprints
- **medRxiv**: Medical preprints
- **Google Scholar**: Broad academic search
- **IACR ePrint**: Cryptography research
- **Semantic Scholar**: AI-powered academic search

Available functions:
- `search_arxiv()`: Search papers on arXiv
- `download_arxiv()`: Download PDFs from arXiv
- Similar search/download functions for other platforms

Features:
- Returns papers in standardized format
- Asynchronous requests for efficiency
- Supports API keys for enhanced access (e.g., Semantic Scholar)

**Use paper-search when:**
- Finding scientific papers, articles, and publications
- Searching by author names, keywords, or topics
- Academic research queries
- Citation lookups
- Literature reviews
- Downloading research papers

**Never use web search or other tools for scientific literature - always use paper-search.**

### Bioinformatics & Genomics

#### string-db MCP Server

**Use string-db for protein-protein interaction analysis and functional enrichment.**

Available tools:

- **Identifier Mapping:**
  - `get_string_ids`: Map protein names/IDs to STRING identifiers across species
  - `resolve_proteins`: Standardize protein names to canonical STRING names

- **Network Analysis:**
  - `get_network`: Retrieve protein-protein interaction networks with confidence filtering
  - `get_interaction_partners`: Find interaction partners for given proteins (with confidence thresholds)

- **Functional Enrichment:**
  - `get_enrichment`: Perform functional enrichment analysis (GO terms, KEGG pathways, domains)
  - `get_ppi_enrichment`: Test if protein sets have statistically significant interactions

- **Cross-Species Analysis:**
  - `get_homology`: Retrieve protein homology information across species
  - `get_homology_best`: Find best homology matches in target species

- **Utility:**
  - `get_version`: Get current STRING database version

**Supported species (common):**
- Human (9606), Mouse (10090), Rat (10116)
- Fruit fly (7227), C. elegans (6239), Yeast (4932)

**Use string-db when:**
- Analyzing protein interactions and networks
- Performing functional enrichment analysis
- Mapping proteins across species
- Finding interaction partners or homologs
- Testing for PPI enrichment in protein sets

#### ensembl-db MCP Server

**Use ensembl-db for genomic data retrieval and analysis via the Ensembl REST API.**

Available tools (31 endpoints across 11 categories):

- **Gene Lookup:**
  - `lookup_gene_by_symbol`: Find genes by symbol (e.g., BRCA2)
  - `lookup_gene_by_id`: Find genes by Ensembl stable ID

- **Sequence Retrieval:**
  - `get_sequence`: Retrieve DNA/RNA/protein sequences

- **Variant Analysis:**
  - `get_variants_for_region`: Find genetic variants in genomic regions
  - `vep_region`: Predict variant consequences (Variant Effect Predictor)

- **Cross-Species Homology:**
  - `get_homology`: Find homologous genes/proteins across species

- **Phenotype Data:**
  - `get_phenotype_by_gene`: Retrieve phenotype annotations for genes

- **Regulatory Features:**
  - `get_regulatory_features`: Find regulatory elements in genomic regions

- **Overlap Analysis:**
  - `overlap_region`, `overlap_id`, `overlap_translation`: Find overlapping genomic features

- **Cross-References:**
  - `get_xrefs_by_gene`, `get_xrefs_by_symbol`, `get_xrefs_by_name`: External database references

- **Coordinate Mapping:**
  - Tools for mapping between assemblies and genomic/protein coordinates

- **Ontology & Taxonomy:**
  - Search and retrieve ontology terms and taxonomy information

**Use ensembl-db when:**
- Looking up genes by symbol or ID
- Retrieving genomic sequences
- Analyzing genetic variants and their effects
- Finding gene homologs across species
- Exploring phenotype associations
- Identifying regulatory features
- Mapping between genome assemblies

### System Operations

#### desktop-commander MCP Server

**Use desktop-commander for advanced system interaction, terminal control, and development tasks.**

Available capabilities:

- **Terminal Control:**
  - Execute terminal commands with output streaming
  - Run long-running commands in background
  - Manage and kill processes
  - Monitor command output in real-time

- **Filesystem Operations:**
  - Read/write files
  - Create/list directories
  - Move files and directories
  - Search files across filesystem
  - Get file metadata
  - Negative offset reading (like Unix `tail`)

- **Code Editing:**
  - Surgical text replacements in files
  - Full file rewrites
  - Multiple file editing
  - Pattern-based replacements
  - VSCode-ripgrep recursive code/text search

- **Development Environment:**
  - Execute code in memory (Python, Node.js, R)
  - Instant data analysis for CSV/JSON files
  - Interact with development servers and databases

**Use desktop-commander when:**
- Running terminal commands or shell scripts
- Managing processes or background tasks
- Performing filesystem operations
- Editing code or text files
- Searching code across the project
- Executing code snippets for quick analysis
- Interacting with development servers

### General Purpose

- **filesystem**: File operations within the workspace
- **fetch**: Web content fetching for non-scientific content
- **memory**: Persistent memory across conversations

## Project Context

- **Field**: Bioinformatics / Computational Biology
- **Primary Language**: Python
- **Environment**: Devcontainer with pixi package management

## Code Style Preferences

- Follow existing code style in the repository
- Use type hints in Python code
- Include docstrings for functions and classes
- Follow scientific computing best practices

## Citation Format

When adding inline citations to scientific papers, use Author-Year format:
- Up to two authors: (Munch, 2025) or (Munch and Hobolth, 2025)
- Three or more: (Munch et al., 2025)
- Citation labels should be hyperlinks to the paper on the journal website

## Notes

- This project uses MCP servers for enhanced capabilities
- The devcontainer includes pixi for package management
- MCP servers use pixi environments (conda packages + pip when needed)
- PyPI-based servers are installed with pip in the shared pixi environment to ensure Python headers are available
