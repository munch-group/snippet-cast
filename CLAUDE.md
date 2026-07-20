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
pixi run snippet-cast test/data/twopass.py --export-script                      # narration script to record

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
| `src/snippet_cast/__init__.py` | Public API: exports `build` (programmatic), `export_script`, and `main` (CLI entry point). |
| `src/snippet_cast/magic.py` | Jupyter `%%snippet-cast` cell magic (`pip install snippet-cast[jupyter]`, `%load_ext snippet_cast.magic`). Deliberately **not** imported from `__init__.py`, so `import snippet_cast` never requires IPython — it's a thin wrapper: writes the cell to a temp `.py` file, calls `build()`/`export_script()`, displays the result with `IPython.display.Video`. |
| `SETUP.md` | How to install/configure the Piper and ElevenLabs TTS backends. |
| `test/data/fib.py`, `test/data/loop.py`, `test/data/twopass.py` | Sample annotated snippets used by tests and for manual verification (`twopass.py` exercises `/`-split, two-pass narration). |
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

#### Two-pass narration (orthogonal to the above, first-exec only)

`split_narration(text)` splits a `#:` narration on the first `/` into
`(part1, part2)`. If **any** marker's raw text contains `/`, `build()` takes an
early branch (`build()`'s `two_pass` flag) that calls `_two_pass_beats()` —
which calls the *unmodified* `build_beats()` **twice**: once with
`steps=[]` (part1 text; forces `state={}` everywhere, since `first.get(...)`
always misses) for **pass 1** ("writing" — always typed, via
`make_pass1_code_clip()`/`probe_duration()`, narration and typing start
together, opening on a blank canvas (`typing_frames()`'s `start_blank` path),
and the clip is sized to the narration's real duration), and once with the
real `steps` (part2 text) for **pass 2** ("walkthrough" — same per-beat
highlight/state/narration as single-pass first-exec mode, but
`_render_two_pass()` deliberately ignores each beat's `revealed` here and
always composes the full code pass 1 already typed (`_visible_code(code_lines,
final_revealed)`, `final_revealed = beats1[-1].revealed`) — only the
highlight and state panel move per beat; the code is never hidden and
re-revealed). `_render_two_pass()` renders all of pass 1 then all of pass 2,
concatenated into one video. A file with no `/` anywhere never takes this
branch — the original single-pass loop in `build()` is untouched, so behavior
for existing snippets doesn't change.

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
10. **A pass-1 "writing" clip's video is never shorter than its narration
    audio.** `make_pass1_code_clip()` sizes frame count from
    `ceil(duration * FPS)` (rounding up), so `make_typing_clip`'s `-shortest`
    only ever trims a sliver of excess video — it must never truncate real
    narration. Only the *silent* (empty part1) sub-case is capped by
    `TYPE_MAXFRAMES`; the narrated sub-case is deliberately uncapped.
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
- Private helpers are `_prefixed`. Rendering is split: `_render_code` (pygments)
  vs `render_panel`/`_draw_caption` (hand-drawn PIL).

### Common changes

- **Add a TTS backend:** write `synth_x(text, out)->path`, add to `BACKENDS`. Done.
- **Change theme/font:** edit `STYLE` (any pygments style) and `FONT_NAME` /
  `FONT_SIZE`; panel/caption colours are constants. Both the hand-drawn panel
  (`_mono_font`) and the pygments code frame (`_render_code`) resolve a font
  file via `_mono_font_path()`/`_FONT_CANDIDATES` first, falling back to
  `FONT_NAME`'s by-name OS lookup only if none of those paths exist — add
  paths to `_FONT_CANDIDATES` for a new platform/font rather than relying on
  `FONT_NAME` alone, since pygments resolves bare names against the OS's
  installed fonts (e.g. "DejaVu Sans Mono" isn't a stock macOS font).
- **Change the narration marker:** `MARKER` (keep it a valid `#` comment prefix).
- **Adjust typing speed:** default is `TYPE_SPEED` (seconds/char), overridable
  per-run with `--typing-speed`; `TYPE_MAXFRAMES` is a safety cap on frames
  per beat regardless of speed.
- **Two-pass narration:** add `/` to a `#:` narration (`split_narration`);
  first-exec only, auto-detected, no flag needed. `TWO_PASS_SEP` changes the
  separator character; `PART2_EMPTY_HOLD` is how long the walkthrough pass
  holds a beat whose part2 text is empty.
- **Custom narration order:** add a leading `N)` to a `#:` narration
  (`_parse_order`/`order_markers`, `_ORDER_RE`); first-exec only, per-pass in
  two-pass mode, no flag needed — all-or-none per pass, else `sys.exit`.
- **Manual-recording tooling:** `--export-script` (`export_script()` /
  `_format_script()`) and `--tts manual` (`make_manual_backend()`) — see the
  "Two-pass narration" architecture note above for how their numbering stays
  aligned with `build()`'s own audio-request order.
- **Jupyter `%%snippet-cast` cell magic:** lives in `src/snippet_cast/magic.py`
  (`SnippetCastMagics`, loaded via `%load_ext snippet_cast.magic`). It's a thin
  wrapper — writes the cell body to a temp `.py` file and calls `build()`/
  `export_script()` unchanged, so new CLI flags/backends need a matching
  `@argument(...)` added there to be reachable from a notebook, but need no
  logic changes.

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
